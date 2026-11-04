"""Axes adapter for CodeClue's SQLAlchemy/JSON login (not Django User auth)."""
import ipaddress
from dataclasses import dataclass
from secrets import compare_digest

from axes.handlers.proxy import AxesProxyHandler
from captcha.fields import CaptchaField
from captcha.helpers import captcha_image_url
from captcha.models import CaptchaStore
from django.conf import settings
from django.contrib.auth.signals import user_login_failed
from django.core.exceptions import ValidationError
from django.http import JsonResponse

LOGIN_FAILED = "아이디 또는 비밀번호가 올바르지 않습니다. 다시 확인해 주세요."
CAPTCHA_NOTICE = "안전한 로그인을 위해 아래 보안문자를 입력해 주세요."
CAPTCHA_ERROR = "보안문자가 올바르지 않습니다. 다시 입력해 주세요."


def client_ip(request):
    """Trust X-Real-IP only from explicitly configured, header-overwriting proxies."""
    peer = request.META.get("REMOTE_ADDR", "")
    value = request.META.get("HTTP_X_REAL_IP", peer) if peer in settings.LOGIN_TRUSTED_PROXY_IPS else peer
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def prepare(request, username):
    credentials = {"username": username.strip().lower()}
    AxesProxyHandler.update_request(request)
    request.axes_credentials = credentials
    return credentials


def failure_state(failures):
    remaining = max(3 - failures, 0)
    if not failures:
        notice = ""
    elif remaining:
        notice = f"로그인 {failures}회 실패 · {remaining}회 더 실패하면 보안문자 확인이 필요합니다."
    else:
        notice = f"로그인 {failures}회 실패 · 보안문자를 입력해 주세요."
    return {"failure_count": failures, "captcha_remaining": remaining,
            "failure_notice": notice, "captcha_required": failures >= 3}


def new_captcha(request):
    previous = request.session.pop("login_captcha_key", None)
    if previous:
        CaptchaStore.objects.filter(hashkey=previous).delete()
    CaptchaStore.remove_expired()
    key = CaptchaStore.generate_key()
    request.session["login_captcha_key"] = key
    return {"key": key, "image_url": captcha_image_url(key), "notice": CAPTCHA_NOTICE}


def captcha_response(request, message, status=400):
    failures = AxesProxyHandler.get_failures(request, request.axes_credentials)
    return JsonResponse({"error": message, **failure_state(failures),
                         "captcha": new_captcha(request)}, status=status)


def guard(request, credentials, body):
    failures = AxesProxyHandler.get_failures(request, credentials)
    # Session is a UI hint only. Server-side Axes records enforce the requirement.
    request.session["fail_count"] = failures
    if failures < 3:
        return None
    key, answer = body.get("captcha_key"), body.get("captcha_value")
    expected = request.session.get("login_captcha_key", "")
    if not isinstance(key, str) or not isinstance(answer, str) or len(key) > 64 or len(answer) > 64 or not expected or not compare_digest(key, expected):
        return captcha_response(request, CAPTCHA_ERROR)
    try:
        CaptchaField().clean([key, answer])
    except ValidationError:
        return captcha_response(request, CAPTCHA_ERROR)
    request.session.pop("login_captcha_key", None)
    return None


def failed(request, credentials):
    # Only an actual credential rejection emits this signal, exactly once.
    user_login_failed.send(sender=__name__, request=request, credentials=credentials)
    failures = AxesProxyHandler.get_failures(request, credentials)
    request.session["fail_count"] = failures
    if failures >= 3:
        return captcha_response(request, LOGIN_FAILED, status=401)
    return JsonResponse({"error": LOGIN_FAILED, **failure_state(failures)}, status=401)


@dataclass
class SecurityIdentity:
    username: str

    def get_username(self):
        return self.username


def succeeded(request, username):
    # Notify Axes directly: Django's global user_logged_in also runs update_last_login,
    # which expects a Django ORM User; our actual user is a SQLAlchemy account.
    AxesProxyHandler.user_logged_in(sender=__name__, request=request, user=SecurityIdentity(username))
    request.session["fail_count"] = 0
    key = request.session.pop("login_captcha_key", None)
    if key:
        CaptchaStore.objects.filter(hashkey=key).delete()
