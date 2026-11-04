"""대화 제목 검색과 제목 변경. 검색·변경 쿼리는 실제 SQL(메모리 SQLite)로, 화면 API는 쿼리 함수를 가짜로 바꿔서 시험한다.

    uv run python back/manage.py test chat
"""

import json
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from django.test import Client, SimpleTestCase, TestCase
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from chat import queries
from chat.test_conversations import log_in
from src.db import Base, Conversation, Message, User

OLD = datetime(2026, 1, 1, 9, 0, 0)


def memory_session():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine)


def add_user(session, name):
    user = User(username=name, password_hash="x")
    session.add(user)
    session.flush()
    return user


def add_conversation(session, user, title, messages=(), updated_at=OLD):
    conversation = Conversation(user_id=user.id, title=title, updated_at=updated_at)
    session.add(conversation)
    session.flush()
    for role, content in messages:
        session.add(Message(conversation_id=conversation.id, role=role, content=content))
    session.flush()
    return conversation


class SearchQueryTests(SimpleTestCase):
    """대화 제목만 검색한다 (대화 내용은 검색하지 않는다)."""

    def setUp(self):
        self.session = memory_session()
        self.addCleanup(self.session.close)
        self.alice = add_user(self.session, "alice01")
        self.bob = add_user(self.session, "bob01")

    def titles(self, query, user=None):
        return [c.title for c in queries.search_conversations(self.session, (user or self.alice).id, query)]

    def test_finds_by_title_ignoring_case(self):
        add_conversation(self.session, self.alice, "LangGraph checkpointer 질문")
        add_conversation(self.session, self.alice, "MCP 서버 연결 오류")
        self.assertEqual(self.titles("mcp"), ["MCP 서버 연결 오류"])
        self.assertEqual(self.titles("CHECKPOINTER"), ["LangGraph checkpointer 질문"])

    def test_does_not_search_message_content(self):
        add_conversation(self.session, self.alice, "제목에는 없음", [("user", "질문입니다"), ("assistant", "InMemorySaver는 메모리에 상태를 저장합니다.")])
        self.assertEqual(self.titles("메모리에"), [])
        self.assertEqual(self.titles("InMemorySaver"), [])

    def test_extra_spaces_in_query_are_normalized(self):
        add_conversation(self.session, self.alice, "MCP 서버 연결 오류")
        self.assertEqual(self.titles("  mcp    서버  "), ["MCP 서버 연결 오류"])

    def test_only_my_conversations_are_searched(self):
        add_conversation(self.session, self.alice, "내 비밀 질문")
        add_conversation(self.session, self.bob, "남의 비밀 질문")
        self.assertEqual(self.titles("비밀"), ["내 비밀 질문"])
        self.assertEqual(self.titles("비밀", self.bob), ["남의 비밀 질문"])

    def test_percent_and_underscore_are_literal(self):
        add_conversation(self.session, self.alice, "할인율 100% 질문")
        add_conversation(self.session, self.alice, "snake_case 질문")
        add_conversation(self.session, self.alice, "100 퍼센트")
        add_conversation(self.session, self.alice, "snakeXcase")
        self.assertEqual(self.titles("100%"), ["할인율 100% 질문"])  # %가 모든 글자로 취급되지 않는다
        self.assertEqual(self.titles("snake_case"), ["snake_case 질문"])  # _가 한 글자로 취급되지 않는다
        self.assertEqual(self.titles("%"), ["할인율 100% 질문"])

    def test_backslash_is_literal(self):
        add_conversation(self.session, self.alice, r"경로 C:\temp 오류")
        self.assertEqual(self.titles("\\temp"), [r"경로 C:\temp 오류"])

    def test_most_recently_updated_first(self):
        add_conversation(self.session, self.alice, "오류 A", updated_at=datetime(2026, 1, 1))
        add_conversation(self.session, self.alice, "오류 B", updated_at=datetime(2026, 3, 1))
        add_conversation(self.session, self.alice, "오류 C", updated_at=datetime(2026, 2, 1))
        self.assertEqual(self.titles("오류"), ["오류 B", "오류 C", "오류 A"])

    def test_result_count_is_limited(self):
        for number in range(queries.SEARCH_LIMIT + 5):
            add_conversation(self.session, self.alice, f"오류 {number}")
        self.assertEqual(len(self.titles("오류")), queries.SEARCH_LIMIT)

    def test_no_match_returns_empty(self):
        add_conversation(self.session, self.alice, "질문")
        self.assertEqual(self.titles("없는말"), [])


