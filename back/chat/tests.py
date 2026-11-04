"""질문 창구(views), 설정, 웜업 규칙을 확인한다. 실제 AI, 검색, DB는 부르지 않고 코어(run_db_chat)를 가짜로 바꿔서 시험한다.

    uv run python back/manage.py test chat
"""

import json
from unittest import mock

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from chat.apps import should_warm_up

URL = "/api/chat/"
USER_ID = 7


def post(client, payload, **extra):
    return client.post(URL, data=json.dumps(payload), content_type="application/json", **extra)


def log_in(client, user_id=USER_ID):
    """테스트용으로 로그인한 상태를 만든다. 서명된 쿠키 방식이라 저장한 쿠키 값을 브라우저(client)에 직접 심어 준다."""
    session = client.session
    session["user_id"] = user_id
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key


def read_events(response):
    """스트리밍 응답을 (이벤트 이름, 데이터) 목록으로 읽는다."""
    body = b"".join(response.streaming_content).decode("utf-8")
    events = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name, data = None, None
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((name, data))
    return events


def fake_run_db_chat(result, tokens=("안", "녕"), stages=("RAG · 검색",)):
    def run(question, *, user_id, conversation_id=None, on_token=None, on_stage=None, **kwargs):
        for stage in stages:
            on_stage(stage)
        for token in tokens:
            on_token(token)
        return result

    return run


SUCCESS = {
    "status": "success",
    "answer": "안녕",
    "sources": [{"title": "문서", "url": "https://docs.example.com/a"}],
    "error": None,
    "conversation_id": 12,
}


