"""
내 대화 목록, 대화 불러오기, 대화 삭제. 모두 로그인한 사용자 본인의 대화만 다룬다 (소유자 확인은 3차 DB 계층이 한다).

GET    /api/attachments/<id>/     → 저장된 이미지 (기본은 썸네일 JPEG, ?size=full이면 원본). 본인 것만, 없거나 남의 것이면 404
GET    /api/conversations/        → {"conversations": [{"id", "title", "updated_at"}, ...]}   최근 수정순
GET    /api/conversations/?q=검색어 → 제목에 검색어가 있는 대화만 (대화 내용은 검색하지 않는다). 공백으로 나눈 단어가 모두 제목에 있으면 찾는다. 대소문자 구분 없음, 검색어는 100자까지, 결과는 50개까지.
                                     검색어가 비어 있으면 전체 목록. 응답 형식은 목록과 같다
GET    /api/conversations/<id>/   → {"id", "title", "messages": [{"role", "content", "sources", "images": [{"id", "width", "height"}], "created_at"}, ...]}   오래된 것부터
DELETE /api/conversations/<id>/   → {}
PATCH  /api/conversations/<id>/   {"title": "새 제목"} → {"id", "title"}   제목 변경 (공백을 뺀 1~100자). 목록 순서는 바뀌지 않고, 직접 바꾼 제목은 첫 질문으로 다시 덮어쓰지 않는다

로그인하지 않았으면 401, 입력이 올바르지 않으면 400({"error": 사용자에게 보여 줄 문장}), 없거나 남의 대화면 404(존재 여부를 알려 주지 않는다), DB 문제면 503. 시각은 UTC ISO 문자열(끝에 Z).
"""

import json
import logging

from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from src.db import db_session, delete_conversation, get_image, image_bytes, list_conversations, list_messages, thumbnail_bytes
from src.db.repository import rename_conversation  # 제목 변경은 코어(3차 DB 계층)의 함수를 쓴다

from .accounts import current_user_id, error
from .queries import QUERY_MAX_CHARS, search_conversations

logger = logging.getLogger(__name__)

LOGIN_REQUIRED = "로그인이 필요합니다."
NOT_FOUND = "대화가 없거나 접근할 수 없습니다."
DB_PROBLEM = "대화를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."


def iso(value):
    """DB의 시각(UTC, 시간대 표시 없음)을 화면이 변환하기 쉬운 문자열로 바꾼다."""
    return value.isoformat() + "Z" if value else None


def image_to_json(attachment):
    return {"id": attachment.id, "width": attachment.width, "height": attachment.height}


def source_to_json(source):
    return {"title": source.title or source.url, "url": source.url, "tech": source.tech, "version": source.version, "doc_type": source.doc_type}


@require_http_methods(["GET"])
def conversation_list(request):
    user_id = current_user_id(request)
    if user_id is None:
        return error(LOGIN_REQUIRED, 401)
    query = " ".join(request.GET.get("q", "").split())
    if len(query) > QUERY_MAX_CHARS:
        return error(f"검색어는 {QUERY_MAX_CHARS}자 이하로 입력해 주세요.", 400)
    try:
        with db_session() as session:
            found = search_conversations(session, user_id, query) if query else list_conversations(session, user_id)
            items = [{"id": c.id, "title": c.title, "updated_at": iso(c.updated_at)} for c in found]
    except Exception:
        logger.exception("대화 목록 DB 오류")
        return error(DB_PROBLEM, 503)
    return JsonResponse({"conversations": items})


@require_http_methods(["GET", "DELETE", "PATCH"])
def conversation_detail(request, conversation_id):
    user_id = current_user_id(request)
    if user_id is None:
        return error(LOGIN_REQUIRED, 401)
    if request.method == "PATCH":
        try:
            body = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return error("요청 형식이 올바르지 않습니다.", 400)
        title = body.get("title") if isinstance(body, dict) else None
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
            return error("제목은 공백을 제외하고 1~100자로 입력해 주세요.", 400)
        try:
            with db_session() as session:
                conv = rename_conversation(session, conversation_id, user_id, title)
                payload = {"id": conv.id, "title": conv.title}
            return JsonResponse(payload)
        except PermissionError:
            return error(NOT_FOUND, 404)
        except Exception:
            logger.exception("대화 제목 변경 DB 오류")
            return error("제목을 저장하지 못했습니다. 다시 시도해 주세요.", 503)
    try:
        with db_session() as session:
            if request.method == "DELETE":
                if not delete_conversation(session, conversation_id, user_id):
                    return error(NOT_FOUND, 404)
                return JsonResponse({})
            messages = list_messages(session, conversation_id, user_id)  # 남의 대화면 PermissionError
            title = messages[0].conversation.title if messages else "새 대화"
            payload = {
                "id": conversation_id,
                "title": title,
                "messages": [
                    {"role": m.role, "content": m.content, "sources": [source_to_json(s) for s in m.sources], "images": [image_to_json(a) for a in m.attachments], "created_at": iso(m.created_at)}
                    for m in messages
                ],
            }
    except PermissionError:
        return error(NOT_FOUND, 404)
    except Exception:
        logger.exception("대화 DB 오류")
        return error(DB_PROBLEM, 503)
    return JsonResponse(payload)


@require_GET
def attachment(request, attachment_id):
    """저장된 이미지를 돌려준다. 본인 것만 볼 수 있고, 형식은 저장할 때 파일 내용으로 확인한 png/jpeg/webp뿐이다."""
    user_id = current_user_id(request)
    if user_id is None:
        return error(LOGIN_REQUIRED, 401)
    full = request.GET.get("size") == "full"
    try:
        with db_session() as session:
            found = get_image(session, attachment_id, user_id)  # 남의 것이면 None
            if found is None:
                return error(NOT_FOUND, 404)
            data, content_type = (image_bytes(found), found.mime_type) if full else (thumbnail_bytes(found), "image/jpeg")
    except FileNotFoundError:  # 저장 폴더가 지워졌거나 다른 서버일 때
        return error(NOT_FOUND, 404)
    except Exception:
        logger.exception("이미지 DB 오류")
        return error(DB_PROBLEM, 503)
    if not data:
        return error(NOT_FOUND, 404)
    response = HttpResponse(data, content_type=content_type)
    response["Cache-Control"] = "private, max-age=3600"  # 로그인한 본인 브라우저에만 저장한다
    response["X-Content-Type-Options"] = "nosniff"
    return response
