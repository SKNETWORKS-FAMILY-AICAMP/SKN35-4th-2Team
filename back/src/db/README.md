# src/db — 로그인, 대화 내역, 이미지, 출처 저장

사용자 계정, 대화와 메시지, 첨부 이미지, 답변 출처를 관계형 DB에 저장하고, 다음 질문에 붙일 **대화 이력**을 상한 안에서 골라 주는 계층이다.
LangGraph, 벡터 DB(Pinecone)와는 무관하다. 그래프는 이 DB를 직접 건드리지 않고, **그래프를 부르는 쪽(UI)이** 아래 함수 두 개로 저장한다.

- 상태: 구동 가능한 지점까지 완료. UI와 그래프에는 아직 연결하지 않았다.
- 확인: 로컬 MySQL 8.4와 TiDB Cloud 양쪽에서 마이그레이션과 기능 확인, 테스트 185개(`tests/`) 통과.

## 빠른 사용

```python
from src.db import (db_session, create_user, authenticate, record_user_turn,
                    record_assistant_turn, get_history_context, list_messages)

with db_session() as s:                      # with 블록 하나 = 트랜잭션 하나 (정상이면 commit, 예외면 rollback)
    create_user(s, "alice01", "비밀번호8자이상")      # 가입 (아이디: 영문 소문자/숫자/밑줄 3~30자)
    user = authenticate(s, "alice01", "비밀번호8자이상")   # 로그인. 실패하면 None (이유는 알려 주지 않는다)
    user_id = user.id

# 1) 그래프를 실행하기 "전에": 사용자의 질문(텍스트, 이미지 최대 3장)을 먼저 저장
with db_session() as s:
    turn = record_user_turn(s, user_id, "State가 전달되지 않아요", conversation_id=None, images=[png_bytes])
    history = get_history_context(s, turn.conversation_id, user_id)   # [{"role","content"}, ...] 상한 안으로 줄인 이력

# ... 그래프 실행 (history를 messages로 넘김) ...

# 2) 그래프가 끝난 "후에": 답변과 출처, 이미지에서 읽은 텍스트를 저장
with db_session() as s:
    record_assistant_turn(s, user_id, turn.conversation_id, answer,
                          sources=[{"url": "...", "title": "...", "tech": "langgraph", "version": "1.x",
                                    "doc_type": "docs", "snippet": "...", "score": 0.9}],
                          user_message_id=turn.message_id, image_analysis=state.get("image_analysis"))

with db_session() as s:                      # 화면에 대화 내역을 그릴 때
    messages = list_messages(s, turn.conversation_id, user_id)        # 오래된 것부터, 각 메시지의 attachments/sources 포함
```

## 꼭 알아 둘 규칙

- **`user_id`가 항상 필요하다.** 대화, 메시지, 이미지, 출처는 모두 소유자 확인을 거친다. 남의 것은 `None`이나 `PermissionError`.
- 예외: `ValueError`(입력 오류: 아이디 형식, 비밀번호 8자 미만, 이미지 형식·크기, 너무 긴 질문), `PermissionError`(남의 데이터), `UsernameTakenError`(아이디 중복).
- `record_*` 함수는 **저장하기 전에 입력을 먼저 검사**한다. 실패하면 아무것도 쓰지 않는다. 이 예외는 `db_session` 블록 밖으로 내보낸다(잡지 않는다).
- 시각은 **UTC**로 저장한다 (TiDB Cloud 서버가 UTC이고 DB의 NOW()를 쓰지 않는다). 한국 시간으로 보여 줄 때는 화면에서 변환한다(변환 함수는 아직 없다).
- 질문과 답변은 저장 전에 **API 키 같은 비밀을 `[MASKED:...]`로 가린다**(알려진 형태만. 완벽한 보호가 아니다). 이미지는 가릴 수 없다.
- **이미지는 서버 디스크의 파일로 저장**하고 DB에는 파일 경로만 둔다(`src/db/storage.py`). 저장 폴더는 환경변수 `IMAGE_STORAGE_DIR`(비우면 프로젝트 루트의 `uploads/`)이고, **배포할 때는 서버를 다시 시작해도 지워지지 않는 디스크**로 지정해야 한다. LLM에 다시 보내지 않고, 대화 이력에는 이미지가 아니라 **텍스트**만 붙는다.
- 한 메시지에 이미지 3장까지, 한 장 2MB까지(기본). 형식은 png/jpeg/webp이고 확장자가 아니라 파일의 실제 바이트로 판별한다.
- 관리자(`is_admin`)는 가입 화면으로 만들 수 없다. `create_user(..., is_admin=True)`나 시드로만 만든다. **가입 화면에서는 `is_admin`을 사용자 입력으로 받지 말고 항상 False로 고정한다.**

## 환경변수와 설정

