"""
가입, 로그인, 로그아웃, 내 정보. 계정은 3차 DB 계층(src.db)을 그대로 쓰고, 로그인 상태는 장고 세션에 user_id만 담는다.

POST /api/auth/signup/   {"username": "...", "password": "..."}  → 200 {"user": {...}} (가입과 동시에 로그인)
POST /api/auth/login/    {"username": "...", "password": "..."}  → 200 {"user": {...}} / 401
POST /api/auth/logout/                                           → 200 {}
GET  /api/auth/me/                                               → 200 {"user": {...}} 또는 {"user": null}

가입 규칙: 아이디 영문 소문자·숫자·밑줄 3~20자, 비밀번호 8자 이상 + 영문과 숫자 모두, 아이디와 비슷한 비밀번호는 거부 (로그인에는 적용하지 않는다).

오류는 JSON {"error": "사용자에게 보여 줄 문장"}과 상태 코드로 돌려준다.
  400 입력 오류, 401 로그인 실패, 409 아이디 중복, 503 DB 문제
"""

import json
import logging
import re
from difflib import SequenceMatcher

from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache

from . import login_security
from django.views.decorators.http import require_GET, require_POST

from src.db import UsernameTakenError, authenticate, create_user, db_session

logger = logging.getLogger(__name__)

# 가입 규칙. 아이디는 3차 코어(3~30자)보다 짧게, 비밀번호는 영문+숫자 필수로 더 엄격하게 한다. 로그인에는 적용하지 않는다(기존 계정 보호).
USERNAME_MIN, USERNAME_MAX = 3, 20
USERNAME_RE = re.compile(rf"^[a-z0-9_]{{{USERNAME_MIN},{USERNAME_MAX}}}$")
PASSWORD_MIN = 8
PASSWORD_MAX_CHARS = 128  # 너무 긴 입력으로 서버를 느리게 만드는 것을 막는다
SIMILARITY_LIMIT = 0.7  # 아이디와 비밀번호가 이 비율 이상 같으면 "너무 비슷함"으로 거부한다
SESSION_USER_KEY = "user_id"
SESSION_NAME_KEY = "username"
SESSION_ADMIN_KEY = "is_admin"

LOGIN_FAILED = login_security.LOGIN_FAILED
DB_PROBLEM = "계정 정보를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요."


def error(message, status):
    return JsonResponse({"error": message}, status=status)


def public_user(username, is_admin):
    return {"username": username, "is_admin": bool(is_admin)}


def read_credentials(request):
    """요청에서 (아이디, 비밀번호)를 읽는다. 문제가 있으면 (None, 사용자에게 보여 줄 문장)."""
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, "요청 형식이 올바르지 않습니다."
    username = body.get("username") if isinstance(body, dict) else None
    password = body.get("password") if isinstance(body, dict) else None
    if not isinstance(username, str) or not isinstance(password, str) or not username.strip() or not password:
        return None, "아이디와 비밀번호를 입력해 주세요."
    if len(password) > PASSWORD_MAX_CHARS:
        return None, f"비밀번호는 {PASSWORD_MAX_CHARS}자 이하로 입력해 주세요."
    return (username, password), None


def too_similar(username, password):
    """비밀번호가 아이디를 포함하거나(거꾸로도), 아이디와 거의 같으면 True. 대소문자와 기호는 무시하고 비교한다."""
    name = re.sub(r"[^a-z0-9]", "", username)
    word = re.sub(r"[^a-z0-9]", "", password.lower())
    if not name or not word:
        return False
    if name in word or name[::-1] in word or (len(word) >= 4 and word in name):
        return True
    return SequenceMatcher(None, name, word).ratio() >= SIMILARITY_LIMIT


def check_signup_rules(username, password):
    """가입할 때만 적용하는 추가 규칙(3차 코어의 규칙보다 엄격하다). 문제가 있으면 사용자에게 보여 줄 문장, 없으면 None."""
    name = username.strip().lower()  # 코어와 같은 정리 방식 (아이디는 소문자로 저장한다)
    if not USERNAME_RE.match(name):
        return f"아이디는 영문 소문자, 숫자, 밑줄(_) {USERNAME_MIN}~{USERNAME_MAX}자여야 합니다."
    if len(password) < PASSWORD_MIN:
        return f"비밀번호는 {PASSWORD_MIN}자 이상이어야 합니다."
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        return "비밀번호에는 영문과 숫자가 모두 들어가야 합니다."
    if too_similar(name, password):
        return "비밀번호가 아이디와 너무 비슷합니다. 다른 비밀번호를 사용해 주세요."
    return None


