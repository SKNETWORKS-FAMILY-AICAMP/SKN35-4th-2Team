# AWS 배포 순서

EC2 서버 1대에 올리는 가장 단순한 방식입니다. **처음에는 IP 주소로 HTTP 접속**까지 만들고, 시간이 남으면 HTTPS를 붙입니다.

```
사용자 브라우저 → (80번) nginx → gunicorn(Django) → 3차 엔진 → OpenAI / Pinecone / TiDB
```

> ⚠️ 이 문서의 서버 명령은 **로컬에서 검증하지 못한 부분**이 있습니다 (gunicorn은 Windows에서 실행되지 않음).
> 로컬에서 확인한 것: 운영 모드(`DEBUG=0`) 설정, 정적 파일 수집, 비밀키가 없으면 시작 거부.
> 서버에서 처음 해 보는 단계는 6장의 확인 절차로 직접 검증하세요.

---

## 0. 시작 전에 준비할 것

| 항목 | 설명 |
|---|---|
| AWS 계정 | 접속 가능한 계정, 사용할 리전은 서울(`ap-northeast-2`) 권장 |
| 예산 알림 | **먼저** 설정한다 (Billing → Budgets, 월 한도와 알림 이메일) |
| `back/.env` | 로컬의 파일. 서버로 안전하게 옮긴다 (3장) |
| 재정렬 모델 | `back/data/onnx/bge-reranker-v2-m3-int8/` 폴더 (약 570MB, git에 없음) |
| 서버 주소 | 아래 1장의 Elastic IP |

---

## 1. EC2 서버 만들기

1. **EC2 → 인스턴스 시작**
   - 이름: `codeclue`
   - 이미지(AMI): **Ubuntu Server 24.04 LTS** (또는 22.04)
   - 인스턴스 유형: **t3.medium (메모리 4GB)** 권장. 모델이 메모리를 쓰므로 너무 작으면 느리거나 죽을 수 있습니다. (실제 사용량은 배포 후 측정해서 기록합니다.)
   - 키 페어: 새로 만들어 `.pem` 파일을 **안전하게 보관** (잃어버리면 접속할 수 없습니다. 저장소나 채팅에 올리지 않기)
   - 스토리지: **20GB 이상** (모델 570MB + 파이썬 패키지)
2. **보안 그룹(방화벽) 규칙**

   | 유형 | 포트 | 허용 대상 |
   |---|---|---|
   | SSH | 22 | **내 IP만** (전체 공개 금지) |
   | HTTP | 80 | 모두 (`0.0.0.0/0`) |
   | HTTPS | 443 | HTTPS를 붙일 때 추가 |

   > 8000번 포트는 **열지 않습니다.** gunicorn은 서버 안에서 nginx하고만 통신합니다.
3. **Elastic IP 할당 후 인스턴스에 연결** — 서버를 껐다 켜도 주소가 바뀌지 않게 합니다. 이 주소를 아래에서 `서버IP`로 씁니다.
4. **TiDB 접속 허용 확인**: TiDB Cloud 콘솔에서 접속 허용 IP 목록(Networking)이 있다면 서버 IP를 추가합니다. (제한이 없으면 필요 없습니다.)

---

## 2. 서버 접속과 기본 설치

내 PC에서 (경로는 본인 `.pem` 위치):

```bash
ssh -i C:\경로\codeclue.pem ubuntu@서버IP
```

서버에서:

```bash
sudo apt update
sudo apt install -y nginx git
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

선택(메모리가 부족할 때를 대비한 안전장치, 2GB 스왑):

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
```

---

## 3. 코드와 비밀값 올리기

**① 코드** (서버에서)

```bash
cd ~
git clone https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN35-4th-2Team.git SKN35-4th-2team
cd SKN35-4th-2team
git checkout Dev        # 합쳐진 브랜치 이름에 맞게 (Dev 또는 main)
uv sync --no-dev        # 파이썬은 .python-version(3.12)에 맞게 uv가 알아서 설치
```

