"""
이전 방식(DB에 바이트로 저장)의 이미지를 서버 파일로 옮긴다.

    uv run python -m src.db.move_images_to_files

- 파일 경로가 없고 data가 있는 행만 대상이다. 원본과 썸네일 파일을 쓰고, DB에는 경로를 채운 뒤 data, thumb_data를 비운다.
- 파일을 쓴 뒤에 DB를 바꾸므로, 중간에 실패해도 이미지는 사라지지 않는다 (다시 실행하면 이어서 한다).
- 여러 번 실행해도 안전하다 (이미 옮긴 행은 건너뛴다).
- 저장 폴더는 환경변수 IMAGE_STORAGE_DIR (src/db/storage.py).
"""

from sqlalchemy import select

from . import storage
from .models import MessageAttachment
from .session import db_session


def main() -> None:
    moved = skipped = 0
    with db_session() as session:
        rows = session.scalars(
            select(MessageAttachment).where(MessageAttachment.file_path.is_(None))
        ).all()
        for att in rows:
            data = att.data
            if data is None:
                skipped += 1
                continue
            original_path, thumb_path = storage.relative_paths(att.message_id, att.position, att.sha256, att.mime_type)
            storage.write_file(original_path, data)
            if att.thumb_data:
                storage.write_file(thumb_path, att.thumb_data)
                att.thumb_path = thumb_path
            att.file_path = original_path
            att.data = None
            att.thumb_data = None
            moved += 1
    print(f"옮긴 이미지 {moved}장, 건너뜀 {skipped}장 (저장 폴더: {storage.storage_root()})")


if __name__ == "__main__":
    main()
