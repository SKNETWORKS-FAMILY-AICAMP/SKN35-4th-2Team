"""
이미지 파일 저장 (서버 디스크).

이미지 원본과 썸네일은 이 폴더에 파일로 두고, DB(message_attachments)에는 그 파일의 "상대 경로"만 저장한다.

    <저장 폴더>/<메시지 번호>/<순서>_<파일 지문 앞 16자>.png        원본
    <저장 폴더>/<메시지 번호>/<순서>_<파일 지문 앞 16자>_thumb.jpg  썸네일

- 저장 폴더: 환경변수 IMAGE_STORAGE_DIR (비우면 프로젝트 루트의 uploads/). 배포할 때는 서버를 다시 시작해도 지워지지 않는 디스크로 지정한다.
- 파일 이름은 사용자가 준 이름이 아니라 번호와 해시로 만든다 (경로를 사용자가 정할 수 없게 하려는 것).
- 읽을 때도 저장 폴더 밖으로 나가는 경로는 거절한다 (DB 값이 이상해도 다른 파일을 읽지 않게 하는 방어).
- 소유자 확인은 이 모듈이 아니라 repository.py가 한다. 파일은 DB 함수를 거쳐서만 읽는다.
"""

import os
import tempfile
from pathlib import Path

from src.const import db_config as cfg

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_EXTENSION = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def storage_root() -> Path:
    """이미지 파일을 두는 폴더 (절대 경로)."""
    raw = os.getenv("IMAGE_STORAGE_DIR")
    root = Path(raw) if raw else PROJECT_ROOT / cfg.IMAGE_STORAGE_DIR_NAME
    return root.resolve()


def relative_paths(message_id: int, position: int, sha256: str, mime: str) -> tuple[str, str]:
    """(원본 경로, 썸네일 경로). DB에는 이 상대 경로를 저장한다 (항상 / 로 구분)."""
    stem = f"{message_id}/{position}_{sha256[:16]}"
    return stem + _EXTENSION[mime], stem + "_thumb.jpg"


def _safe_path(relative: str) -> Path:
    root = storage_root()
    path = (root / relative).resolve()
    if path == root or root not in path.parents:
        raise ValueError("이미지 저장 폴더 밖의 경로입니다.")
    return path


def write_file(relative: str, data: bytes) -> None:
    """파일을 쓴다. 중간에 끊겨도 반쪽짜리 파일이 남지 않게 임시 파일에 쓴 뒤 이름을 바꾼다."""
    path = _safe_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=path.parent, delete=False)
    try:
        with handle:
            handle.write(data)
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def read_file(relative: str) -> bytes:
    return _safe_path(relative).read_bytes()


def remove_files(*relatives: str | None) -> None:
    """파일을 지운다 (없는 파일은 무시, 실패해도 예외를 내지 않는다). 비어 버린 메시지 폴더도 치운다."""
    for relative in relatives:
        if not relative:
            continue
        try:
            path = _safe_path(relative)
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()  # 다른 파일이 남아 있으면 실패하고 그대로 둔다
            except OSError:
                pass
        except (OSError, ValueError):
            pass