> 저장소 주소와 브랜치 이름은 실제 값으로 확인하세요. 비공개 저장소라 인증이 필요하면 팀에서 정한 방법(토큰 등)으로 받습니다.

**② `.env` 올리기** — 내 PC에서 (`.env`는 git에 없으므로 직접 복사)

```bash
scp -i C:\경로\codeclue.pem C:\sk-encoa\SKN35-4th-2team\back\.env ubuntu@서버IP:~/SKN35-4th-2team/back/.env
```

**③ 재정렬 모델 올리기** — 내 PC에서 (570MB, 몇 분 걸림)

```bash
scp -i C:\경로\codeclue.pem -r C:\sk-encoa\SKN35-4th-2team\back\data\onnx ubuntu@서버IP:~/SKN35-4th-2team/back/data/
```

> 서버에서 모델을 직접 변환하지 않습니다 (변환에는 torch가 필요해서 서버가 무거워집니다).

**④ 서버의 `back/.env`에 운영 설정 추가** — 서버에서 `nano ~/SKN35-4th-2team/back/.env`

```
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=여기에-긴-무작위-문자열
DJANGO_ALLOWED_HOSTS=서버IP
DJANGO_CSRF_TRUSTED_ORIGINS=http://서버IP
```

비밀키 만들기 (서버에서 출력된 값을 위에 붙여 넣기):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

> - `DJANGO_SECURE_COOKIES`는 **넣지 않습니다.** HTTP로 접속하는 동안 켜면 로그인이 되지 않습니다. HTTPS를 붙인 뒤에만 1로 켭니다.
> - **이미지 저장 폴더**: 첨부 이미지는 서버 디스크의 파일로 저장됩니다(기본 `back/uploads/`, DB에는 경로만). 서버를 다시 만들어도 남기려면 `back/.env`에 `IMAGE_STORAGE_DIR=/home/ubuntu/codeclue-uploads` 처럼 지정하세요. 폴더는 `mkdir -p`로 미리 만들고, nginx의 `client_max_body_size`(32m)는 이미 설정 파일에 들어 있습니다.
> - `DB_DATABASE`는 `skn35_4th`인지 확인하세요 (3차 DB `skn35_3rd`와 섞이지 않게).
> - DB 테이블과 관리자 계정은 이미 `skn35_4th`에 만들어져 있어서, 서버에서 마이그레이션과 시드를 다시 할 필요가 없습니다.
> - 로그인 상태는 서명된 쿠키에 담기므로 장고용 `migrate`도 필요 없습니다 (`DJANGO_SECRET_KEY`가 바뀌면 모두 로그아웃됩니다).

---

## 4. Django 준비

서버에서:

```bash
cd ~/SKN35-4th-2team
uv run python back/manage.py collectstatic --noinput   # 화면 파일(CSS, JS) 모으기
uv run python back/manage.py check           # 오류가 없어야 함
```

---

## 5. gunicorn과 nginx 켜기

설정 파일은 저장소의 `docs/deploy/`에 있습니다. 서버에서:

```bash
cd ~/SKN35-4th-2team
sudo cp docs/deploy/codeclue.service /etc/systemd/system/codeclue.service
sudo systemctl daemon-reload
sudo systemctl enable --now codeclue

sudo cp docs/deploy/nginx.conf /etc/nginx/sites-available/codeclue
sudo ln -sf /etc/nginx/sites-available/codeclue /etc/nginx/sites-enabled/codeclue
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

> 사용자 이름이 `ubuntu`가 아니거나 폴더 위치가 다르면 `codeclue.service`의 경로를 먼저 고칩니다.

---

## 6. 확인 절차 (순서대로)

| 순서 | 확인 | 기대 결과 | 안 되면 |
|---|---|---|---|
| 1 | `sudo systemctl status codeclue` | `active (running)` | `journalctl -u codeclue -n 80 --no-pager` 로 오류 확인 |
| 2 | 서버에서 `curl http://127.0.0.1:8000/api/health/` | `{"status": "ok"}` | 1번부터 다시 |
| 3 | 내 PC 브라우저에서 `http://서버IP/` | 로그인 화면 | 보안 그룹 80번, `nginx -t`, `systemctl status nginx` |
| 4 | 가입 → 로그인 | 채팅 화면 | 아래 문제 해결표 |
| 5 | 질문 → 답변이 **한 글자씩** 나타남 | 스트리밍 + 출처 | 아래 문제 해결표 |
| 6 | 새로고침 → 대화 목록에서 다시 열기 | 이전 대화 표시 | DB 연결(`DB_*`) 확인 |

