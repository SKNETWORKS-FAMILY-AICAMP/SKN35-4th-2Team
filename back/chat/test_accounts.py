"""가입, 로그인, 로그아웃, 내 정보. 실제 DB는 건드리지 않고 3차 계정 함수(create_user, authenticate)를 가짜로 바꿔서 시험한다.

    uv run python back/manage.py test chat
"""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

from django.test import Client, SimpleTestCase, TestCase

from chat.accounts import check_signup_rules
from src.db import UsernameTakenError

SIGNUP, LOGIN, LOGOUT, ME = "/api/auth/signup/", "/api/auth/login/", "/api/auth/logout/", "/api/auth/me/"
CREDENTIALS = {"username": "alice01", "password": "password-1234"}


def post(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


@contextmanager
def fake_db_session():
    yield object()


def fake_user(user_id=7, username="alice01", is_admin=False):
    return SimpleNamespace(id=user_id, username=username, is_admin=is_admin)


def patched(**targets):
    """chat.accounts 안의 3차 함수들을 가짜로 바꾼다."""
    patches = [mock.patch("chat.accounts.db_session", fake_db_session)]
    patches += [mock.patch(f"chat.accounts.{name}", value) for name, value in targets.items()]
    return patches


class PatchedTestCase(TestCase):
    def use(self, **targets):
        for patch in patched(**targets):
            patch.start()
            self.addCleanup(patch.stop)


class SignupTests(PatchedTestCase):
    def test_signup_creates_regular_user_and_logs_in(self):
        create = mock.Mock(return_value=fake_user())
        self.use(create_user=create)
        response = post(self.client, SIGNUP, {**CREDENTIALS, "is_admin": True})  # 관리자 요청은 무시된다
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"user": {"username": "alice01", "is_admin": False}})
        self.assertIs(create.call_args.kwargs["is_admin"], False)
        self.assertEqual(self.client.session["user_id"], 7)
        self.assertEqual(self.client.get(ME).json()["user"]["username"], "alice01")

    def test_duplicate_username_is_409(self):
        self.use(create_user=mock.Mock(side_effect=UsernameTakenError("alice01")))
        response = post(self.client, SIGNUP, CREDENTIALS)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("user_id", self.client.session)

    def test_invalid_input_message_is_passed_to_user_as_400(self):
        self.use(create_user=mock.Mock(side_effect=ValueError("비밀번호는 8자 이상이어야 합니다.")))
        response = post(self.client, SIGNUP, {"username": "alice01", "password": "short"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "비밀번호는 8자 이상이어야 합니다.")

    def test_db_failure_is_503_without_details(self):
        self.use(create_user=mock.Mock(side_effect=RuntimeError("host=secret.example password=xyz")))
        response = post(self.client, SIGNUP, CREDENTIALS)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.content.decode())


