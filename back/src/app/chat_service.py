"""UI adapter for the unchanged team graph; no retrieval or routing implementation."""
import os
import sys
import threading
from math import isfinite
from urllib.parse import urlsplit
from uuid import uuid4

from langchain_core.messages import AIMessage
from src.graph.progress import LOADING, StageReporter


def text_content(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            block if isinstance(block, str) else block["text"]
            for block in content
            if isinstance(block, str) or (
                isinstance(block, dict) and block.get("type") in ("text", "output_text")
                and isinstance(block.get("text"), str)
            )
        ).strip()
    return ""


def chat_result(answer="", *, status="success", code=None, message=None, sources=None, image_analysis=None):
    return {
        "status": status, "answer": answer, "sources": sources or [],
        "image_analysis": image_analysis,
        "error": {"code": code, "message": message} if code else None,
    }


def document_sources(documents, mcp_results=None):
    """Convert final graph Documents to DB-compatible reference metadata.

    These are documents supplied to the answer node, not verified citations.
    Missing URLs are omitted; no links, versions or grounding claims are invented.
    """
    sources = []
    seen = set()
    for document in documents or []:
        metadata = document.get("metadata") if isinstance(document, dict) else getattr(document, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        url = None
        for key in ("source_url", "url", "github_url"):
            candidate = metadata.get(key)
            if not isinstance(candidate, str):
                continue
            candidate = candidate.strip()
            try:
                parsed = urlsplit(candidate)
                if parsed.scheme in ("http", "https") and parsed.hostname and len(candidate) <= 1000:
                    url = candidate
                    break
            except ValueError:
                continue
        if not url or url in seen:
            continue
        seen.add(url)
        source = {"url": url}
        for output, keys, limit in (
            ("title", ("title",), 300),
            ("tech", ("technology", "tech"), 30),
            ("version", ("version",), 30),
            ("doc_type", ("document_type", "doc_type"), 30),
        ):
            for key in keys:
                value = metadata.get(key)
                if isinstance(value, str) and value.strip():
                    source[output] = value.strip()[:limit]
                    break
        content = document.get("page_content") if isinstance(document, dict) else getattr(document, "page_content", None)
        if isinstance(content, str) and content.strip():
            source["snippet"] = content.strip()[:1000]
        for key in ("rerank_score", "score"):
            score = metadata.get(key)
            if isinstance(score, (int, float)) and not isinstance(score, bool) and isfinite(score):
                source["score"] = float(score)
                break
        sources.append(source)
    # Use the team's shared limits and masking after adapting legacy metadata.
    from src.db import build_sources
    documents = [{"metadata": {
        "source_url": source["url"], "title": source.get("title"),
        "technology": source.get("tech"), "version": source.get("version"),
        "document_type": source.get("doc_type"), "score": source.get("score"),
    }, "page_content": source.get("snippet")} for source in sources]
    return [{key: value for key, value in source.items() if value is not None}
            for source in build_sources(documents, mcp_results)]


# 이미지만 올리고 질문을 쓰지 않았을 때 그래프에 넘기는 질문
# "문제의 원인과 해결 방법"처럼 문제가 있다고 단정하는 문장은 쓰지 않는다. 새 이미지에 문제가 없을 때 모델이 이전 대화의 오류를 다시 설명하기 때문이다.
IMAGE_ONLY_QUESTION = "첨부한 이미지의 내용을 설명해 주세요. 오류가 보이면 원인과 해결 방법도 알려 주세요."
LEGACY_IMAGE_ONLY_QUESTION = "첨부한 이미지의 내용을 확인해 주세요. 오류나 문제가 보이면 원인과 해결 방법을 알려 주세요."  # 예전에 저장된 대화에 남아 있는 문장 (화면에서 같은 방식으로 보여 주려고 남겨 둔다)


def prepare_images(images):
    """첨부 이미지를 DB 한도에 맞춘다: 장수와 형식을 확인하고, 한 장이 크기 한도보다 크면 줄여서 쓴다.

    문제가 있으면 사용자에게 그대로 보여 줄 수 있는 문장으로 ValueError를 낸다.
    """
    items = [bytes(data) for data in (images or []) if data]
    if not items:
        return []
    import io

    from PIL import Image

    from src.db.images import max_image_bytes, max_images_per_message, shrink_image, sniff_mime

    if len(items) > max_images_per_message():
        raise ValueError(f"이미지는 한 번에 {max_images_per_message()}장까지 첨부할 수 있어요.")
    prepared = []
    for number, data in enumerate(items, 1):
        if sniff_mime(data) is None:
            raise ValueError(f"이미지 {number}은(는) png, jpeg, webp 형식이 아니에요.")
        try:
            with Image.open(io.BytesIO(data)) as picture:
                picture.load()
        except Exception as error:
            raise ValueError(f"이미지 {number}을(를) 읽을 수 없어요. 손상되지 않은 이미지를 올려 주세요.") from error
        if len(data) > max_image_bytes():
            try:
                data, _ = shrink_image(data)
            except (ValueError, RuntimeError) as error:
                raise ValueError(f"이미지 {number}을(를) {max_image_bytes() // 1_000_000}MB 이하로 줄이지 못했어요. 더 작은 이미지를 올려 주세요.") from error
        prepared.append(data)
    return prepared


_GRAPH_READY = threading.Event()  # 그래프 모듈(재정렬 모델 포함)을 다 불러왔는지
_warm_lock = threading.Lock()
_warm_started = False
NO_WARM_UP_ENV = "CODECLUE_NO_WARMUP"  # 1이면 앱을 켤 때 미리 불러오지 않는다 (시험용)


def get_graph():
    # Keep dev's checkpointer unchanged. Each request owns its graph and checkpoints.
    from src.graph.workflow import workflow
    _GRAPH_READY.set()  # 이후 질문에서는 "모델을 불러오는 중"을 알리지 않는다
    return workflow()


def _warm_up_steps():
    """첫 질문 때 한꺼번에 걸리던 준비를 미리 한다: 그래프 모듈과 재정렬 모델 불러오기, 검색기(Pinecone, BM25) 준비."""
    get_graph()
    from src.rag.retriever import create_hybrid_retriever

    create_hybrid_retriever(filters=None, use_query_rewrite=False, use_multi_query=False, use_rerank=False)


def warm_up(background=True):
    """앱을 켤 때 한 번 불러서, 첫 질문의 준비 시간(약 10초 이상)을 사용자가 질문을 입력하는 동안 미리 끝내 둔다.

    - 여러 번 불러도 한 번만 실행한다 (Streamlit은 화면을 다시 그릴 때마다 main.py를 다시 실행한다).
    - background=True이면 별도 스레드에서 실행하므로 화면은 바로 뜬다. 준비가 끝나기 전에 질문하면 남은 시간만 기다린다.
    - 실패해도 앱은 멈추지 않는다 (준비를 못 했으면 첫 질문 때 원래대로 불러온다).
    - 환경변수 CODECLUE_NO_WARMUP=1이면 하지 않는다.
    돌려주는 값: 이번 호출에서 실행을 시작했으면 True.
    """
    global _warm_started
    if os.getenv(NO_WARM_UP_ENV) == "1":
        return False
    with _warm_lock:
        if _warm_started:
            return False
        _warm_started = True

    def run():
        try:
            _warm_up_steps()
        except Exception as error:  # 미리 불러오기는 덤이라서 실패해도 무시한다
            print("웜업 실패(무시):", type(error).__name__, str(error)[:200], file=sys.stderr)

    if background:
        threading.Thread(target=run, name="codeclue-warm-up", daemon=True).start()
    else:
        run()
    return True


def unsupported_result():
    return chat_result(status="unsupported", code="UNSUPPORTED_ROUTE", message=
        "요청한 처리 단계가 완료되지 않아 답변을 만들지 못했습니다. 그래프 연결과 종료 조건을 확인해 주세요.")


def result_sources(result):
    """그래프 결과(RAG 문서, MCP 결과)에서 화면과 DB가 같이 쓰는 출처 목록을 만든다.

    출처를 만들지 못해도(예: DB 패키지가 없는 환경) 답변은 그대로 낸다.
    """
    try:
        from src.db import build_sources

        return document_sources(result.get("retrieved_docs"), result.get("mcp_results"))
    except Exception:
        return []


def run_chat(messages, *, conversation_id=None, graph=None, images=None, on_token=None, on_stage=None):
    """Send full bounded history to a fresh graph, using the DB conversation ID.

    Without a DB conversation, temporary UI requests keep their own UUID.
    An injected graph is for tests only; DB calls always construct a fresh graph.
    images: 첨부 이미지(바이트 목록). 그래프의 State.image로 넘어가고, Supervisor가 multi_modal을 골라 읽는다.
    """
    try:
        images = prepare_images(images)
    except ValueError as error:
        return chat_result(status="error", code="INVALID_IMAGE", message=str(error))
    if conversation_id is not None and (
        type(conversation_id) is not int or conversation_id <= 0
    ):
        return chat_result(status="error", code="INVALID_INPUT", message="대화 정보를 확인해 주세요.")
    if not isinstance(messages, list) or not messages or any(
        not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant")
        or not isinstance(m.get("content"), str) for m in messages
    ) or messages[-1]["role"] != "user" or not messages[-1]["content"].strip():
        return chat_result(status="error", code="INVALID_INPUT", message="질문을 입력해 주세요.")
    state = {
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "original_question": messages[-1]["content"],
        "image": images or None, "image_analysis": "", "retrieved_docs": [],
        "mcp_results": [], "answer": "",
    }
    config = {"configurable": {"thread_id": str(conversation_id) if conversation_id is not None else str(uuid4())}}
    try:
        reporter = StageReporter(on_stage)
        if graph is None and not _GRAPH_READY.is_set():
            reporter.announce(LOADING)  # 준비가 아직 끝나지 않았다 (웜업 중이거나 첫 질문)
        engine = graph if graph is not None else get_graph()
        if on_token is None and on_stage is None:
            result = engine.invoke(state, config=config)
        else:
            result = dict(state)
            reporter.start()
            for kind, event in engine.stream(state, config=config, stream_mode=["messages", "updates"]):
                if kind == "messages":
                    chunk, metadata = event
                    if metadata.get("langgraph_node") in ("answer", "general", "answer_node", "general_node"):
                        content = chunk.content
                        token = content if isinstance(content, str) else "".join(
                            block.get("text", "") for block in content
                            if isinstance(block, dict) and block.get("type") in ("text", "output_text")
                        )
                        if token and on_token is not None:
                            on_token(token)
                elif kind == "updates":
                    for node_name, update in event.items():
                        if isinstance(update, dict):
                            result.update(update)
                        reporter.node_finished(node_name, update)
        if result.get("route") in ("rag", "mcp", "multi_modal"):
            return unsupported_result()
        replies = result.get("messages", [])
        if not replies or not isinstance(replies[-1], AIMessage):
            return chat_result(status="error", code="EMPTY_RESPONSE", message="AI 답변을 받지 못했습니다.")
        answer = text_content(result.get("answer")) or text_content(replies[-1].content)
        if not answer:
            return chat_result(status="error", code="EMPTY_RESPONSE", message="AI 답변이 비어 있습니다.")
        analysis = text_content(result.get("image_analysis")) if images else ""
        return chat_result(answer, sources=result_sources(result), image_analysis=analysis or None)
    except Exception as error:
        # dev's conditional edge mapping has no destinations for these routes.
        # Recognize that existing contract failure without changing graph internals.
        if isinstance(error, KeyError) and error.args in (("mcp",), ("multi_modal",)):
            return unsupported_result()
        if type(error).__name__ == "GraphRecursionError":
            return chat_result(status="error", code="GRAPH_RECURSION_LIMIT", message=
                "처리 단계 한도에 도달해 답변을 완료하지 못했습니다. "
                "재검색 횟수와 그래프 종료 조건을 확인해 주세요.")
        notices = {
            "AuthenticationError": "OpenAI 인증에 실패했습니다. API 키를 확인해 주세요.",
            "RateLimitError": "OpenAI 사용 한도 또는 요청 제한에 도달했습니다.",
            "NotFoundError": "설정된 OpenAI 모델을 사용할 수 없습니다.",
            "APITimeoutError": "답변 대기 시간이 초과되었습니다. 다시 시도해 주세요.",
        }
        return chat_result(status="error", code="GRAPH_ERROR", message=notices.get(
            type(error).__name__, "답변을 받지 못했습니다. 모델 설정과 인터넷 연결을 확인해 주세요."
        ))


def run_db_chat(question, *, user_id, conversation_id=None, images=None, on_token=None, on_stage=None):
    """Save the question, fetch bounded DB history once, run a fresh graph, save reply.

    user_id must come from authenticated session state, never from a chat input.
    A returned conversation_id lets the UI continue the same conversation even
    if the model failed after the user's question was saved.
    images: 첨부 이미지(바이트 목록). 질문과 함께 DB에 저장하고(원본과 썸네일), 그래프로 넘겨 읽은 글(image_analysis)을 답변과 함께 저장한다.
    """
    try:
        images = prepare_images(images)
    except ValueError as error:
        return chat_result(status="error", code="INVALID_IMAGE", message=str(error))
    if not isinstance(question, str) or (not question.strip() and not images) or type(user_id) is not int or user_id <= 0 or (
        conversation_id is not None and (type(conversation_id) is not int or conversation_id <= 0)
    ):
        return chat_result(status="error", code="INVALID_INPUT", message="질문과 로그인 정보를 확인해 주세요.")
    current_id = conversation_id
    try:
        from src.db import db_session, get_history_context, record_user_turn, record_assistant_turn
        with db_session() as session:
            turn = record_user_turn(session, user_id, question, conversation_id=conversation_id, images=images or None)
            history = get_history_context(session, turn.conversation_id, user_id)
        current_id = turn.conversation_id
        if images and history and history[-1]["role"] == "user" and not history[-1]["content"].strip():
            history[-1] = {**history[-1], "content": IMAGE_ONLY_QUESTION}  # 이미지만 올린 질문
        # history already includes the current question; do not append it again.
        result = run_chat(history, conversation_id=current_id, images=images, on_token=on_token, on_stage=on_stage)
        result["conversation_id"] = current_id
        if result["status"] == "success":
            with db_session() as session:
                record_assistant_turn(session, user_id, current_id, result["answer"],
                    user_message_id=turn.message_id, sources=result["sources"],
                    image_analysis=result.get("image_analysis") or None)
        return result
    except PermissionError:
        result = chat_result(status="error", code="CONVERSATION_ACCESS_DENIED",
            message="대화가 없거나 접근할 수 없습니다.")
    except ValueError as error:
        # 이미지 오류(장수, 크기, 형식 등)는 그대로 알려 준다. 그 밖의 입력 오류는 기존 안내를 쓴다.
        result = chat_result(status="error", code="INVALID_INPUT",
            message=str(error) if images else "질문 길이와 입력 정보를 확인해 주세요.")
    except Exception:
        result = chat_result(status="error", code="DB_ERROR",
            message="대화를 읽거나 저장하지 못했습니다. DB 연결 상태를 확인해 주세요.")
    result["conversation_id"] = current_id
    return result