첫 질문은 모델 준비 때문에 몇 초 더 걸릴 수 있습니다. **서버가 켜지고 첫 질문까지의 시간, `free -h`로 본 메모리 사용량을 기록**해 두세요 (README와 테스트 보고서에 쓸 값).

---

## 7. 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| 502 Bad Gateway | gunicorn이 안 떠 있음 | `journalctl -u codeclue -n 80 --no-pager` |
| 400 (DisallowedHost) | 접속 주소가 허용 목록에 없음 | `DJANGO_ALLOWED_HOSTS`에 서버IP 추가 |
| 질문 보낼 때 403 | CSRF 출처 불일치 | `DJANGO_CSRF_TRUSTED_ORIGINS=http://서버IP` |
| 로그인해도 바로 풀림 | HTTP인데 `DJANGO_SECURE_COOKIES=1` | 그 줄을 지우거나 0으로 |
| 답변이 모였다가 한꺼번에 나옴 | nginx 버퍼링 | `nginx.conf`의 `proxy_buffering off` 확인 후 reload |
| 서비스가 시작되자마자 죽음 | `DJANGO_SECRET_KEY` 없음, 또는 메모리 부족 | 로그 확인, 인스턴스 유형 올리기 |
| 답변 오류(모델 못 찾음) | `back/data/onnx/...` 폴더 누락 | 3장 ③ 다시 |
| "계정 정보를 확인하지 못했습니다" | DB 접속 실패 | `DB_*` 값, TiDB 허용 IP, TiDB 클러스터 상태 |
| 변경한 화면이 안 보임 | 정적 파일 미갱신 | `collectstatic` 후 `systemctl restart codeclue`, 브라우저 강력 새로고침 |

---

## 8. 코드 수정 후 다시 배포

서버에서:

```bash
cd ~/SKN35-4th-2team
git pull
uv sync --no-dev
uv run python back/manage.py collectstatic --noinput
sudo systemctl restart codeclue
```

---

## 9. HTTPS (시간이 남을 때, 도메인이 있을 때만)

IP 주소만으로는 일반 인증서를 받을 수 없어서 **도메인이 필요**합니다. 도메인이 생기면:

1. 도메인의 A 레코드를 Elastic IP로 연결
2. `nginx.conf`의 `server_name`을 도메인으로 바꾸고 `sudo apt install -y certbot python3-certbot-nginx && sudo certbot --nginx -d 도메인`
3. `back/.env` 수정: `DJANGO_ALLOWED_HOSTS`에 도메인 추가, `DJANGO_CSRF_TRUSTED_ORIGINS=https://도메인`, `DJANGO_SECURE_COOKIES=1`
4. `sudo systemctl restart codeclue`

발표 전까지 도메인이 없으면 **HTTP + IP로 발표**해도 됩니다. 다만 비밀번호가 암호화 없이 오가므로 시연 전용 계정만 쓰고, 이 한계를 README에 적어 두세요.

---

## 10. 비용과 정리

- 서버를 쓰지 않을 때는 **인스턴스를 중지**합니다 (중지 중에는 컴퓨팅 비용이 들지 않지만, 디스크와 Elastic IP 요금은 별도입니다).
- 발표가 끝나면 인스턴스, Elastic IP, 보안 그룹, 디스크를 정리합니다.
- `.pem` 파일과 `.env`는 어디에도 올리지 않습니다.