class LoginTests(PatchedTestCase):
    def test_login_success(self):
        self.use(authenticate=mock.Mock(return_value=fake_user(is_admin=True)))
        response = post(self.client, LOGIN, CREDENTIALS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"], {"username": "alice01", "is_admin": True})
        self.assertEqual(self.client.session["user_id"], 7)

    def test_wrong_credentials_are_401_with_one_message(self):
        self.use(authenticate=mock.Mock(return_value=None))
        response = post(self.client, LOGIN, CREDENTIALS)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "아이디 또는 비밀번호가 올바르지 않습니다. 다시 확인해 주세요.")
        self.assertNotIn("user_id", self.client.session)

    def test_missing_fields_are_400_and_do_not_touch_db(self):
        authenticate = mock.Mock()
        self.use(authenticate=authenticate)
        for payload in ({}, {"username": "alice01"}, {"username": "", "password": "x"}, {"username": 1, "password": "x"}, ["a"]):
            self.assertEqual(post(self.client, LOGIN, payload).status_code, 400, payload)
        authenticate.assert_not_called()

    def test_too_long_password_is_400(self):
        self.use(authenticate=mock.Mock())
        response = post(self.client, LOGIN, {"username": "alice01", "password": "a" * 129})
        self.assertEqual(response.status_code, 400)

    def test_invalid_json_is_400(self):
        self.use(authenticate=mock.Mock())
        response = self.client.post(LOGIN, data="not json", content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_db_failure_is_503_without_details(self):
        self.use(authenticate=mock.Mock(side_effect=RuntimeError("password=xyz")))
        response = post(self.client, LOGIN, CREDENTIALS)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("xyz", response.content.decode())

    def test_login_replaces_the_pre_login_cookie(self):
        """로그인하면 로그인 전에 받은 쿠키는 새 쿠키로 바뀐다 (로그인 전 쿠키로는 로그인 상태가 되지 않는다)."""
        self.use(authenticate=mock.Mock(return_value=fake_user()))
        self.client.get("/api/auth/me/")
        session = self.client.session  # 로그인 전 쿠키
        before = self.client.cookies["sessionid"].value
        post(self.client, LOGIN, CREDENTIALS)
        self.assertNotEqual(before, self.client.cookies["sessionid"].value)
        self.assertEqual(self.client.session["user_id"], 7)


class LogoutAndMeTests(PatchedTestCase):
    def test_me_is_null_when_logged_out(self):
        self.assertEqual(self.client.get(ME).json(), {"user": None})

    def test_logout_clears_login(self):
        self.use(authenticate=mock.Mock(return_value=fake_user()))
        post(self.client, LOGIN, CREDENTIALS)
        self.assertIsNotNone(self.client.get(ME).json()["user"])
        self.assertEqual(self.client.post(LOGOUT).status_code, 200)
        self.assertEqual(self.client.get(ME).json(), {"user": None})

    def test_wrong_methods_are_405(self):
        self.assertEqual(self.client.get(LOGIN).status_code, 405)
        self.assertEqual(self.client.get(SIGNUP).status_code, 405)
        self.assertEqual(self.client.get(LOGOUT).status_code, 405)
        self.assertEqual(self.client.post(ME).status_code, 405)

    def test_csrf_is_enforced_on_auth_posts(self):
        strict = Client(enforce_csrf_checks=True)
        for url in (SIGNUP, LOGIN, LOGOUT):
            self.assertEqual(post(strict, url, CREDENTIALS).status_code, 403, url)

    def test_session_is_marked_to_expire_at_browser_close(self):
        self.use(authenticate=mock.Mock(return_value=fake_user()))
        post(self.client, LOGIN, CREDENTIALS)
        self.assertTrue(self.client.session.get_expire_at_browser_close())


class SignupRuleTests(PatchedTestCase):
    """가입 규칙: 아이디 3~20자, 비밀번호 8자 이상 + 영문과 숫자 모두, 아이디와 비슷한 비밀번호 거부."""

    def rejected(self, username, password):
        create = mock.Mock(return_value=fake_user())
        self.use(create_user=create)
        response = post(self.client, SIGNUP, {"username": username, "password": password})
        self.assertEqual(response.status_code, 400, (username, password))
        create.assert_not_called()  # 규칙에 걸리면 DB까지 가지 않는다
        return response.json()["error"]

    def test_username_length_limits(self):
        self.assertIsNone(check_signup_rules("a" * 20, "Zx9-unrelated"))
        self.assertIsNone(check_signup_rules("abc", "Zx9-unrelated"))
        self.assertIn("3~20자", check_signup_rules("a" * 21, "Zx9-unrelated"))
        self.assertIn("3~20자", check_signup_rules("ab", "Zx9-unrelated"))

    def test_username_allows_only_lowercase_digits_underscore(self):
        for bad in ("Bad Name", "한글아이디", "a-b-c", "a.b.c"):
            self.assertIn("3~20자", check_signup_rules(bad, "Zx9-unrelated"), bad)
        self.assertIsNone(check_signup_rules("  Alice_01  ", "Zx9-unrelated"))  # 앞뒤 공백과 대문자는 코어처럼 정리한다

    def test_password_needs_letters_and_digits(self):
        self.assertIn("영문과 숫자", self.rejected("alice01", "onlyletters"))
        self.assertIn("영문과 숫자", self.rejected("alice01", "1234567890"))
        self.assertIn("영문과 숫자", self.rejected("alice01", "한글비밀번호1234"))  # 영문이 없다
        self.assertIn("8자 이상", self.rejected("alice01", "Ab1"))

    def test_password_too_similar_to_username_is_rejected(self):
        for password in ("alice01", "Alice01!!", "alice0123", "my-alice01-pw", "10ecila-x9", "alice1"):
            message = self.rejected("alice01", password) if len(password) >= 8 else check_signup_rules("alice01", password)
            self.assertIsNotNone(message, password)
        self.assertIn("비슷", self.rejected("alice01", "ALICE01abc9"))

    def test_unrelated_passwords_are_not_rejected(self):
        for username, password in (("alice01", "password-1234"), ("alice01", "Zx9-unrelated"), ("kim_dev", "Rainy7Morning"), ("abc", "Zebra-4-Lamp")):
            self.assertIsNone(check_signup_rules(username, password), (username, password))

    def test_rules_apply_only_to_signup_not_login(self):
        """예전 규칙으로 만든 계정(길이 20자 초과 등)도 로그인은 할 수 있어야 한다."""
        self.use(authenticate=mock.Mock(return_value=fake_user(username="a" * 25)))
        response = post(self.client, LOGIN, {"username": "a" * 25, "password": "simple"})
        self.assertEqual(response.status_code, 200)


class SignedCookieSessionTests(TestCase):
    """Sessions stay signed cookies; Axes/Captcha security state requires Django tables."""

    def run_with(self, **targets):
        patches = [mock.patch("chat.accounts.db_session", fake_db_session)] + [mock.patch(f"chat.accounts.{n}", v) for n, v in targets.items()]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_login_me_logout_keep_signed_cookie_sessions(self):
        self.run_with(authenticate=mock.Mock(return_value=fake_user()))
        self.assertEqual(post(self.client, LOGIN, CREDENTIALS).status_code, 200)
        self.assertEqual(self.client.get(ME).json()["user"]["username"], "alice01")
        self.assertEqual(self.client.post(LOGOUT).status_code, 200)
        self.assertEqual(self.client.get(ME).json(), {"user": None})

    def test_signup_keeps_signed_cookie_session(self):
        self.run_with(create_user=mock.Mock(return_value=fake_user()))
        self.assertEqual(post(self.client, SIGNUP, CREDENTIALS).status_code, 200)
        self.assertEqual(self.client.get(ME).json()["user"]["username"], "alice01")

    def test_session_cookie_cannot_be_forged(self):
        self.client.cookies["sessionid"] = "forged-value"
        self.assertEqual(self.client.get(ME).json(), {"user": None})
