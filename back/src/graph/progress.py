"""
답변이 나오는 과정의 "큰 단계"를 화면에 알려 주기 위한 약속 (SUPERVISOR, RAG, MCP, MULTI_MODAL, ANSWER).

이 파일은 단계의 이름과 규칙만 정한다. 화면(chat.py)이나 서비스 연결부(chat_service.py)는 건드리지 않는다.
연결과 표시는 각 담당자가 아래 "사용법"대로 한다.

단계를 알아내는 방법
- 그래프가 노드 하나를 끝낼 때마다 LangGraph가 (노드 이름, 갱신 값)을 알려 준다 (stream_mode="updates").
- Supervisor가 route를 고르면 다음에 실행될 노드가 곧 그 route다. 그래서 route가 바뀌는 순간이 그 단계에 들어가는 순간이다.
    supervisor가 route="rag"를 정함  -->  "RAG · 공식 문서를 검색하는 중"
- rag, mcp, multi_modal이 끝나면 Supervisor가 다시 판단한다 -->  "SUPERVISOR · 다음 단계를 판단하는 중"

단계 이름 (화면에 그대로 보여 줘도 된다)
    LOADING  준비 · 모델을 불러오는 중 (앱을 켠 뒤 첫 질문만. 약 30초)
    START    SUPERVISOR · 질문을 분석하는 중
    NEXT     SUPERVISOR · 다음 단계를 판단하는 중
    BY_ROUTE multi_modal / rag / mcp / general / answer 별 이름

사용법

1) chat_service.run_chat (서비스 연결부 담당): 이미 있는 stream 반복문에 몇 줄만 더한다.

    from src.graph.progress import StageReporter

    def run_chat(messages, ..., on_token=None, on_stage=None):
        reporter = StageReporter(on_stage)
        ...
        reporter.loading_if_first_run()          # get_graph()를 부르기 전에 (첫 질문은 모델을 불러오느라 오래 걸린다)
        engine = graph if graph is not None else get_graph()
        if on_token is None and on_stage is None:
            result = engine.invoke(state, config=config)
        else:
            reporter.start()
            for kind, event in engine.stream(state, config=config, stream_mode=["messages", "updates"]):
                ...
                elif kind == "updates":
                    for node_name, update in event.items():
                        ...                       # 기존 처리
                        reporter.node_finished(node_name, update)

   run_db_chat과 generate_answer는 on_stage를 그대로 넘겨 주기만 하면 된다.

2) chat.py (화면 담당): 단계 이름이 올 때마다 화면을 바꾼다.

    with st.status("질문을 분석하고 있어요…") as progress:
        result = generate_answer(..., on_token=show_token, on_stage=lambda label: progress.update(label=label))
        progress.update(label="답변 완성", state="complete")

   on_stage는 단계가 바뀔 때만 (같은 이름을 연달아 알리지 않는다) 호출되고, 이름은 위의 문자열 하나다.

한계
- 큰 단계만 알린다. RAG 안의 세부 단계(질문 재작성, 재정렬 등)는 알리지 않는다.
- 단계는 "노드가 끝난 뒤" 알 수 있어서, Supervisor가 route를 고른 시점(= 그 단계에 들어가는 시점)에 알린다.
"""

import sys

LOADING = "준비 · 모델을 불러오는 중 (앱을 켠 뒤 첫 질문만 오래 걸려요)"
START = "SUPERVISOR · 질문을 분석하는 중"
NEXT = "SUPERVISOR · 다음 단계를 판단하는 중"
BY_ROUTE = {
    "multi_modal": "MULTI_MODAL · 이미지에서 내용을 읽는 중",
    "rag": "RAG · 공식 문서를 검색하는 중",
    "mcp": "MCP · 외부 도구로 사실을 확인하는 중",
    "general": "ANSWER · 답변을 작성하는 중",
    "answer": "ANSWER · 답변을 작성하는 중",
}


def stage_for(node_name, update):
    """그래프 노드 하나가 끝났을 때(updates 이벤트) 화면에 보여 줄 다음 단계 이름. 보여 줄 것이 없으면 None."""
    if node_name == "supervisor":
        route = update.get("route") if isinstance(update, dict) else None
        return BY_ROUTE.get(route)
    if node_name in ("rag", "mcp", "multi_modal"):
        return NEXT
    return None


class StageReporter:
    """단계가 바뀔 때만 on_stage(단계 이름)를 부른다. on_stage가 없으면 아무 일도 하지 않는다."""

    def __init__(self, on_stage=None):
        self.on_stage = on_stage
        self.last = None

    def announce(self, label):
        if self.on_stage and label and label != self.last:  # 같은 단계를 연달아 알리지 않는다
            self.last = label
            self.on_stage(label)

    def loading_if_first_run(self):
        """앱을 켠 뒤 처음 그래프를 만들기 전에 부른다 (이미 불러왔다면 아무것도 알리지 않는다)."""
        if "src.graph.workflow" not in sys.modules:
            self.announce(LOADING)

    def start(self):
        self.announce(START)

    def node_finished(self, node_name, update):
        self.announce(stage_for(node_name, update))
