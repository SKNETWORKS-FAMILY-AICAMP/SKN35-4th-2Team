"""
로그인한 사용자의 질문을 받아 3차 코어(LangGraph, RAG, MCP, 멀티모달)로 답을 만들고, 한 조각씩 화면으로 돌려주는 창구.
질문과 답변, 출처는 코어(run_db_chat)가 4차 전용 DB에 저장하고, 이전 대화(이력)도 DB에서 읽는다.

POST /api/chat/   요청 (둘 중 하나)
                    JSON            {"question": "...", "conversation_id": 12}   (conversation_id는 이어서 질문할 때만, 없으면 새 대화)
                    multipart/form-data  question, conversation_id(선택), images(이미지 파일, 여러 개 가능)
                                         이미지는 png/jpeg/webp, 한 번에 3장까지. 이미지만 보내고 질문은 비워도 된다.
                  로그인하지 않았으면 401
                  응답: Server-Sent Events (text/event-stream). 이벤트 종류
                        stage   처리 단계 이름 (문자열)           예: "RAG · 공식 문서를 검색하는 중"
                        token   답변 조각 (문자열)
                        sources 출처 목록 [{title, url, snippet, ...}]
                        done    {"answer": 전체 답변, "conversation_id": 대화 번호}
                        error   {"message": 사용자에게 보여 줄 문장, "conversation_id": 대화 번호 또는 null}
"""

import json
import queue
import threading

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.http.multipartparser import MultiPartParserError
from django.http import HttpResponseNotAllowed, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET

from src.app.chat_service import run_db_chat  # 3차 코어 (수정하지 않는다)
from src.db.images import max_images_per_message  # 한 번에 첨부할 수 있는 이미지 수 (코어와 같은 한도)

from .accounts import current_user_id

LOGIN_REQUIRED = "로그인이 필요합니다."


def sse(event, data):
    """Server-Sent Events 한 건을 만든다."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@ensure_csrf_cookie
@require_GET
def index(request):
    return render(request, "chat.html")


@require_GET
def health(request):
    return JsonResponse({"status": "ok"})


def parse_conversation_id(value, *, from_form):
    """대화 번호를 검사한다. (번호 또는 None, 문제가 있으면 True). 양식(multipart)은 숫자도 문자열로 오므로 그때만 숫자 문자열을 받아 준다."""
    if value is None or (from_form and value == ""):
        return None, False
    if from_form and isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if type(value) is not int or value <= 0:
        return None, True
    return value, False


def parse_request(request):
    """요청을 읽는다. ((질문, 대화 번호 또는 None, 이미지 바이트 목록), None) 또는 (None, 사용자에게 보여 줄 오류 문장)."""
    images = []
    from_form = (request.content_type or "").startswith("multipart/")
    if from_form:
        try:
            question = request.POST.get("question", "")
            raw_conversation_id = request.POST.get("conversation_id")
            files = request.FILES.getlist("images")
        except (SuspiciousOperation, MultiPartParserError):
            return None, "요청 형식이 올바르지 않거나 너무 큽니다."
        if len(files) > max_images_per_message():
            return None, f"이미지는 한 번에 {max_images_per_message()}장까지 첨부할 수 있어요."
        for number, uploaded in enumerate(files, 1):
            if uploaded.size > settings.CHAT_IMAGE_UPLOAD_MAX_BYTES:
                return None, f"이미지 {number}이(가) 너무 큽니다. 한 장에 {settings.CHAT_IMAGE_UPLOAD_MAX_BYTES // 1_000_000}MB 이하로 올려 주세요."
            images.append(uploaded.read())
    else:
        try:
            body = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, "요청 형식이 올바르지 않습니다."
        if not isinstance(body, dict):
            return None, "요청 형식이 올바르지 않습니다."
        question, raw_conversation_id = body.get("question"), body.get("conversation_id")
    if not isinstance(question, str):
        return None, "질문을 입력해 주세요."
    if not question.strip() and not images:  # 이미지가 있으면 질문은 비워도 된다
        return None, "질문을 입력해 주세요."
    if len(question) > settings.CHAT_QUESTION_MAX_CHARS:
        return None, f"질문은 {settings.CHAT_QUESTION_MAX_CHARS:,}자 이하로 입력해 주세요."
    conversation_id, broken = parse_conversation_id(raw_conversation_id, from_form=from_form)
    if broken:
        return None, "대화 정보를 확인해 주세요."
    return (question.strip(), conversation_id, images), None


def event_stream(user_id, question, conversation_id, images=None):
    """코어는 동기 함수라서 별도 스레드에서 돌리고, 나오는 단계와 토큰을 큐로 받아 한 건씩 내보낸다."""
    events = queue.Queue()

    def work():
        try:
            result = run_db_chat(
                question,
                user_id=user_id,
                conversation_id=conversation_id,
                images=images or None,
                on_token=lambda token: events.put(("token", token)),
                on_stage=lambda stage: events.put(("stage", stage)),
            )
            events.put(("result", result))
        except Exception as error:  # 코어의 예외가 화면을 멈추게 하지 않는다
            events.put(("failure", f"{type(error).__name__}"))
        finally:
            events.put(("end", None))

    threading.Thread(target=work, daemon=True).start()
    while True:
        kind, payload = events.get()
        if kind == "end":
            return
        if kind in ("token", "stage"):
            yield sse(kind, payload)
        elif kind == "failure":
            yield sse("error", {"message": "답변을 만드는 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.", "conversation_id": conversation_id})
        elif kind == "result":
            if payload["status"] == "success":
                yield sse("sources", payload.get("sources") or [])
                yield sse("done", {"answer": payload["answer"], "conversation_id": payload.get("conversation_id")})
            else:
                error = payload.get("error") or {}
                yield sse("error", {"message": error.get("message") or "답변을 받지 못했습니다.", "conversation_id": payload.get("conversation_id")})


def chat_stream(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    user_id = current_user_id(request)  # 로그인한 사용자만. user_id는 세션에서만 가져오고 요청 본문으로는 받지 않는다
    if user_id is None:
        return JsonResponse({"error": LOGIN_REQUIRED}, status=401)
    parsed, problem = parse_request(request)
    if problem:
        return JsonResponse({"error": problem}, status=400)
    question, conversation_id, images = parsed
    response = StreamingHttpResponse(event_stream(user_id, question, conversation_id, images), content_type="text/event-stream; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # nginx가 답변을 모았다가 한꺼번에 보내지 않게 한다
    return response
