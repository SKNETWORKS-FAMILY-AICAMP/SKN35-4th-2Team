"""
Django 설정.

- 백엔드는 back/, 프론트(HTML, CSS, JS)는 front/ 폴더에 있다. 아래 TEMPLATES와 STATICFILES_DIRS가 front/를 가리킨다.
- 비밀값(API 키, SECRET_KEY 등)은 back/.env에서 읽는다 (git에 올리지 않는다). 예시는 .env.example.
- 운영(AWS)에서는 DJANGO_DEBUG=0, DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS를 꼭 설정한다.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # back/
REPO_ROOT = BASE_DIR.parent  # 저장소 맨 위 (back/, front/, docs/가 있는 곳)
FRONT_DIR = REPO_ROOT / "front"

load_dotenv(BASE_DIR / ".env")


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# ---------------------------------------------------------------- 보안
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"  # 운영에서는 반드시 0
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or "dev-only-insecure-key-change-me"
if not DEBUG and SECRET_KEY == "dev-only-insecure-key-change-me":
    raise RuntimeError("운영에서는 DJANGO_SECRET_KEY를 설정해야 합니다.")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")  # 예: http://13.125.0.1

# ---------------------------------------------------------------- 앱
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "chat",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # 운영에서 정적 파일(CSS, JS)을 바로 내준다
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------- 프론트(HTML, CSS, JS)는 front/ 폴더
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [FRONT_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

STATIC_URL = "/static/"
STATICFILES_DIRS = [FRONT_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic이 모으는 곳 (운영)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage" if not DEBUG else "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# ---------------------------------------------------------------- DB (Django 자체 용도: 로그인, 대화 저장)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ---------------------------------------------------------------- 로그인 세션 (계정 자체는 3차 DB 계층이 관리하고, 장고는 user_id만 세션에 담는다)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True  # 브라우저를 닫으면 로그인 종료
SESSION_COOKIE_AGE = 60 * 60 * 24  # 열어 둔 채로도 최대 24시간
SESSION_COOKIE_SAMESITE = "Lax"
# HTTPS로 서비스할 때만 1로 켠다. HTTP에서 켜면 쿠키가 전달되지 않아 로그인이 되지 않는다.
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = os.getenv("DJANGO_SECURE_COOKIES", "0") == "1"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------- 질문 처리 한도
CHAT_QUESTION_MAX_CHARS = 4000  # 이전 대화(이력)의 양은 3차 DB 계층이 HISTORY_MAX_TURNS, HISTORY_MAX_TOKENS로 정한다
