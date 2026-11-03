"""
DB 계층(src/db)의 설정값과 기본값.

- 팀 방침대로 설정은 src/const에 모은다. 이 파일은 DB 담당 전용이라 config.py, models.py와 충돌하지 않는다.
- 여기에는 "값과 기본값"만 둔다. 환경변수로 바꾸는 동작(.env 읽기, ENV_FILE, 호출 시점마다 읽기)은 src/db에 있다.
  (환경변수를 import 시점에 한 번만 읽으면, 테스트나 배포 환경에서 값을 바꿔 쓸 수 없어서 일부러 나눴다.)

환경변수로 바꿀 수 있는 항목 (비워 두면 아래 기본값을 쓴다. 설명은 .env.example 참고)
  접속   : DATABASE_URL, DB_HOST, DB_PORT, DB_USERNAME, DB_PASSWORD, DB_DATABASE, DB_SSL, DB_SSL_CA, ENV_FILE
  이력   : HISTORY_MAX_TURNS, HISTORY_MAX_TOKENS
  이미지 : IMAGE_MAX_BYTES, IMAGE_MAX_PER_MESSAGE
  텍스트 : MESSAGE_MAX_CHARS, SNIPPET_MAX_CHARS, SUMMARY_MAX_CHARS
"""

from pathlib import Path

# 프로젝트 루트 = src/const/db_config.py 에서 두 단계 위 (README.md, data/ 가 있는 곳)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# 접속
# ---------------------------------------------------------------------------
DEFAULT_DB_PORT = 4000                      # TiDB Cloud 기본 포트 (로컬 MySQL은 DB_PORT=3306으로 지정)
DB_DRIVER = "mysql+pymysql"                 # DB_HOST가 설정되어 있을 때 쓰는 드라이버
DB_CHARSET = "utf8mb4"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}   # 이 주소로 접속할 때는 TLS를 기본으로 끈다
LOCAL_SQLITE_PATH = PROJECT_ROOT / "data" / "app.sqlite3"   # 아무 설정도 없을 때의 비상용 로컬 파일

# ---------------------------------------------------------------------------
# 대화 이력 반영 (src/db/history.py)
# ---------------------------------------------------------------------------
DEFAULT_HISTORY_MAX_TURNS = 6               # 최근 몇 번의 주고받음(질문+답변)까지 볼지. 임의로 정한 시작값
DEFAULT_HISTORY_MAX_TOKENS = 1500           # 이력이 차지할 수 있는 토큰 예산. 임의로 정한 시작값
TOKEN_ESTIMATE_DIVISOR = 3                  # 토큰 수 거친 추정: 글자 수 / 3

# ---------------------------------------------------------------------------
# 이미지 (src/db/images.py)
# 실제 DB에서 시험한 한도(2026-10-08):
#   TiDB Cloud Starter: 한 행 최대 6,291,456바이트(6MiB), 4MB는 저장됨, 6MB부터 실패(오류 8025 entry too large)
#   로컬 MySQL 8.4: MEDIUMBLOB 한도 근처인 15MB까지 저장됨
# 한 행에는 이미지 외에 썸네일, 분석 텍스트도 들어가므로 TiDB 한도의 3분의 1 수준으로 여유를 둔다.
# ---------------------------------------------------------------------------
DEFAULT_IMAGE_MAX_BYTES = 2_000_000         # 이미지 한 장의 최대 크기(바이트)
DEFAULT_IMAGE_MAX_PER_MESSAGE = 3           # 한 메시지에 붙일 수 있는 이미지 수
IMAGE_MAX_PIXELS = 40_000_000               # 가로x세로가 이보다 크면 거부 (아주 큰 이미지로 메모리를 폭주시키는 공격 방지)
IMAGE_THUMB_EDGE = 256                      # 썸네일의 긴 변(픽셀)
IMAGE_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}
IMAGE_ANALYSIS_MAX_CHARS = 100_000          # 이미지에서 읽은 텍스트의 최대 글자 수 (넘으면 잘라서 저장)
IMAGE_STORAGE_DIR_NAME = "uploads"          # 이미지 파일을 두는 기본 폴더 (프로젝트 루트 아래). IMAGE_STORAGE_DIR 환경변수로 바꾼다 (src/db/storage.py)

# ---------------------------------------------------------------------------
# 텍스트 길이 (src/db/limits.py)
# TiDB의 한 행 6MiB 제한 때문에, 한글 3바이트·이모지 4바이트로 계산해도 한참 못 미치게 잡았다.
# ---------------------------------------------------------------------------
DEFAULT_MESSAGE_MAX_CHARS = 200_000         # 질문/답변 한 건. 질문은 넘으면 거부, 답변은 잘라서 저장
DEFAULT_SNIPPET_MAX_CHARS = 50_000          # 출처 발췌문. 넘으면 잘라서 저장
DEFAULT_SUMMARY_MAX_CHARS = 50_000          # 대화 요약. 넘으면 잘라서 저장

# ---------------------------------------------------------------------------
# 답변에 붙는 출처 (src/db/sources.py의 build_sources)
# ---------------------------------------------------------------------------
SOURCES_MAX_PER_ANSWER = 10                 # 답변 한 건에 붙일 출처의 최대 개수 (화면과 DB 모두 이 목록을 쓴다)
SOURCES_SNIPPET_CHARS = 500                 # 출처 발췌문 길이. DB 상한(SNIPPET_MAX_CHARS)보다 훨씬 짧게 두어 화면에 쓰기 좋게 한다
CLIP_SUFFIX = " …(이하 생략)"               # 잘랐을 때 끝에 붙이는 표시
