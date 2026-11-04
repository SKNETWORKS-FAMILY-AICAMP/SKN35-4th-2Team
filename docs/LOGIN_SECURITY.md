# CodeClue 로그인 보안

## 실제 구조와 연동

- 화면: `front/templates/chat.html`, 동작: `front/static/js/chat.js`.
- 기존 `/api/auth/login/` JSON 요청과 성공 응답, 로그인 후 화면 전환을 유지한다.
- `chat/accounts.py`의 SQLAlchemy `authenticate(session, username, password)`를 요청당 한 번만 호출한다.
- 기존 Django AuthenticationForm/LoginForm 또는 커스텀 인증 백엔드는 없다. Django 기본 `ModelBackend`는 보존하고 `AxesStandaloneBackend`를 맨 앞에 추가했다.
- Django `authenticate()`로 교체하면 기존 SQLAlchemy 계정 대신 다른 사용자 테이블을 인증할 위험이 있어 교체하지 않았다.
- 실제 request를 Axes 공개 ProxyHandler에 전달해 서버의 실패 횟수를 확인한다. 실제 인증 실패에만 Django `user_login_failed` 신호를 한 번 보낸다.
- 성공은 `AxesProxyHandler.user_logged_in`으로 통지한다. Django 전역 성공 신호의 `update_last_login` 수신기는 Django ORM User를 요구하므로 SQLAlchemy 계정에는 호출하지 않는다.
- 기존 서명된 쿠키의 `user_id`, `username`, `is_admin`과 CSRF 보호를 유지한다. 기존 대화 저장·소유권 검사 및 `back/src/`는 변경하지 않는다.

## 동작

| 결과 | 다음 상태 |
|---|---|
| 실제 인증 1~2회 실패 | 동일한 일반 오류 + 서버 실패 횟수 + 캡차까지 남은 횟수 표시 |
| 3회 실패 직후 | 같은 실패 응답에 캡차 이미지 URL·키 포함 |
| 캡차 누락·오류·만료 | 비밀번호 검증 미실행, 실패 횟수 유지, 새 캡차 제공 |
| 유효한 캡차 + 4회째 인증 실패 | 새 캡차 유지 |
| 유효한 캡차 + 5·6회 이상 인증 실패 | 실패 횟수 증가, 캡차 유지, 시간 제한 없이 재시도 |
| 올바른 캡차 + 올바른 로그인 정보 | 즉시 로그인, 현재 username·IP 실패 기록과 세션 fail_count 초기화 |

- 실패 기록 기준은 정규화한 username(앞뒤 공백 제거·소문자)과 IP의 조합이다.
- Axes 9 공식 설정 `AXES_LOCK_OUT_AT_FAILURE=False`로 백엔드·미들웨어의 실패 횟수 기반 차단을 해제했다. 기록 기능은 계속 사용한다.
- `AXES_COOLOFF_TIME=None`이며 별도 10분 대기나 실패 기록의 시간 만료는 없다. 실패 기록은 성공 시 해당 username·IP에 대해서만 초기화한다.
- 과거 5회 이상 실패한 기록도 삭제할 필요 없이 정상 캡차 검증 후 바로 로그인할 수 있다.
- 인증 실패 응답에 `failure_count`, `captcha_remaining`, `failure_notice`, `captcha_required`를 제공한다. UI는 서버가 제공한 문구를 textContent로 표시한다.
- 1회: `로그인 1회 실패 · 2회 더 실패하면 보안문자 확인이 필요합니다.`
- 2회: `로그인 2회 실패 · 1회 더 실패하면 보안문자 확인이 필요합니다.`
- 3회 이상: `로그인 N회 실패 · 보안문자를 입력해 주세요.`
- `session['fail_count']`는 표시용이다. 실제 캡차 필요 여부도 Axes DB 횟수로 판정해 쿠키 삭제·이전 쿠키 재전송으로 우회하지 못한다.
- 캡차는 세션의 발급 키와 대조한 뒤 `CaptchaField`로 검증한다. 잘못된 캡차는 단일 사용 처리 후 새로 발급한다.
- `POST /api/auth/captcha/`는 JSON username과 CSRF 토큰으로 캡차를 갱신하며 실패 횟수를 늘리지 않는다.
- 루트 `/captcha/`는 라이브러리 이미지 URL에 사용한다. 정적 파일 URL과 충돌하지 않는다.
- 기존 `/auth/lockout/` 주소는 로그인 화면으로 이동한다. 로그인 API의 잠금 응답·Retry-After·잠금 페이지 이동 처리는 제거했다.