접속과 상한의 이름, 기본값, 설명은 **`.env.example`** 에 있다(`.env`로 복사해서 채운다). 기본값은 `src/const/db_config.py` 한 곳에 있다.
핵심은 `DB_HOST`, `DB_PORT`, `DB_USERNAME`, `DB_PASSWORD`, `DB_DATABASE`(없으면 로컬 SQLite 파일로 동작하는 비상 모드), 이력 상한 `HISTORY_MAX_TURNS`, `HISTORY_MAX_TOKENS`다.

- 로컬 `localhost`는 TLS를 끄고 그 밖의 서버(TiDB Cloud)는 켠다 (`DB_SSL`로 직접 지정 가능).
- 다른 환경 파일을 쓰려면 `ENV_FILE=.env.tidb`를 명령 앞에 붙인다. 지정하면 이미 읽힌 값보다 우선한다.
- 이 폴더는 팀의 `src/const/config.py`에 의존하지 않는다 (`import src.db`가 `config.py`를 불러오지 않는다).

## 개발용 DB 준비 (팀원 각자)

개발은 팀 전체가 하므로, **각자 PC에서 아래 셋 중 하나**를 고른다. 시연은 TiDB Cloud로 한다.
모든 방법에서 코드는 같고, `.env`의 `DB_*` 값만 다르다. 테스트(`uv run pytest tests -q`)는 DB가 없어도 돈다(메모리 SQLite).

| 방법 | 언제 | 주의 |
|---|---|---|
| **A. 각자 로컬 MySQL** (권장) | 시연 DB(TiDB)와 가장 비슷하게 개발하고 싶을 때 | 계정과 대화 데이터는 **PC마다 따로**다 (다른 팀원의 계정은 내 PC에 없다). 마이그레이션과 시드도 각자 한 번씩 한다 |
| **B. 공용 TiDB** | 팀원이 같은 데이터를 봐야 할 때 | 시연 데이터와 섞이지 않게 **개발용 DB를 따로 만들어**(예: `skn35_3rd_dev`) `DB_DATABASE`로 지정한다. 마이그레이션과 시드는 한 사람만 실행한다 |
| **C. 설치 없이 SQLite** | 빠르게 코드만 돌려 볼 때 | `DB_*`를 비워 두면 `data/app.sqlite3` 파일로 동작한다(`.gitignore`로 제외됨). MySQL/TiDB와 동작이 다를 수 있어서, 동작 확인은 A나 B로 한 번 더 한다 |

### A. 로컬 MySQL 만들기

1. MySQL을 설치한다 (이 저장소의 확인은 **MySQL 8.4** 기준이다. 다른 버전과 MariaDB는 확인하지 못했다).
2. 관리자(root)로 접속해서 이 프로젝트 전용 데이터베이스와 사용자를 만든다. 다른 프로젝트 DB와 섞이지 않게 전용으로 만든다.
   - 접속: 설치 폴더의 `bin\mysql.exe -u root -p` (또는 DBeaver 같은 도구에서 SQL 실행)
   ```sql
   CREATE DATABASE skn35_3rd CHARACTER SET utf8mb4;
   CREATE USER 'skn35_3rd'@'localhost' IDENTIFIED BY '<새 비밀번호>';
   GRANT ALL PRIVILEGES ON skn35_3rd.* TO 'skn35_3rd'@'localhost';
   ```
   - DBeaver에서 여러 줄을 한 번에 실행하려면 `Alt + X`(스크립트 실행)를 쓴다. `Ctrl + Enter`는 한 줄만 실행한다.
   - DBeaver에서만 `Public Key Retrieval is not allowed` 오류가 나면 연결 설정의 드라이버 속성에서 `allowPublicKeyRetrieval=true`로 바꾼다 (이 프로젝트 코드로 접속할 때는 필요하지 않았다).
3. `.env`에 접속 값을 넣는다. 로컬은 포트가 `3306`이고(`.env.example`의 기본 `4000`은 TiDB용), `localhost`면 TLS는 자동으로 꺼진다.
   ```
   DB_HOST=localhost
   DB_PORT=3306
   DB_USERNAME=skn35_3rd
   DB_PASSWORD=<위에서 정한 비밀번호>
   DB_DATABASE=skn35_3rd
   ```
4. 테이블을 만든다: `uv run alembic -c src/db/alembic.ini upgrade head` (아래 명령어 참고). 관리자 계정이 필요하면 `.env`의 `SEED_ADMIN_*`를 채우고 시드를 실행한다.

### B. 공용 TiDB를 쓸 때

- 접속 정보(호스트, 사용자, 비밀번호)는 채팅이나 저장소에 올리지 말고 안전한 방법으로 받아 `.env`에만 넣는다.
- `localhost`가 아닌 서버는 TLS가 자동으로 켜진다. 포트는 기본 `4000`이다.
- 두 DB(로컬 MySQL과 TiDB)를 오가며 쓸 때는 TiDB 값을 `.env.tidb` 같은 별도 파일에 두고 `ENV_FILE=.env.tidb`를 명령 앞에 붙이면 된다 (`.env.*`는 `.gitignore`로 제외된다). 하나만 쓰면 `.env` 하나면 충분하다.

