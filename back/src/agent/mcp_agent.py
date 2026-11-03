"""
MCP 에이전트: 질문에 맞는 MCP 도구를 골라 부르고, 결과를 State.mcp_results에 담는다.

이 파일 하나에 전체 흐름이 보이도록 했다 (rag_agent.py와 같은 방식). 각 단계의 일은 src/graph/node/mcp/ 의 노드가 한다.
메인 그래프에는 mcp_node를 노드로 붙인다 (workflow.py: builder.add_node("mcp", mcp_node), builder.add_edge("mcp", "supervisor")).

    START
      │
      ▼
    list_tools ──(도구 없음)──────────────────────────────────────┐
      │                                                           │
      ▼                                                           │
    select_tool ◀──────────────┐   모델이 도구와 인자를 고른다     │
      │                        │   (도구를 안 골랐으면 바로 정리로)  │
      ▼                        │                                   │
    validate_call ──(오류)──▶ route_on_error ─(다시 고를 수 있음)──┘ ← select_tool로 되돌아감
      │                        ▲                                   │
      ▼                        │                                   │
    call_tool ───(오류)────────┘                                   │
      │                                                           │
      ▼                                                           ▼
    format_results ◀──────────(다시 고를 수 없음 / 횟수 초과 / 도구 안 고름)
      │
      ▼
     END

다시 고르는 조건 (route_on_error)
- 오류가 "고칠 수 있는 종류"이고 (없는 도구, 잘못된 인자, 이미 실패한 호출 반복, 도구 자체의 실패),
- 지금까지 고른 횟수가 MAX_ATTEMPTS(src/const/mcp_config.py)보다 적을 때만 select_tool로 되돌아간다.
- 서버를 못 띄움, 시간 초과, 모델 호출 실패는 도구를 바꿔도 소용없으므로 바로 정리로 간다.
- 결과가 비어 있는 경우는 다시 고르지 않는다.
"""

from langgraph.graph import END, START, StateGraph

from src.const import mcp_config as cfg
from src.graph.node.mcp.call_tool_node import call_tool_node
from src.graph.node.mcp.format_results_node import failed_record, format_results_node
from src.graph.node.mcp.list_tools_node import list_tools_node
from src.graph.node.mcp.select_tool_node import select_tool_node
from src.graph.node.mcp.validate_call_node import validate_call_node
from src.graph.state import MCPState, State
from src.mcp_integration.client.tools import describe_error


def route_after_list_tools(state: MCPState):
    return "format_results" if state.get("mcp_error") else "select_tool"


def route_after_select_tool(state: MCPState):
    # 모델 호출이 실패했거나 도구를 고르지 않았으면 더 갈 곳이 없다
    if state.get("mcp_error") or state.get("mcp_call") is None:
        return "format_results"
    return "validate_call"


def route_on_error(state: MCPState):
    error = state["mcp_error"]
    if error["retryable"] and state.get("mcp_attempts", 0) < cfg.MAX_ATTEMPTS:
        return "select_tool"
    return "format_results"


def route_after_validate_call(state: MCPState):
    return route_on_error(state) if state.get("mcp_error") else "call_tool"


def route_after_call_tool(state: MCPState):
    return route_on_error(state) if state.get("mcp_error") else "format_results"


def mcp_node(state: State):
    """메인 그래프에 붙이는 노드 (workflow.py에서 builder.add_node("mcp", mcp_node)). rag_agent.py의 rag_node와 같은 방식이다.

    MCP 에이전트를 실행해서 부모로는 mcp_results와 completed_routes만 돌려준다. 이 노드를 쓰는 이유는 세 가지다.
    - MCP는 "있으면 좋은 보조 정보"라서, 안에서 예상하지 못한 오류가 나더라도 질문 전체가 실패하면 안 된다.
      오류를 잡아서 "실패" 결과로 바꿔 돌려주면, 이어지는 answer 노드가 "조회에 실패했다"고 알리며 계속 답할 수 있다.
    - 부모로 돌아가는 값을 분명히 제한한다 (서브그래프를 노드로 직접 붙이면 부모와 이름이 같은 키가 모두 돌아간다).
    - completed_routes에 "mcp"를 더해 돌려준다 (rag_node가 "rag"를 더하는 것과 같다).
      Supervisor는 이 목록을 보고 이미 끝낸 route를 다시 고르지 않는다. 이게 없으면 MCP가 끝났는지 몰라 계속 mcp를 고르게 된다.
    """
    previous = list(state.get("mcp_results") or [])
    completed = [*(state.get("completed_routes") or []), "mcp"]
    try:
        result = mcp_agent().invoke(
            {
                "messages": state.get("messages", []),
                "original_question": state.get("original_question", ""),
                "image_analysis": state.get("image_analysis") or "",
                "mcp_results": previous,
            }
        )
        return {"mcp_results": result["mcp_results"], "completed_routes": completed}
    except Exception as exc:
        return {"mcp_results": [*previous, failed_record(describe_error(exc))], "completed_routes": completed}


def mcp_agent():
    builder = StateGraph(MCPState)

    builder.add_node("list_tools", list_tools_node)
    builder.add_node("select_tool", select_tool_node)
    builder.add_node("validate_call", validate_call_node)
    builder.add_node("call_tool", call_tool_node)
    builder.add_node("format_results", format_results_node)

    builder.add_edge(START, "list_tools")
    builder.add_conditional_edges(
        "list_tools", route_after_list_tools, {"select_tool": "select_tool", "format_results": "format_results"}
    )
    builder.add_conditional_edges(
        "select_tool", route_after_select_tool, {"validate_call": "validate_call", "format_results": "format_results"}
    )
    builder.add_conditional_edges(
        "validate_call",
        route_after_validate_call,
        {"call_tool": "call_tool", "select_tool": "select_tool", "format_results": "format_results"},
    )
    builder.add_conditional_edges(
        "call_tool", route_after_call_tool, {"select_tool": "select_tool", "format_results": "format_results"}
    )
    builder.add_edge("format_results", END)

    return builder.compile()
