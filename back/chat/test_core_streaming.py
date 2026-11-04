"""코어(src/app/chat_service.run_chat)의 답변 스트리밍 규칙을 가짜 그래프로 확인한다. 실제 AI, 검색, DB는 쓰지 않는다.

PR #4가 코어의 stream 호출을 subgraphs=True로 바꿨다. 이 테스트는 그 변경이 의도대로 동작하고 나중에 실수로 되돌려지지 않게 지킨다.
  - 답변 글자(token)는 하위 그래프 안의 답변 노드(answer, general)에서만 화면으로 나간다.
  - 하위 그래프(RAG 등) 내부 노드의 갱신과 단계는 결과와 진행 단계에 섞이지 않는다 (최상위 그래프만 쓴다).

    uv run python back/manage.py test chat
"""

from langchain_core.messages import AIMessage, AIMessageChunk
from django.test import SimpleTestCase

from src.app.chat_service import run_chat
from src.graph.progress import BY_ROUTE, NEXT, START

QUESTION = [{"role": "user", "content": "질문"}]


class FakeEngine:
    """LangGraph 그래프처럼 stream/invoke를 흉내 낸다. subgraphs=True이면 (경로, 종류, 내용) 3개씩 돌려준다."""

    def __init__(self, events=(), invoke_result=None):
        self.events = list(events)
        self.invoke_result = invoke_result
        self.stream_calls = []
        self.invoke_calls = 0

    def stream(self, state, config=None, stream_mode=None, subgraphs=False):
        self.stream_calls.append({"stream_mode": stream_mode, "subgraphs": subgraphs})
        yield from self.events

    def invoke(self, state, config=None):
        self.invoke_calls += 1
        return self.invoke_result


def token(text, node="answer_node", path=("answer:1",)):
    return (path, "messages", (AIMessageChunk(content=text), {"langgraph_node": node}))


def top(update):
    """최상위 그래프(경로가 비어 있음)의 노드 갱신."""
    return ((), "updates", update)


def inner(update, path=("rag:1",)):
    """하위 그래프 안쪽 노드의 갱신."""
    return (path, "updates", update)


def run(events, **callbacks):
    tokens, stages = [], []
    engine = FakeEngine(events)
    result = run_chat(QUESTION, graph=engine, on_token=tokens.append, on_stage=stages.append, **callbacks)
    return result, tokens, stages, engine


class StreamingRuleTests(SimpleTestCase):
    def events(self):
        return [
            top({"supervisor": {"route": "rag"}}),
            inner({"supervisor": {"route": "mcp"}}),  # 하위 그래프 안의 판단은 단계로 알리지 않는다
            token("내부 검색어 재작성", node="query_rewrite", path=("rag:1",)),  # 답변 노드가 아니므로 화면에 보내지 않는다
            top({"rag": {"retrieved_docs": []}}),
            top({"supervisor": {"route": "answer"}}),
            token("안"),
            token("녕"),
            top({"answer": {"messages": [AIMessage(content="안녕")], "answer": "안녕"}}),
            # 아래 두 갱신은 하위 그래프 안쪽 것이라, 섞였다면 최종 답변이 바뀌거나 route가 mcp로 바뀌어 오류가 난다
            inner({"answer_node": {"answer": "내부 값이 섞임"}}, path=("answer:1",)),
            inner({"supervisor": {"route": "mcp"}}),
        ]

    def test_only_answer_node_tokens_reach_the_screen(self):
        result, tokens, _, _ = run(self.events())
        self.assertEqual(tokens, ["안", "녕"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["answer"], "안녕")  # 하위 그래프의 갱신이 최종 답변을 바꾸지 않는다

    def test_stages_follow_top_level_graph_only(self):
        _, _, stages, _ = run(self.events())
        self.assertEqual(stages, [START, BY_ROUTE["rag"], NEXT, BY_ROUTE["answer"]])

    def test_stream_is_requested_with_subgraphs(self):
        """답변 노드가 하위 그래프 안에 있어서 subgraphs=True여야 답변 글자가 실시간으로 나온다 (이전 방식은 한꺼번에 도착했다)."""
        _, _, _, engine = run(self.events())
        self.assertEqual(engine.stream_calls, [{"stream_mode": ["messages", "updates"], "subgraphs": True}])
        self.assertEqual(engine.invoke_calls, 0)

    def test_general_node_tokens_are_streamed_too(self):
        events = [
            top({"supervisor": {"route": "general"}}),
            token("안", node="general", path=("general:1",)),
            token("녕", node="general_node", path=("general:1",)),
            top({"general": {"messages": [AIMessage(content="안녕")], "answer": "안녕"}}),
        ]
        result, tokens, stages, _ = run(events)
        self.assertEqual(tokens, ["안", "녕"])
        self.assertEqual(result["answer"], "안녕")
        self.assertEqual(stages, [START, BY_ROUTE["general"]])

    def test_tokens_given_as_content_blocks_are_joined(self):
        """모델에 따라 답변 조각이 글자가 아니라 [{"type": "text", "text": ...}] 목록으로 온다."""
        block = (("answer:1",), "messages", (AIMessageChunk(content=[{"type": "text", "text": "가"}, {"type": "text", "text": "나"}]), {"langgraph_node": "answer"}))
        events = [block, top({"answer": {"messages": [AIMessage(content="가나")], "answer": "가나"}})]
        result, tokens, _, _ = run(events)
        self.assertEqual(tokens, ["가나"])
        self.assertEqual(result["status"], "success")

    def test_streamed_text_equals_final_answer(self):
        result, tokens, _, _ = run(self.events())
        self.assertEqual("".join(tokens), result["answer"])


class NoCallbackTests(SimpleTestCase):
    def test_without_callbacks_the_graph_is_invoked_once_without_streaming(self):
        final = {"messages": [AIMessage(content="답")], "answer": "답"}
        engine = FakeEngine(invoke_result=final)
        result = run_chat(QUESTION, graph=engine)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["answer"], "답")
        self.assertEqual((engine.invoke_calls, engine.stream_calls), (1, []))


class FailureTests(SimpleTestCase):
    def test_graph_exception_becomes_error_result_not_a_crash(self):
        class Broken(FakeEngine):
            def stream(self, *args, **kwargs):
                raise RuntimeError("secret-key-123")
                yield  # pragma: no cover

        result = run_chat(QUESTION, graph=Broken(), on_token=lambda t: None)
        self.assertEqual(result["status"], "error")
        self.assertNotIn("secret-key-123", str(result))