class RenameQueryTests(SimpleTestCase):
    def setUp(self):
        self.session = memory_session()
        self.addCleanup(self.session.close)
        self.alice = add_user(self.session, "alice01")
        self.bob = add_user(self.session, "bob01")
        self.conversation = add_conversation(self.session, self.alice, "원래 제목")

    def rename(self, title, user=None, conversation_id=None):
        return queries.rename_conversation(self.session, (user or self.alice).id, conversation_id or self.conversation.id, title)

    def test_rename_changes_title(self):
        self.assertEqual(self.rename("  새   제목 ").title, "새 제목")

    def test_rename_keeps_updated_at_so_list_order_does_not_change(self):
        self.rename("새 제목")
        self.session.expire_all()
        self.assertEqual(self.session.get(Conversation, self.conversation.id).updated_at, OLD)

    def test_cannot_rename_others_conversation(self):
        self.assertIsNone(self.rename("해킹", user=self.bob))
        self.session.expire_all()
        self.assertEqual(self.session.get(Conversation, self.conversation.id).title, "원래 제목")

    def test_missing_conversation_returns_none(self):
        self.assertIsNone(self.rename("제목", conversation_id=999999))

    def test_invalid_titles_are_rejected_before_touching_db(self):
        for bad in ("", "   ", "\n\t", None, 123, ["a"]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.rename(bad)
        with self.assertRaises(ValueError):
            self.rename("가" * (queries.TITLE_MAX_CHARS + 1))

    def test_title_length_boundary(self):
        self.assertEqual(len(self.rename("가" * queries.TITLE_MAX_CHARS).title), queries.TITLE_MAX_CHARS)

    def test_control_characters_and_newlines_become_spaces(self):
        self.assertEqual(self.rename("줄1\n줄2\x00끝").title, "줄1 줄2 끝")

    def test_secrets_in_title_are_masked_like_messages(self):
        title = self.rename("키 sk-proj-abcdefghijklmnopqrstuvwxyz0123456789ABCD 오류").title
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", title)
        self.assertIn("MASKED", title)


@contextmanager
def fake_db_session():
    yield object()


def conv(conv_id=12, title="제목", updated=datetime(2026, 11, 4, 1, 2, 3)):
    return SimpleNamespace(id=conv_id, title=title, updated_at=updated)


class SearchApiTests(TestCase):
    URL = "/api/conversations/"

    def use(self, **targets):
        patches = [mock.patch("chat.conversations.db_session", fake_db_session)] + [mock.patch(f"chat.conversations.{n}", v) for n, v in targets.items()]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def setUp(self):
        log_in(self.client)

    def test_search_returns_same_shape_as_list_without_snippet(self):
        search = mock.Mock(return_value=[conv(1, "MCP 오류"), conv(2, "MCP 연결")])
        self.use(search_conversations=search)
        data = self.client.get(self.URL, {"q": "  mcp   "}).json()["conversations"]
        self.assertEqual(data[0], {"id": 1, "title": "MCP 오류", "updated_at": "2026-11-04T01:02:03Z"})
        self.assertEqual([set(item) for item in data], [{"id", "title", "updated_at"}] * 2)  # 내용 검색이 없으므로 snippet이 없다
        self.assertEqual(search.call_args.args[1:], (7, "mcp"))  # 세션의 사용자 번호, 공백을 정리한 검색어

    def test_empty_query_returns_normal_list_without_search(self):
        search = mock.Mock()
        self.use(search_conversations=search, list_conversations=mock.Mock(return_value=[conv()]))
        for q in ("", "   "):
            self.assertEqual(len(self.client.get(self.URL, {"q": q}).json()["conversations"]), 1)
        search.assert_not_called()

    def test_too_long_query_is_400(self):
        self.use(search_conversations=mock.Mock())
        response = self.client.get(self.URL, {"q": "가" * (queries.QUERY_MAX_CHARS + 1)})
        self.assertEqual(response.status_code, 400)
        self.assertIn("100자", response.json()["error"])

    def test_search_requires_login(self):
        self.assertEqual(Client().get(self.URL, {"q": "a"}).status_code, 401)

    def test_search_db_failure_is_503_without_details(self):
        self.use(search_conversations=mock.Mock(side_effect=RuntimeError("password=xyz")))
        response = self.client.get(self.URL, {"q": "a"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("xyz", response.content.decode())


class RenameApiTests(TestCase):
    URL = "/api/conversations/12/"

    def use(self, **targets):
        patches = [mock.patch("chat.conversations.db_session", fake_db_session)] + [mock.patch(f"chat.conversations.{n}", v) for n, v in targets.items()]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def patch(self, payload, client=None):
        return (client or self.client).patch(self.URL, data=json.dumps(payload), content_type="application/json")

    def setUp(self):
        log_in(self.client)

    def test_rename_success(self):
        rename = mock.Mock(return_value=conv(12, "새 제목"))
        self.use(rename_conversation=rename)
        response = self.patch({"title": "새 제목"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": 12, "title": "새 제목", "updated_at": "2026-11-04T01:02:03Z"})
        self.assertEqual(rename.call_args.args[1:], (7, 12, "새 제목"))  # 세션의 사용자 번호, 주소의 대화 번호

    def test_invalid_title_message_is_400(self):
        self.use(rename_conversation=mock.Mock(side_effect=ValueError("제목을 입력해 주세요.")))
        response = self.patch({"title": " "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "제목을 입력해 주세요.")

    def test_bad_body_is_400_and_does_not_touch_db(self):
        rename = mock.Mock()
        self.use(rename_conversation=rename)
        self.assertEqual(self.client.patch(self.URL, data="not json", content_type="application/json").status_code, 400)
        rename.assert_not_called()

    def test_missing_title_field_is_400(self):
        self.use(rename_conversation=mock.Mock(side_effect=ValueError("제목을 입력해 주세요.")))
        self.assertEqual(self.patch({}).status_code, 400)
        self.assertEqual(self.patch(["제목"]).status_code, 400)

    def test_other_or_missing_conversation_is_404(self):
        self.use(rename_conversation=mock.Mock(return_value=None))
        self.assertEqual(self.patch({"title": "제목"}).status_code, 404)

    def test_rename_requires_login(self):
        rename = mock.Mock()
        self.use(rename_conversation=rename)
        self.assertEqual(self.patch({"title": "제목"}, client=Client()).status_code, 401)
        rename.assert_not_called()

    def test_rename_requires_csrf_token(self):
        strict = Client(enforce_csrf_checks=True)
        log_in(strict)
        self.use(rename_conversation=mock.Mock(return_value=conv()))
        self.assertEqual(self.patch({"title": "제목"}, client=strict).status_code, 403)

    def test_db_failure_is_503_without_details(self):
        self.use(rename_conversation=mock.Mock(side_effect=RuntimeError("password=xyz")))
        response = self.patch({"title": "제목"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("xyz", response.content.decode())

    def test_other_methods_are_still_rejected(self):
        self.assertEqual(self.client.post(self.URL).status_code, 405)
        self.assertEqual(self.client.put(self.URL).status_code, 405)
