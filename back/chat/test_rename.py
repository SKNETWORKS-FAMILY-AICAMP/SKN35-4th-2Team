import json
from contextlib import contextmanager
from unittest import mock

from django.test import TestCase, Client
from sqlalchemy import select

from src.db.engine import make_engine, init_db, make_session_factory, session_scope
from src.db.models import Conversation, Message
from src.db.repository import create_user, create_conversation, add_message, list_conversations


class RenameTests(TestCase):
    def setUp(self):
        self.engine = make_engine("sqlite:///:memory:")
        init_db(self.engine)
        self.addCleanup(self.engine.dispose)
        self.factory = make_session_factory(self.engine)
        with session_scope(self.factory) as session:
            self.owner = create_user(session, "owner", "Testpass123").id
            self.other = create_user(session, "other", "Testpass456").id
            self.id = create_conversation(session, self.owner).id
            add_message(session, self.id, self.owner, "user", "original question")
            create_conversation(session, self.owner, "newer")
            conv = session.get(Conversation, self.id)
            self.before = (conv.created_at, conv.updated_at)
            self.order = [c.id for c in list_conversations(session, self.owner)]
        @contextmanager
        def db():
            with session_scope(self.factory) as session:
                yield session
        patch = mock.patch("chat.conversations.db_session", db)
        patch.start()
        self.addCleanup(patch.stop)
        self.login(self.client, self.owner)
        self.url = f"/api/conversations/{self.id}/"

    def login(self, client, user):
        session = client.session
        session["user_id"] = user
        session.save()

    def rename(self, title, client=None):
        return (client or self.client).patch(self.url, json.dumps({"title": title}), content_type="application/json")

    def test_persistence_order_messages_and_custom_title(self):
        self.assertEqual(self.rename("  새 대화  ").json()["title"], "새 대화")
        with session_scope(self.factory) as session:
            conv = session.get(Conversation, self.id)
            self.assertEqual((conv.created_at, conv.updated_at), self.before)
            self.assertEqual([c.id for c in list_conversations(session, self.owner)], self.order)
            self.assertEqual(list(session.scalars(select(Message.content))), ["original question"])
            add_message(session, self.id, self.owner, "user", "must not replace custom title")
        self.client.logout()
        self.login(self.client, self.owner)
        self.assertEqual(self.client.get(self.url).json()["title"], "새 대화")

    def test_limits_and_plain_text(self):
        for value in ("", "  ", "x" * 101, None, 123):
            with self.subTest(value=value):
                self.assertEqual(self.rename(value).status_code, 400)
        self.assertEqual(self.rename("가" * 100).status_code, 200)
        title = '<script>alert("x")</script>'
        self.assertEqual(self.rename(title).json()["title"], title)

    def test_permissions_and_csrf(self):
        self.login(self.client, self.other)
        self.assertEqual(self.rename("forbidden").status_code, 404)
        self.client.logout()
        self.assertEqual(self.rename("anonymous").status_code, 401)
        strict = Client(enforce_csrf_checks=True)
        self.login(strict, self.owner)
        self.assertEqual(self.rename("no csrf", strict).status_code, 403)
        strict.get("/")
        token = strict.cookies["csrftoken"].value
        response = strict.patch(self.url, json.dumps({"title": "with csrf"}), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)

    def test_failure_keeps_old_title_and_allows_retry(self):
        with mock.patch("chat.conversations.rename_conversation", side_effect=RuntimeError("private details")):
            response = self.rename("failed title")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private details", response.content.decode())
        with session_scope(self.factory) as session:
            self.assertEqual(session.get(Conversation, self.id).title, "original question")
        self.assertEqual(self.rename("retry title").status_code, 200)

    def test_invalid_json(self):
        for body in ("{", "[]", '"text"'):
            self.assertEqual(self.client.patch(self.url, body, content_type="application/json").status_code, 400)
