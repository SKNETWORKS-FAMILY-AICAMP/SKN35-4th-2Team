import json
from contextlib import contextmanager
from unittest import mock

from django.conf import settings
from django.test import Client, TestCase
from sqlalchemy import select

from src.db.engine import init_db, make_engine, make_session_factory, session_scope
from src.db.models import Conversation, Message
from src.db.repository import create_user, create_conversation, add_message
from .pins import metadata, conversation_pins, set_conversation_pin


class PinTests(TestCase):
    def setUp(self):
        self.engine = make_engine("sqlite:///:memory:")
        init_db(self.engine)
        metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.factory = make_session_factory(self.engine)
        with session_scope(self.factory) as session:
            self.owner = create_user(session, "owner", "Testpass123").id
            self.other = create_user(session, "other", "Testpass456").id
            conv = create_conversation(session, self.owner, "older")
            self.id = conv.id
            add_message(session, self.id, self.owner, "user", "original text")
            self.before = (conv.title, conv.created_at, conv.updated_at)
            self.newer = create_conversation(session, self.owner, "newer").id
            self.foreign = create_conversation(session, self.other, "private").id
        @contextmanager
        def db():
            with session_scope(self.factory) as session:
                yield session
        patch = mock.patch("chat.conversations.db_session", db)
        patch.start()
        self.addCleanup(patch.stop)
        self.url = f"/api/conversations/{self.id}/pin/"
        self.login(self.client, self.owner)

    def login(self, client, user):
        session = client.session
        session["user_id"] = user
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

    def pin(self, value, client=None, url=None, **kwargs):
        return (client or self.client).patch(url or self.url, json.dumps({"is_pinned": value}), content_type="application/json", **kwargs)

    def listing(self):
        response = self.client.get('/api/conversations/')
        self.assertEqual(response.status_code, 200)
        return response.json()['conversations']

    def test_pin_persists_and_unpin_restores_order_without_changing_chat(self):
        self.assertEqual([c['id'] for c in self.listing()], [self.newer, self.id])
        for _ in range(2):
            self.assertEqual(self.pin(True).status_code, 200)
        self.client.logout()
        self.login(self.client, self.owner)
        rows = self.listing()
        self.assertEqual([c['id'] for c in rows], [self.id, self.newer])
        self.assertTrue(rows[0]['is_pinned'])
        with session_scope(self.factory) as session:
            conv = session.get(Conversation, self.id)
            self.assertEqual((conv.title, conv.created_at, conv.updated_at), self.before)
            self.assertEqual(list(session.scalars(select(Message.content))), ['original text'])
            self.assertEqual(len(session.execute(select(conversation_pins)).all()), 1)
        for _ in range(2):
            self.assertEqual(self.pin(False).status_code, 200)
        self.assertEqual([c['id'] for c in self.listing()], [self.newer, self.id])

    def test_no_ownership_leak_and_requires_login(self):
        self.assertEqual(self.pin(True, url=f'/api/conversations/{self.foreign}/pin/').status_code, 404)
        self.assertEqual(self.pin(True, url='/api/conversations/99999/pin/').status_code, 404)
        self.login(self.client, self.other)
        self.assertEqual(self.pin(True).status_code, 404)
        self.assertEqual([c['id'] for c in self.listing()], [self.foreign])
        self.client.logout()
        self.assertEqual(self.pin(True).status_code, 401)

    def test_boolean_validation_json_and_method(self):
        for value in (None, 0, 1, 'true', [], {}):
            with self.subTest(value=value):
                self.assertEqual(self.pin(value).status_code, 400)
        for body in ('{', '[]', 'null'):
            self.assertEqual(self.client.patch(self.url, body, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_csrf_required_and_valid_token_works(self):
        client = Client(enforce_csrf_checks=True)
        self.login(client, self.owner)
        self.assertEqual(self.pin(True, client).status_code, 403)
        client.get('/')
        token = client.cookies['csrftoken'].value
        self.assertEqual(self.pin(True, client, HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_db_failure_does_not_change_pin_and_can_retry(self):
        with mock.patch('chat.conversations.set_conversation_pin', side_effect=RuntimeError('secret detail')):
            response = self.pin(True)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret detail', response.content.decode())
        self.assertFalse(any(c['is_pinned'] for c in self.listing()))
        self.assertEqual(self.pin(True).status_code, 200)

    def test_delete_cleans_up_pin(self):
        self.pin(True)
        self.assertEqual(self.client.delete(f'/api/conversations/{self.id}/').status_code, 200)
        with session_scope(self.factory) as session:
            self.assertEqual(list(session.execute(select(conversation_pins))), [])
        self.assertEqual([c['id'] for c in self.listing()], [self.newer])

    def test_old_pinned_chat_is_included_beyond_recent_limit(self):
        with session_scope(self.factory) as session:
            for i in range(51):
                create_conversation(session, self.owner, f'new {i}')
        self.pin(True)
        self.assertEqual(self.listing()[0]['id'], self.id)

    def test_web_migration_upgrade_and_downgrade_preserve_conversations(self):
        from pathlib import Path
        from alembic.config import Config
        from alembic import command
        from sqlalchemy import inspect
        metadata.drop_all(self.engine)
        config = Config(str(Path(__file__).with_name('pins_alembic.ini')))
        with self.engine.connect() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
            command.upgrade(config, 'head')
            self.assertIn('conversation_pins', inspect(connection).get_table_names())
            self.assertIsNotNone(connection.execute(select(Conversation.id).where(Conversation.id == self.id)).first())
            command.downgrade(config, 'base')
            self.assertNotIn('conversation_pins', inspect(connection).get_table_names())
            self.assertIsNotNone(connection.execute(select(Conversation.id).where(Conversation.id == self.id)).first())

    def test_missing_pin_table_keeps_existing_history_available(self):
        metadata.drop_all(self.engine)
        rows = self.listing()
        self.assertEqual([row['id'] for row in rows], [self.newer, self.id])
        self.assertTrue(all(row['is_pinned'] is False for row in rows))
        self.assertEqual(self.client.get(f'/api/conversations/{self.id}/').status_code, 200)

    def test_missing_pin_table_only_disables_pinning_and_recovers_after_creation(self):
        metadata.drop_all(self.engine)
        response = self.pin(True)
        self.assertEqual(response.status_code, 503)
        self.assertIn('준비되지', response.json()['error'])
        metadata.create_all(self.engine)
        self.assertEqual(self.pin(True).status_code, 200)
        self.assertTrue(self.listing()[0]['is_pinned'])

    def test_delete_without_pin_table_still_works(self):
        metadata.drop_all(self.engine)
        self.assertEqual(self.client.delete(f'/api/conversations/{self.id}/').status_code, 200)

    def test_search_preserves_filter_and_prioritizes_matching_pins(self):
        with session_scope(self.factory) as session:
            session.get(Conversation, self.id).title = 'MCP older'
            session.get(Conversation, self.newer).title = 'MCP newer'
            irrelevant = create_conversation(session, self.owner, 'unrelated').id
        self.pin(True)
        self.pin(True, url=f'/api/conversations/{irrelevant}/pin/')
        response = self.client.get('/api/conversations/', {'q': 'mcp'})
        self.assertEqual(response.status_code, 200)
        rows = response.json()['conversations']
        self.assertEqual([row['id'] for row in rows], [self.id, self.newer])
        self.assertEqual([row['is_pinned'] for row in rows], [True, False])
        self.assertEqual(self.client.get('/api/conversations/', {'q': 'no match'}).json()['conversations'], [])

    def test_search_works_before_pin_migration(self):
        metadata.drop_all(self.engine)
        response = self.client.get('/api/conversations/', {'q': 'older'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.json()['conversations']], [self.id])