class PageAndHealthTests(SimpleTestCase):
    def test_health(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_index_renders_front_template_and_sets_csrf_cookie(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="chat-form"')
        self.assertContains(response, "/static/js/chat.js")  # 프론트 파일(front/static)을 가리킨다
        self.assertIn("csrftoken", response.cookies)


class ChatStreamTests(TestCase):
    def setUp(self):
        log_in(self.client)

    def test_streams_stage_tokens_sources_then_done_with_conversation_id(self):
        with mock.patch("chat.views.run_db_chat", fake_run_db_chat(SUCCESS)):
            response = post(self.client, {"question": "질문"})
            events = read_events(response)
        self.assertEqual(response["Content-Type"], "text/event-stream; charset=utf-8")
        self.assertEqual(response["X-Accel-Buffering"], "no")
        self.assertEqual([name for name, _ in events], ["stage", "token", "token", "sources", "done"])
        self.assertEqual(events[1][1] + events[2][1], "안녕")
        self.assertEqual(events[3][1][0]["url"], "https://docs.example.com/a")
        self.assertEqual(events[4][1], {"answer": "안녕", "conversation_id": 12})

    def test_user_id_comes_from_session_and_question_is_trimmed(self):
        seen = {}

        def run(question, *, user_id, conversation_id=None, **kwargs):
            seen.update(question=question, user_id=user_id, conversation_id=conversation_id)
            return SUCCESS

        with mock.patch("chat.views.run_db_chat", run):
            # 요청에 user_id를 넣어도 쓰지 않는다 (세션의 사용자만 쓴다)
            read_events(post(self.client, {"question": " 새 질문 ", "user_id": 999, "conversation_id": 12}))
        self.assertEqual(seen, {"question": "새 질문", "user_id": USER_ID, "conversation_id": 12})

    def test_new_conversation_has_no_conversation_id(self):
        seen = {}

        def run(question, *, user_id, conversation_id=None, **kwargs):
            seen["conversation_id"] = conversation_id
            return SUCCESS

        with mock.patch("chat.views.run_db_chat", run):
            read_events(post(self.client, {"question": "질문"}))
        self.assertIsNone(seen["conversation_id"])

    def test_core_error_result_becomes_error_event_keeping_conversation_id(self):
        result = {"status": "error", "answer": "", "sources": [], "error": {"code": "GRAPH_ERROR", "message": "실패 안내"}, "conversation_id": 12}
        with mock.patch("chat.views.run_db_chat", fake_run_db_chat(result, tokens=())):
            events = read_events(post(self.client, {"question": "질문"}))
        self.assertEqual(events[-1], ("error", {"message": "실패 안내", "conversation_id": 12}))
        self.assertNotIn("done", [name for name, _ in events])

    def test_core_exception_becomes_generic_error_without_details(self):
        with mock.patch("chat.views.run_db_chat", side_effect=RuntimeError("secret-api-key-123")):
            events = read_events(post(self.client, {"question": "질문"}))
        self.assertEqual(events[0][0], "error")
        self.assertNotIn("secret-api-key-123", json.dumps(events, ensure_ascii=False))


class LoginRequiredTests(TestCase):
    def test_chat_requires_login_and_does_not_call_core(self):
        run = mock.Mock()
        with mock.patch("chat.views.run_db_chat", run):
            response = post(self.client, {"question": "질문"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "로그인이 필요합니다.")
        run.assert_not_called()

    def test_logged_out_session_cannot_chat(self):
        log_in(self.client)
        self.client.post("/api/auth/logout/")
        with mock.patch("chat.views.run_db_chat", mock.Mock()) as run:
            self.assertEqual(post(self.client, {"question": "질문"}).status_code, 401)
        run.assert_not_called()

    def test_non_integer_user_id_in_session_is_treated_as_logged_out(self):
        log_in(self.client, user_id="7")
        self.assertEqual(post(self.client, {"question": "질문"}).status_code, 401)


class RequestValidationTests(TestCase):
    def setUp(self):
        log_in(self.client)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(URL).status_code, 405)

    def test_invalid_json_is_400(self):
        response = self.client.post(URL, data="not json", content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_empty_or_missing_question_is_400(self):
        for payload in ({}, {"question": ""}, {"question": "   "}, {"question": 123}, ["질문"]):
            self.assertEqual(post(self.client, payload).status_code, 400, payload)

    def test_too_long_question_is_400(self):
        with self.settings(CHAT_QUESTION_MAX_CHARS=10):
            self.assertEqual(post(self.client, {"question": "가" * 11}).status_code, 400)

    def test_invalid_conversation_id_is_400(self):
        for value in ("12", 0, -1, 1.5, True, [1]):
            self.assertEqual(post(self.client, {"question": "질문", "conversation_id": value}).status_code, 400, value)

    def test_csrf_is_enforced(self):
        strict = Client(enforce_csrf_checks=True)
        log_in(strict)
        self.assertEqual(post(strict, {"question": "질문"}).status_code, 403)


class WarmUpRuleTests(SimpleTestCase):
    def test_server_commands_warm_up(self):
        self.assertTrue(should_warm_up(["gunicorn"], {}))
        self.assertTrue(should_warm_up(["manage.py", "runserver", "--noreload"], {}))
        self.assertTrue(should_warm_up(["manage.py", "runserver"], {"RUN_MAIN": "true"}))

    def test_runserver_parent_process_skips_warm_up(self):
        self.assertFalse(should_warm_up(["manage.py", "runserver"], {}))

    def test_management_commands_skip_warm_up(self):
        for command in ("migrate", "test", "check", "collectstatic", "shell"):
            self.assertFalse(should_warm_up(["manage.py", command], {}), command)

    def test_environment_can_switch_it_off(self):
        self.assertFalse(should_warm_up(["gunicorn"], {"CODECLUE_NO_WARMUP": "1"}))


class UrlTests(SimpleTestCase):
    def test_named_urls(self):
        self.assertEqual(reverse("chat:chat_stream"), URL)
        self.assertEqual(reverse("chat:index"), "/")


class RerankerModelCheckTests(SimpleTestCase):
    """재정렬 모델 폴더가 없는 PC에서, 서버를 켤 때 이유와 해결 방법을 알려 주는지 확인한다."""

    def problem(self, *, ready, backend="auto", has_sentence_transformers=False):
        with mock.patch("src.rag.rerank_onnx.onnx_model_ready", return_value=ready),              mock.patch("src.const.config.RERANK_BACKEND", backend),              mock.patch("chat.checks.find_spec", return_value=object() if has_sentence_transformers else None):
            from chat.checks import reranker_problem

            return reranker_problem()

    def test_no_problem_when_model_folder_is_ready(self):
        self.assertIsNone(self.problem(ready=True))

    def test_missing_model_folder_is_reported_with_the_path(self):
        message = self.problem(ready=False)
        self.assertIn("재정렬 모델 폴더가 없어서", message)
        self.assertIn("model_int8.onnx", message)

    def test_no_report_when_original_backend_is_chosen_or_available(self):
        self.assertIsNone(self.problem(ready=False, backend="torch"))
        self.assertIsNone(self.problem(ready=False, has_sentence_transformers=True))

    def test_explicit_onnx_backend_is_reported_even_if_original_is_available(self):
        self.assertIsNotNone(self.problem(ready=False, backend="onnx", has_sentence_transformers=True))

    def test_django_check_returns_a_warning_with_hint(self):
        from chat.checks import RERANKER_HINT, check_reranker_model

        with mock.patch("chat.checks.reranker_problem", return_value="모델 없음"):
            warnings = check_reranker_model(None)
        self.assertEqual([w.id for w in warnings], ["chat.W001"])
        self.assertEqual(warnings[0].hint, RERANKER_HINT)
        with mock.patch("chat.checks.reranker_problem", return_value=None):
            self.assertEqual(check_reranker_model(None), [])
