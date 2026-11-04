"""대화 목록, 불러오기, 삭제. 실제 DB는 건드리지 않고 3차 조회 함수를 가짜로 바꿔서 시험한다.

    uv run python back/manage.py test chat
"""

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import TestCase

LIST_URL = "/api/conversations/"
DETAIL_URL = "/api/conversations/12/"
USER_ID = 7


@contextmanager
def fake_db_session():
    yield object()


def log_in(client, user_id=USER_ID):
    """테스트용으로 로그인한 상태를 만든다. 서명된 쿠키 방식이라 저장한 쿠키 값을 브라우저(client)에 직접 심어 준다."""
    session = client.session
    session["user_id"] = user_id
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key


def source(url="https://docs.example.com/a", title="문서"):
    return SimpleNamespace(url=url, title=title, tech="langgraph", version="1.x", doc_type="docs")


def message(role, content, sources=(), title="체크포인터 질문", images=()):
    return SimpleNamespace(
        role=role, content=content, sources=list(sources), attachments=list(images), created_at=datetime(2026, 11, 3, 5, 30, 0),
        conversation=SimpleNamespace(title=title),
    )


class ConversationTestCase(TestCase):
    def use(self, **targets):
        patches = [mock.patch("chat.conversations.db_session", fake_db_session)]
        patches += [mock.patch(f"chat.conversations.{name}", value) for name, value in targets.items()]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)


class LoginRequiredTests(ConversationTestCase):
    def test_all_endpoints_require_login_and_skip_db(self):
        listing, messages, delete = mock.Mock(), mock.Mock(), mock.Mock()
        self.use(list_conversations=listing, list_messages=messages, delete_conversation=delete)
        self.assertEqual(self.client.get(LIST_URL).status_code, 401)
        self.assertEqual(self.client.get(DETAIL_URL).status_code, 401)
        self.assertEqual(self.client.delete(DETAIL_URL).status_code, 401)
        for fake in (listing, messages, delete):
            fake.assert_not_called()

    def test_methods_are_limited(self):
        log_in(self.client)
        self.assertEqual(self.client.post(LIST_URL).status_code, 405)
        self.assertEqual(self.client.post(DETAIL_URL).status_code, 405)


class ListTests(ConversationTestCase):
    def test_lists_only_current_users_conversations(self):
        log_in(self.client)
        rows = [SimpleNamespace(id=12, title="질문", updated_at=datetime(2026, 11, 3, 5, 30, 0))]
        listing = mock.Mock(return_value=rows)
        self.use(list_conversations=listing)
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conversations"], [{"id": 12, "title": "질문", "updated_at": "2026-11-03T05:30:00Z"}])
        self.assertEqual(listing.call_args.args[1], USER_ID)  # 세션의 사용자 번호로만 조회한다

    def test_db_failure_is_503_without_details(self):
        log_in(self.client)
        self.use(list_conversations=mock.Mock(side_effect=RuntimeError("password=xyz")))
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("xyz", response.content.decode())


class DetailTests(ConversationTestCase):
    def setUp(self):
        log_in(self.client)

    def test_returns_messages_in_order_with_sources(self):
        rows = [message("user", "질문"), message("assistant", "### 답변", sources=[source(), source("https://docs.example.com/b", "문서2")])]
        self.use(list_messages=mock.Mock(return_value=rows))
        data = self.client.get(DETAIL_URL).json()
        self.assertEqual(data["id"], 12)
        self.assertEqual(data["title"], "체크포인터 질문")
        self.assertEqual([m["role"] for m in data["messages"]], ["user", "assistant"])
        self.assertEqual(data["messages"][1]["content"], "### 답변")
        self.assertEqual([s["url"] for s in data["messages"][1]["sources"]], ["https://docs.example.com/a", "https://docs.example.com/b"])
        self.assertEqual(data["messages"][0]["created_at"], "2026-11-03T05:30:00Z")

    def test_other_users_conversation_is_404(self):
        self.use(list_messages=mock.Mock(side_effect=PermissionError("남의 대화")))
        response = self.client.get(DETAIL_URL)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("남의", response.content.decode())

    def test_db_failure_is_503(self):
        self.use(list_messages=mock.Mock(side_effect=RuntimeError("boom")))
        self.assertEqual(self.client.get(DETAIL_URL).status_code, 503)


class DeleteTests(ConversationTestCase):
    def setUp(self):
        log_in(self.client)

    def test_delete_own_conversation(self):
        delete = mock.Mock(return_value=True)
        self.use(delete_conversation=delete)
        response = self.client.delete(DETAIL_URL, HTTP_X_CSRFTOKEN="x")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(delete.call_args.args[1:], (12, USER_ID))

    def test_delete_missing_or_others_is_404(self):
        self.use(delete_conversation=mock.Mock(return_value=False))
        self.assertEqual(self.client.delete(DETAIL_URL).status_code, 404)

    def test_delete_requires_csrf_token(self):
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        log_in(strict)
        self.use(delete_conversation=mock.Mock(return_value=True))
        self.assertEqual(strict.delete(DETAIL_URL).status_code, 403)
