"""이미지 업로드(multipart)와 저장된 이미지 보여 주기. 실제 AI, DB, 파일 저장은 쓰지 않고 가짜로 바꿔서 시험한다.

    uv run python back/manage.py test chat
"""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from chat.test_conversations import log_in, message
from chat.tests import SUCCESS, fake_run_db_chat, read_events

CHAT = "/api/chat/"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"


def png(name="a.png", content=PNG, content_type="image/png"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def upload(client, data):
    """multipart/form-data로 보낸다 (장고 테스트 클라이언트의 기본 방식)."""
    return client.post(CHAT, data=data)


class UploadTests(TestCase):
    def setUp(self):
        log_in(self.client)

    def run_chat(self, data, run=None):
        seen = {}

        def default_run(question, *, user_id, conversation_id=None, images=None, **kwargs):
            seen.update(question=question, conversation_id=conversation_id, images=images)
            return SUCCESS

        with mock.patch("chat.views.run_db_chat", run or default_run):
            response = upload(self.client, data)
            if response.status_code == 200:
                read_events(response)
        return response, seen

    def test_images_are_passed_to_core_as_bytes(self):
        response, seen = self.run_chat({"question": " 이 오류 뭐야? ", "images": [png("a.png"), png("b.png", PNG + b"2")]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["question"], "이 오류 뭐야?")
        self.assertEqual(seen["images"], [PNG, PNG + b"2"])

    def test_image_only_question_is_allowed(self):
        response, seen = self.run_chat({"question": "", "images": png()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["question"], "")
        self.assertEqual(seen["images"], [PNG])

    def test_multipart_without_images_works_like_text_question(self):
        response, seen = self.run_chat({"question": "질문"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(seen["images"])

    def test_empty_question_without_images_is_400(self):
        self.assertEqual(self.run_chat({"question": "  "})[0].status_code, 400)

    def test_conversation_id_from_form_is_converted_to_int(self):
        response, seen = self.run_chat({"question": "질문", "conversation_id": "12"})
        self.assertEqual(seen["conversation_id"], 12)
        response, seen = self.run_chat({"question": "질문", "conversation_id": ""})
        self.assertIsNone(seen["conversation_id"])

    def test_invalid_conversation_id_from_form_is_400(self):
        for value in ("abc", "0", "-1", "1.5", "１２"):
            self.assertEqual(self.run_chat({"question": "질문", "conversation_id": value})[0].status_code, 400, value)

    def test_json_still_rejects_string_conversation_id(self):
        response = self.client.post(CHAT, data=json.dumps({"question": "질문", "conversation_id": "12"}), content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_too_many_images_is_400_and_core_is_not_called(self):
        run = mock.Mock()
        response, _ = self.run_chat({"question": "질문", "images": [png(f"{i}.png") for i in range(4)]}, run=run)
        self.assertEqual(response.status_code, 400)
        self.assertIn("3장", response.json()["error"])
        run.assert_not_called()

    def test_too_large_image_is_400(self):
        with self.settings(CHAT_IMAGE_UPLOAD_MAX_BYTES=10):
            response, _ = self.run_chat({"question": "질문", "images": png()})
        self.assertEqual(response.status_code, 400)
        self.assertIn("너무 큽니다", response.json()["error"])

    def test_core_image_error_is_shown_to_user_as_error_event(self):
        result = {"status": "error", "answer": "", "sources": [], "error": {"code": "INVALID_IMAGE", "message": "이미지 1은(는) png, jpeg, webp 형식이 아니에요."}, "conversation_id": None}
        with mock.patch("chat.views.run_db_chat", fake_run_db_chat(result, tokens=())):
            events = read_events(upload(self.client, {"question": "질문", "images": png("x.gif", b"GIF89a", "image/gif")}))
        self.assertEqual(events[-1][0], "error")
        self.assertIn("png, jpeg, webp", events[-1][1]["message"])

    def test_upload_requires_login(self):
        run = mock.Mock()
        with mock.patch("chat.views.run_db_chat", run):
            response = upload(Client(), {"question": "질문", "images": png()})
        self.assertEqual(response.status_code, 401)
        run.assert_not_called()

    def test_upload_requires_csrf_token(self):
        strict = Client(enforce_csrf_checks=True)
        log_in(strict)
        self.assertEqual(upload(strict, {"question": "질문", "images": png()}).status_code, 403)


@contextmanager
def fake_db_session():
    yield object()


def attachment(att_id=5, mime="image/png"):
    return SimpleNamespace(id=att_id, mime_type=mime, width=640, height=480)


class AttachmentTests(TestCase):
    URL = "/api/attachments/5/"

    def use(self, **targets):
        patches = [mock.patch("chat.conversations.db_session", fake_db_session)]
        patches += [mock.patch(f"chat.conversations.{n}", v) for n, v in targets.items()]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_requires_login(self):
        get = mock.Mock()
        self.use(get_image=get)
        self.assertEqual(self.client.get(self.URL).status_code, 401)
        get.assert_not_called()

    def test_thumbnail_is_default_and_is_served_safely(self):
        log_in(self.client)
        get = mock.Mock(return_value=attachment())
        self.use(get_image=get, thumbnail_bytes=mock.Mock(return_value=b"jpegbytes"), image_bytes=mock.Mock(return_value=b"original"))
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"jpegbytes")
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("private", response["Cache-Control"])
        self.assertEqual(get.call_args.args[1:], (5, 7))  # 세션의 사용자 번호로만 조회한다

    def test_full_size_returns_original_with_stored_mime(self):
        log_in(self.client)
        self.use(get_image=mock.Mock(return_value=attachment(mime="image/webp")), thumbnail_bytes=mock.Mock(), image_bytes=mock.Mock(return_value=b"original"))
        response = self.client.get(self.URL + "?size=full")
        self.assertEqual(response.content, b"original")
        self.assertEqual(response["Content-Type"], "image/webp")

    def test_missing_or_others_image_is_404(self):
        log_in(self.client)
        self.use(get_image=mock.Mock(return_value=None))
        self.assertEqual(self.client.get(self.URL).status_code, 404)

    def test_missing_file_or_thumbnail_is_404(self):
        log_in(self.client)
        self.use(get_image=mock.Mock(return_value=attachment()), thumbnail_bytes=mock.Mock(return_value=None), image_bytes=mock.Mock(side_effect=FileNotFoundError))
        self.assertEqual(self.client.get(self.URL).status_code, 404)
        self.assertEqual(self.client.get(self.URL + "?size=full").status_code, 404)

    def test_db_failure_is_503_without_details(self):
        log_in(self.client)
        self.use(get_image=mock.Mock(side_effect=RuntimeError("password=xyz")))
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("xyz", response.content.decode())

    def test_only_get_is_allowed(self):
        log_in(self.client)
        self.assertEqual(self.client.post(self.URL).status_code, 405)

    def test_conversation_detail_lists_images_of_a_message(self):
        log_in(self.client)
        rows = [message("user", "사진 질문", images=[attachment(5), attachment(6)]), message("assistant", "답")]
        self.use(list_messages=mock.Mock(return_value=rows))
        data = self.client.get("/api/conversations/12/").json()
        self.assertEqual([i["id"] for i in data["messages"][0]["images"]], [5, 6])
        self.assertEqual(data["messages"][0]["images"][0], {"id": 5, "width": 640, "height": 480})
        self.assertEqual(data["messages"][1]["images"], [])
