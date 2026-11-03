-- ============================================================
-- CodeClue 데이터베이스 생성 스크립트 (MySQL 8.x / TiDB Cloud)
--
-- 기준: 로컬 MySQL 8.4에서 alembic 마이그레이션 0001~0005를 적용한 실제 테이블 (SHOW CREATE TABLE 결과)
-- 테이블 6개: users, user_profiles, conversations, messages, message_attachments, message_sources
--
-- 사용법
--   1) 아래 데이터베이스 이름(skn35_3rd)을 배포 환경의 이름으로 바꾼다.
--      TiDB Cloud는 콘솔에서 만든 이름을 그대로 쓰고, 시스템 DB(sys, mysql, test 등)는 쓰지 않는다.
--   2) 한 번만 실행한다 (이미 있으면 건너뛰도록 IF NOT EXISTS를 썼다).
--   3) 계정은 이 파일에 없다. 관리자 계정은 .env의 SEED_ADMIN_* 를 채운 뒤
--      uv run python -m src.db.seed  로 만든다 (비밀번호 해시는 SQL로 직접 넣지 않는다).
--
-- 이미지 저장 방식 (중요)
--   첨부 이미지의 원본과 썸네일은 DB가 아니라 서버(앱이 실행되는 PC)의 폴더에 파일로 저장한다.
--   DB(message_attachments)에는 그 파일의 상대 경로(file_path, thumb_path)만 저장한다.
--   - 저장 폴더: .env의 IMAGE_STORAGE_DIR. 비워 두면 프로젝트 루트의 uploads/ (git에는 올라가지 않는다).
--   - 이미지 파일은 저장한 PC에만 있다. DB를 여럿이 공유해도 파일은 공유되지 않아서,
--     다른 PC에서는 글은 보이고 이미지(썸네일)만 안 보인다 (화면이 깨지지는 않는다).
--     그래서 발표처럼 한 PC에서 시연할 때는 그 PC에서 올린 이미지가 그대로 보인다.
--   - 실제 서비스로 운영한다면 서버를 다시 시작해도 지워지지 않는 디스크로 IMAGE_STORAGE_DIR을 지정해야 한다.
--   - data, thumb_data 칸은 예전 방식(DB에 바이트로 저장)의 이미지를 읽기 위해 남겨 둔 것이라 새 이미지는 NULL이다.
--     예전 이미지를 파일로 옮기려면: uv run python -m src.db.move_images_to_files
--
-- 이미 만들어 둔 DB(0004 구조)를 쓰고 있다면 이 파일을 다시 실행하지 말고 구조만 올린다:
--   uv run alembic -c src/db/alembic.ini upgrade head
--   (이 명령을 실행하지 않으면 이미지가 있는 질문이 DB 오류로 실패한다. 팀원도 최신 코드를 받은 뒤 한 번 실행해야 한다.)
--
-- 이 파일 대신 alembic으로 만들 수도 있다 (같은 결과):
--   uv run alembic -c src/db/alembic.ini upgrade head
-- 이 파일로 만든 DB에 나중에 alembic을 쓰려면 맨 아래 "alembic 버전 표시"를 실행해 둔다.
-- ============================================================

CREATE DATABASE IF NOT EXISTS skn35_3rd DEFAULT CHARACTER SET utf8mb4;
USE skn35_3rd;

-- 1. 사용자 (비밀번호는 원문이 아니라 scrypt 해시만 저장한다)
CREATE TABLE IF NOT EXISTS `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(50) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `is_admin` tinyint(1) NOT NULL,
  `created_at` datetime NOT NULL,
  `last_login_at` datetime DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_users_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. 사용자 개발 환경 (users와 1:1)
CREATE TABLE IF NOT EXISTS `user_profiles` (
  `user_id` int NOT NULL,
  `python_version` varchar(20) DEFAULT NULL,
  `os` varchar(50) DEFAULT NULL,
  `lib_versions` json DEFAULT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`user_id`),
  CONSTRAINT `user_profiles_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. 대화 (사용자 한 명이 여러 개)
CREATE TABLE IF NOT EXISTS `conversations` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `title` varchar(200) NOT NULL,
  `summary` mediumtext,
  `summary_upto_message_id` int DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_conversations_user_id` (`user_id`),
  CONSTRAINT `conversations_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. 메시지 (질문과 답변. role은 user 또는 assistant)
CREATE TABLE IF NOT EXISTS `messages` (
  `id` int NOT NULL AUTO_INCREMENT,
  `conversation_id` int NOT NULL,
  `role` varchar(16) NOT NULL,
  `input_type` varchar(16) NOT NULL,
  `content` mediumtext NOT NULL,
  `env_snapshot` json DEFAULT NULL,
  `token_count` int NOT NULL,
  `created_at` datetime NOT NULL,
  `image_analysis` mediumtext,
  PRIMARY KEY (`id`),
  KEY `ix_messages_conversation_id` (`conversation_id`),
  CONSTRAINT `messages_ibfk_1` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. 첨부 이미지 (메시지당 최대 3장은 코드가 제한한다)
--    원본과 썸네일은 서버 디스크의 파일이고 file_path, thumb_path에 경로만 저장한다 (저장 폴더: .env의 IMAGE_STORAGE_DIR).
--    data, thumb_data는 이전 방식(DB 저장)의 이미지를 읽기 위한 칸이라 새 이미지는 NULL이다.
CREATE TABLE IF NOT EXISTS `message_attachments` (
  `id` int NOT NULL AUTO_INCREMENT,
  `message_id` int NOT NULL,
  `position` int NOT NULL,
  `mime_type` varchar(50) NOT NULL,
  `size_bytes` int NOT NULL,
  `width` int DEFAULT NULL,
  `height` int DEFAULT NULL,
  `sha256` varchar(64) NOT NULL,
  `file_path` varchar(255) DEFAULT NULL,
  `thumb_path` varchar(255) DEFAULT NULL,
  `data` mediumblob,
  `thumb_data` mediumblob,
  `analysis_text` mediumtext,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_message_attachments_message_id` (`message_id`),
  CONSTRAINT `message_attachments_ibfk_1` FOREIGN KEY (`message_id`) REFERENCES `messages` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. 답변 출처 (rank는 표시 순서. is_grounded는 아직 채우는 코드가 없다)
CREATE TABLE IF NOT EXISTS `message_sources` (
  `id` int NOT NULL AUTO_INCREMENT,
  `message_id` int NOT NULL,
  `rank` int NOT NULL,
  `url` varchar(1000) NOT NULL,
  `title` varchar(300) DEFAULT NULL,
  `tech` varchar(30) DEFAULT NULL,
  `version` varchar(30) DEFAULT NULL,
  `doc_type` varchar(30) DEFAULT NULL,
  `snippet` mediumtext,
  `score` float DEFAULT NULL,
  `is_grounded` tinyint(1) DEFAULT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_message_sources_message_id` (`message_id`),
  CONSTRAINT `message_sources_ibfk_1` FOREIGN KEY (`message_id`) REFERENCES `messages` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ------------------------------------------------------------
-- alembic 버전 표시 (선택): 이 파일로 만든 DB에 나중에 alembic upgrade를 쓰려면 실행한다.
-- 쓰지 않을 거면 건너뛴다.
-- ------------------------------------------------------------
-- CREATE TABLE IF NOT EXISTS `alembic_version` (
--   `version_num` varchar(32) NOT NULL,
--   PRIMARY KEY (`version_num`)
-- ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- INSERT INTO `alembic_version` (`version_num`) VALUES ('0005');