def log_in(request, user_id, username, is_admin):
    """세션에 로그인 상태를 기록한다. 세션 키를 새로 만들어서, 로그인 전 세션을 가로챈 사람이 이어 쓰지 못하게 한다."""
    request.session.cycle_key()
    request.session[SESSION_USER_KEY] = user_id
    request.session[SESSION_NAME_KEY] = username
    request.session[SESSION_ADMIN_KEY] = bool(is_admin)


def current_user_id(request):
    """로그인한 사용자의 id. 로그인하지 않았으면 None."""
    user_id = request.session.get(SESSION_USER_KEY)
    return user_id if type(user_id) is int else None


@require_POST
def signup(request):
    credentials, problem = read_credentials(request)
    if problem:
        return error(problem, 400)
    username, password = credentials
    broken_rule = check_signup_rules(username, password)
    if broken_rule:
        return error(broken_rule, 400)
    try:
        with db_session() as session:
            user = create_user(session, username, password, is_admin=False)  # 가입으로는 관리자를 만들 수 없다
            user_id, name, is_admin = user.id, user.username, user.is_admin
    except UsernameTakenError:
        return error("이미 사용 중인 아이디입니다.", 409)
    except ValueError as problem_found:  # 아이디 형식, 비밀번호 길이 (3차 DB 계층이 사용자용 문장으로 알려 준다)
        return error(str(problem_found), 400)
    except Exception:
        logger.exception("가입 중 DB 오류")
        return error(DB_PROBLEM, 503)
    log_in(request, user_id, name, is_admin)
    return JsonResponse({"user": public_user(name, is_admin)})


@never_cache
@require_POST
def login(request):
    credentials, problem = read_credentials(request)
    if problem:
        return error(problem, 400)
    username, password = credentials
    username = username.strip().lower()
    if len(username) > 255:
        return error("아이디가 너무 깁니다.", 400)
    body = json.loads(request.body.decode("utf-8"))  # read_credentials already validated JSON.
    try:
        axes_credentials = login_security.prepare(request, username)
        blocked = login_security.guard(request, axes_credentials, body)
        if blocked is not None:
            return blocked
        with db_session() as session:
            user = authenticate(session, username, password)
            found = (user.id, user.username, user.is_admin) if user else None
        if found is None:
            return login_security.failed(request, axes_credentials)
        login_security.succeeded(request, found[1])
    except Exception:
        logger.exception("로그인 중 DB 오류")
        return error(DB_PROBLEM, 503)
    log_in(request, *found)
    return JsonResponse({"user": public_user(found[1], found[2])})


@require_POST
def logout(request):
    if current_user_id(request) is not None:
        try:
            login_security.AxesProxyHandler.user_logged_out(
                sender=__name__, request=request,
                user=login_security.SecurityIdentity(request.session.get(SESSION_NAME_KEY, "")),
            )
        except Exception:
            logger.exception("로그아웃 보안 이력 기록 오류")
    request.session.flush()
    return JsonResponse({})


@require_GET
def me(request):
    if current_user_id(request) is None:
        return JsonResponse({"user": None})
    return JsonResponse({"user": public_user(request.session.get(SESSION_NAME_KEY, ""), request.session.get(SESSION_ADMIN_KEY, False))})


@never_cache
@require_POST
def login_captcha(request):
    """Refresh a challenge without authenticating or increasing failure counts."""
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return error("요청 형식이 올바르지 않습니다.", 400)
    username = body.get("username") if isinstance(body, dict) else None
    if not isinstance(username, str) or not username.strip() or len(username) > 255:
        return error("아이디를 입력해 주세요.", 400)
    try:
        credentials = login_security.prepare(request, username)
        failures = login_security.AxesProxyHandler.get_failures(request, credentials)
        request.session["fail_count"] = failures
        return JsonResponse({**login_security.failure_state(failures),
                             "captcha": login_security.new_captcha(request) if failures >= 3 else None})
    except Exception:
        logger.exception("로그인 보안문자 준비 오류")
        return error("보안문자를 준비하지 못했습니다. 잠시 후 다시 시도해 주세요.", 503)


@never_cache
@require_GET
def lockout(request):
    # Existing bookmarks must not continue showing a removed lockout policy.
    return redirect("chat:index")