## 설치와 개발 실행

현재 Python 3.12.13 / Django 5.2.18 기준으로 `django-axes==9.0.0`, `django-simple-captcha==0.7.0`을 검증했다.
Pillow는 기존 `pillow>=12.3.0` 의존성을 재사용한다. `uv.lock`에 실제 버전을 기록했다.

```powershell
# 저장소 최상위 폴더, 개발 환경에서
uv sync
cd back
uv run python manage.py check
uv run python manage.py migrate
uv run python manage.py runserver
```

이제 서명된 쿠키를 사용하더라도 Axes·Captcha를 위해 Django DB 테이블이 반드시 필요하다.
기본 Django DB는 `back/db.sqlite3`이며, SQLAlchemy 계정·대화 DB(`DB_*`)와는 별개다.
최초 기능 추가 시 로컬 개발 DB에 Axes·Captcha 테이블을 적용했다. 이번 잠금 제거 변경은 스키마 변경이 없어 새 마이그레이션이 필요 없다. 운영 DB는 변경하지 않았다.
운영 반영 시 관리자가 해당 환경의 Django DB 경로·백업·마이그레이션 실행을 확인해야 한다.
라이브러리에 포함된 마이그레이션을 사용하므로 프로젝트 자체의 새 모델 마이그레이션은 없다.

## IP와 배포

기본은 REMOTE_ADDR만 사용하며 임의의 X-Forwarded-For/X-Real-IP를 신뢰하지 않는다.
기존 nginx 설정은 X-Real-IP를 덮어쓰므로, nginx가 로컬에서 프록시하고 Django 직접 접근이 차단된 배포에서만
`LOGIN_TRUSTED_PROXY_IPS=127.0.0.1,::1`을 설정할 수 있다. 허용된 프록시에서만 X-Real-IP를 사용한다.
여러 서버에 배포한다면 Axes·Captcha의 Django DB도 공용 DB로 구성해야 한다. 서버별 SQLite는 서버 간 실패 횟수·캡차를 공유하지 않는다.

## 검증 및 수동 확인

```powershell
uv run python back/manage.py test chat
```

개발용 계정으로 잘못된 비밀번호를 1·2회 입력해 서버 횟수와 남은 횟수 안내를 확인한다.
3회 실패 응답에서 바로 캡차가 표시되어야 한다. 잘못된 캡차·빈 입력은 인증 실패 횟수를 늘리지 않아야 한다.
올바른 캡차와 틀린 비밀번호로 5·6회 이상 시도해도 401 오류와 현재 횟수가 표시되고 같은 화면에서 재시도할 수 있어야 한다.
올바른 캡차와 로그인 정보로 즉시 로그인할 수 있어야 하며, 성공 후 실패 횟수는 0이다.
이전 정책에서 5회 이상 실패한 기존 기록도 삭제하지 않고, 캡차 검증 후 즉시 로그인할 수 있어야 한다.

검증: 전체 Django 테스트 143개 통과. 격리 개발 서버의 실제 JSON·CSRF·SQLAlchemy·Axes·Captcha 브라우저 흐름에서
1/2/3/5/6회 안내, 캡차 오류 시 횟수 유지, 6회 이후 성공, 과거 7회 실패 기록 로그인, 페이지 이동·Retry-After 없음, 성공 후 안내 초기화를 확인했다.
전체 기록 삭제나 `axes_reset`은 실행하지 않았다. 타 사용자 실패 기록이 보존되는 테스트도 포함한다.

## 공식 문서

- [Axes 9 릴리스·호환성](https://pypi.org/project/django-axes/9.0.0/)
- [Axes 커스텀 인증·JSON 응답 연동](https://django-axes.readthedocs.io/en/stable/5_customization.html)
- [Axes 설정](https://django-axes.readthedocs.io/en/latest/4_configuration.html)
- [Captcha 설치·AJAX·서버 검증](https://django-simple-captcha.readthedocs.io/en/latest/usage.html)
- [Captcha 요구 환경](https://django-simple-captcha.readthedocs.io/en/latest/)