## 명령어 (프로젝트 루트에서)

```bash
uv run alembic -c src/db/alembic.ini upgrade head     # DB 구조를 최신으로 (처음 한 번, 구조가 바뀔 때마다)
uv run python -m src.db.seed                          # 관리자 계정 만들기 (.env의 SEED_ADMIN_USERNAME/PASSWORD)
uv run pytest tests -q                                # 테스트 (메모리 SQLite 사용, 실제 DB에 접속하지 않는다)
ENV_FILE=.env.tidb uv run alembic -c src/db/alembic.ini upgrade head   # 다른 DB(TiDB)에 적용할 때 (PowerShell: $env:ENV_FILE=".env.tidb")
```

- 공유 DB(TiDB)에서는 **마이그레이션과 시드를 팀에서 정한 한 사람만** 실행한다. 이미 있는 계정은 건너뛴다.
- 테이블 구조를 바꿀 때는 `models.py`를 고치고 `migrations/versions/`에 새 파일을 추가한다. 둘이 어긋나면 `tests/db/test_migrations.py`가 실패한다.
- `init_db()`는 테스트용이다. 실제 DB는 반드시 마이그레이션으로 만든다.

## 테이블

| 테이블 | 내용 |
|---|---|
| `users`, `user_profiles` | 계정(비밀번호는 scrypt 해시만 저장), 기본 개발 환경 |
| `conversations`, `messages` | 대화, 메시지(`input_type` text/image, `env_snapshot`, `image_analysis`) |
| `message_attachments` | 사용자 메시지에 딸린 이미지 정보. 원본과 썸네일은 파일이고 `file_path`, `thumb_path`에 경로만 저장 (이전에 DB에 바이트로 저장된 행은 `data`, `thumb_data`로 읽음) |
| `message_sources` | 답변의 출처(URL, 제목, 버전, 발췌문, 점수, 근거 여부) |

## 파일

| 파일 | 역할 |
|---|---|
| `turns.py` | `record_user_turn`, `record_assistant_turn` (UI가 쓰는 입구) |
| `storage.py` | 이미지 파일을 서버 디스크에 쓰고, 읽고, 지움. 저장 폴더 밖의 경로는 거절 |
| `move_images_to_files.py` | 이전 방식(DB 저장) 이미지를 파일로 옮기는 도구: `uv run python -m src.db.move_images_to_files` |
| `repository.py` | 가입, 로그인, 계정 관리, 대화, 메시지, 이미지, 출처 함수 |
| `history.py` | 대화 이력을 턴 수와 토큰 예산 안으로 고르는 로직 (DB와 무관한 순수 함수) |
| `images.py`, `masking.py`, `limits.py` | 이미지 검증·썸네일·용량 줄이기, 비밀 가리기, 길이 상한 |
| `engine.py`, `session.py` | DB 연결, `db_session()` |
| `models.py`, `migrations/` | 테이블 정의, 구조 변경 이력 (0001~0004) |
| `seed.py` | 관리자 계정 |

## 알려진 한계 (아직 하지 않은 것)

- **UI와 LangGraph에 연결하지 않았다.** 그래프 쪽에서 정해야 할 것: `InMemorySaver`(thread_id)와 DB 이력을 함께 쓰면 같은 대화가 중복으로 쌓일 수 있다 (요청마다 새 thread_id를 쓰거나 둘 중 하나만 쓴다).
- 메시지 순서를 `id`로 정한다. TiDB는 서버가 여러 대면 `AUTO_INCREMENT`가 단조 증가하지 않을 수 있다고 공식 문서에 있다. 새 연결로 160건을 넣어 본 시험에서는 역전이 없었다.
- TiDB Cloud 한 행은 최대 6MiB다(실측). 이미지 2MB, 질문 20만 자 등 상한은 이 한도 안에 들어가게 잡았다 (`src/const/db_config.py`).
- 백업·내보내기는 팀 논의 후 이번 범위에서 제외했다. 다만 TiDB 무료 티어의 데이터 보존 정책은 확인하지 못했으니, 중요한 시연 전에는 데이터가 남아 있는지 직접 확인한다.
- 비밀번호 찾기 없음(이메일을 받지 않는다). 관리자가 `reset_password`로 초기화한다. 로그인 실패 잠금과 로그인 유지(새로고침 후)는 없다.
- 이력의 토큰 수는 `글자 수 / 3`의 거친 추정이다 (`history.estimate_tokens`). 기본 상한(6턴, 1500토큰)은 임의로 잡은 시작값이다.
