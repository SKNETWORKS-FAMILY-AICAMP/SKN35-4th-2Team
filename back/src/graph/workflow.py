from langgraph.graph import END, START, StateGraph

from src.agent.answer_agent import answer_agent
from src.agent.general_agent import general_agent
from src.agent.mcp_agent import mcp_node
from src.agent.multi_modal_agent import multi_modal_node
from src.agent.rag_agent import rag_node
from src.graph.node.supervisor_node import supervisor_node
from src.graph.state import State


def reset_turn_state_node(state):
    print("reset_turn_state 진입", end="\n\n")

    return {
        "route": "",
        "reason": "",
        "completed_routes": [],
        "retrieved_docs": [],
        "mcp_results": [],
        "answer": "",
    }


def route_from_supervisor(state):
    print("route_from_supervisor 진입", end="\n\n")

    print("선택된 Agent : ", state["route"], end="\n\n")
    return state["route"]


def workflow():
    builder = StateGraph(State)

    builder.add_node("reset_turn_state", reset_turn_state_node)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("general", general_agent())
    builder.add_node("answer", answer_agent())
    builder.add_node("rag", rag_node)
    builder.add_node("mcp", mcp_node)
    builder.add_node("multi_modal", multi_modal_node)

    builder.add_edge(START, "reset_turn_state")
    builder.add_edge("reset_turn_state", "supervisor")

    builder.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "rag": "rag",
            "mcp": "mcp",
            "multi_modal": "multi_modal",
            "general": "general",
            "answer": "answer",
        },
    )

    builder.add_edge("rag", "supervisor")
    builder.add_edge("mcp", "supervisor")
    builder.add_edge("multi_modal", "supervisor")

    builder.add_edge("general", END)
    builder.add_edge("answer", END)

    graph = builder.compile()

    return graph
