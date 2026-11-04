"""
내 대화 목록, 대화 불러오기, 대화 삭제. 모두 로그인한 사용자 본인의 대화만 다룬다 (소유자 확인은 3차 DB 계층이 한다).

GET    /api/conversations/        → {"conversations": [{"id", "title", "updated_at"}, ...]}   최근 수정순
GET    /api/conversations/<id>/   → {"id", "title", "messages": [{"role", "content", "sources", "created_at"}, ...]}   오래된 것부터
DELETE /api/conversations/<id>/   → {}

로그인하지 않았으면 401, 없거나 남의 대화면 404(존재 여부를 알려 주지 않는다), DB 문제면 503. 시각은 UTC ISO 문자열(끝에 Z).
"""

import json
import logging

from src.db.repository import rename_conversation

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from src.db import db_session, delete_conversation, list_conversations, list_messages

from .accounts import current_user_id, error

logger = logging.getLogger(__name__)

LOGIN_REQUIRED = "로그인이 필요합니다."
NOT_FOUND = "대화가 없거나 접근할 수 없습니다."
DB_PROBLEM = "대화를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."


def iso(value):
    """DB의 시각(UTC, 시간대 표시 없음)을 화면이 변환하기 쉬운 문자열로 바꾼다."""
    return value.isoformat() + "Z" if value else None


def source_to_json(source):
    return {"title": source.title or source.url, "url": source.url, "tech": source.tech, "version": source.version, "doc_type": source.doc_type}


@require_http_methods(["GET"])
def conversation_list(request):
    user_id = current_user_id(request)
    if user_id is None:
        return error(LOGIN_REQUIRED, 401)
    try:
        with db_session() as session:
            items = [{"id": c.id, "title": c.title, "updated_at": iso(c.updated_at)} for c in list_conversations(session, user_id)]
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
                    {"role": m.role, "content": m.content, "sources": [source_to_json(s) for s in m.sources], "created_at": iso(m.created_at)}
                    for m in messages
                ],
            }
    except PermissionError:
        return error(NOT_FOUND, 404)
    except Exception:
        logger.exception("대화 DB 오류")
        return error(DB_PROBLEM, 503)
    return JsonResponse(payload)
