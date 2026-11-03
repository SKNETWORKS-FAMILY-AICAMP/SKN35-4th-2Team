"""
멀티모달 에이전트: 사용자가 올린 이미지(최대 3장)를 읽어서 항목이 있는 글로 옮긴다.

    State.image  -->  [이 에이전트]  -->  State.image_analysis (문자열 하나)

이 파일 하나에 전체 흐름이 보이도록 했다 (rag_agent.py, mcp_agent.py와 같은 방식).
각 단계의 노드는 src/graph/node/multi_modal/ 에, 단계가 실제로 하는 일은 src/multi_modal/ 에 있다.

    START
      │
      ▼
    validate_images ──(읽을 이미지 없음)──────────────────────────┐
      │                                                           │
      ▼                                                           │
    resize_images                                                 │
      │                                                           │
      ▼                                                           │
    encode_images ────(변환 실패)─────────────────────────────────┤
      │                                                           │
      ▼                                                           ▼
    read_images ────────────────────────────────────────▶ build_analysis
                                                                  │
                                                                  ▼
                                                                 END

- Supervisor가 route="multi_modal"을 고르면 multi_modal_node가 실행되고, 끝나면 다시 Supervisor로 돌아간다.
- 이미지는 "원본 바이트"로 받는다. 화면에 다시 보여 주는 용도의 저장은 이 에이전트가 아니라 그래프 밖(UI의 record_user_turn)이 한다.
  이 에이전트는 DB를 모른다.
- 어떤 단계가 실패해도 예외를 던지지 않는다. 실패했다는 안내가 image_analysis에 들어가고 그래프는 계속 진행된다.
- 이미지 바이트와 base64는 이 하위 그래프 안에서만 오간다. 메인 State에는 읽은 글(image_analysis)만 돌려준다.
- 설정값은 src/const/multi_modal_config.py, 프롬프트는 src/prompt/multi_modal_prompt.py에 있다.
"""

from langgraph.graph import END, START, StateGraph

from src.graph.node.multi_modal.build_analysis_node import build_analysis_node
from src.graph.node.multi_modal.encode_images_node import encode_images_node
from src.graph.node.multi_modal.read_images_node import read_images_node
from src.graph.node.multi_modal.resize_images_node import resize_images_node
from src.graph.node.multi_modal.validate_images_node import validate_images_node
from src.graph.state import MultiModalState, State


def route_after_validate(state: MultiModalState) -> str:
    # 읽을 수 있는 이미지가 하나도 없으면 모델을 부르지 않고 안내만 정리한다
    return "resize_images" if state.get("images") else "build_analysis"


def route_after_encode(state: MultiModalState) -> str:
    # 변환에 실패했으면 읽을 수 없으니 바로 정리로 간다 (그때 raw_text=None이 들어 있다)
    return "build_analysis" if state.get("raw_text", "") is None else "read_images"


def multi_modal_agent():
    builder = StateGraph(MultiModalState)

    builder.add_node("validate_images", validate_images_node)
    builder.add_node("resize_images", resize_images_node)
    builder.add_node("encode_images", encode_images_node)
    builder.add_node("read_images", read_images_node)
    builder.add_node("build_analysis", build_analysis_node)

    builder.add_edge(START, "validate_images")
    builder.add_conditional_edges(
        "validate_images",
        route_after_validate,
        {"resize_images": "resize_images", "build_analysis": "build_analysis"},
    )
    builder.add_edge("resize_images", "encode_images")
    builder.add_conditional_edges(
        "encode_images",
        route_after_encode,
        {"read_images": "read_images", "build_analysis": "build_analysis"},
    )
    builder.add_edge("read_images", "build_analysis")
    builder.add_edge("build_analysis", END)

    return builder.compile()


def multi_modal_node(state: State):
    # completed_routes에 "multi_modal"을 더해 돌려준다 (rag_node, mcp_node와 같다).
    # Supervisor는 이 목록을 보고 이미 끝낸 route를 다시 고르지 않는다.
    completed = [*(state.get("completed_routes") or []), "multi_modal"]

    result = multi_modal_agent().invoke(
        {
            "messages": state.get("messages", []),
            "original_question": state.get("original_question", ""),
            "image": state.get("image"),
        },
    )

    update = {"image_analysis": result["image_analysis"], "completed_routes": completed}
    if result.get("question_with_image") is not None:
        update["original_question"] = result["question_with_image"]
    return update
