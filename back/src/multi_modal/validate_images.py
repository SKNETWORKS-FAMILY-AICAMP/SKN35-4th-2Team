"""
1단계: 입력 이미지 검사.

State.image  -->  [이 단계]  -->  쓸 수 있는 이미지 목록 + 안내 문구

- State.image는 이미지 바이트, {"data": 이미지 바이트, ...}, 또는 그 목록 중 하나로 받는다.
- 형식(png/jpeg/webp)은 확장자나 mime이 아니라 파일의 실제 앞부분 바이트로 판별한다 (이름만 .png인 다른 파일을 막기 위해).
- Pillow로 깨진 이미지와 너무 큰 해상도를 거른다.
- 장수, 크기, 형식의 한도는 DB와 같은 값을 써야 하므로 src/const/db_config.py를 읽기만 한다.
  (DB 쪽 검사는 src/db/images.py에 따로 있고, 이 단계는 그와 독립적으로 동작한다.)
- 일부 이미지가 잘못되어도 나머지는 계속 읽는다. 건너뛴 이미지는 안내 문구로 남긴다.
"""

import io
from dataclasses import dataclass
from typing import Any

from PIL import Image

from src.const import db_config as limits


@dataclass
class ImageItem:
    """파이프라인의 각 단계가 주고받는 이미지 한 장."""

    number: int  # 올린 순서(1부터). 일부가 건너뛰어져도 원래 번호를 유지한다
    data: bytes
    mime: str
    width: int
    height: int


def sniff_mime(data: bytes) -> str | None:
    """파일의 앞부분 바이트로 형식을 판별한다. 허용하지 않는 형식이면 None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif data[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        return None
    return mime if mime in limits.IMAGE_ALLOWED_MIME else None


def normalize_images(value: Any) -> list[bytes]:
    """State.image를 이미지 바이트의 목록으로 바꾼다. 알 수 없는 형태는 ValueError."""
    if value is None:
        return []
    items = list(value) if isinstance(value, (list, tuple)) else [value]
    images: list[bytes] = []
    for item in items:
        if isinstance(item, (bytes, bytearray)):
            images.append(bytes(item))
        elif isinstance(item, dict) and isinstance(item.get("data"), (bytes, bytearray)):
            images.append(bytes(item["data"]))
        elif item:
            raise ValueError("State.image는 이미지 바이트, {'data': 바이트}, 또는 그 목록이어야 합니다.")
    return images


def _check_one(data: bytes) -> tuple[str, int, int]:
    """이미지 한 장을 검사해 (mime, 가로, 세로)를 돌려준다. 문제가 있으면 ValueError."""
    if not data:
        raise ValueError("이미지 데이터가 비어 있습니다")
    if len(data) > limits.DEFAULT_IMAGE_MAX_BYTES:
        raise ValueError(f"이미지가 {limits.DEFAULT_IMAGE_MAX_BYTES}바이트를 넘습니다 (현재 {len(data)}바이트)")
    mime = sniff_mime(data)
    if mime is None:
        raise ValueError("png, jpeg, webp 이미지만 읽을 수 있습니다")
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            if width * height > limits.IMAGE_MAX_PIXELS:
                raise ValueError(f"해상도가 너무 큽니다 ({width}x{height})")
            img.verify()  # 파일이 깨졌는지 확인 (다 읽지는 않는다)
    except ValueError:
        raise
    except Exception as exc:  # Pillow가 던지는 다양한 오류를 하나로 묶는다
        raise ValueError("깨졌거나 올바른 이미지 파일이 아닙니다") from exc
    return mime, width, height


def validate_images(value: Any) -> tuple[list[ImageItem], list[str]]:
    """이미지를 검사해서 (읽을 수 있는 이미지 목록, 안내 문구 목록)을 돌려준다. 예외를 던지지 않는다."""
    notes: list[str] = []
    try:
        raw = normalize_images(value)
    except ValueError as exc:
        return [], [f"이미지를 읽지 못했습니다: {exc}"]

    limit = limits.DEFAULT_IMAGE_MAX_PER_MESSAGE
    if len(raw) > limit:
        notes.append(f"이미지가 {len(raw)}장이라 앞의 {limit}장만 읽었습니다.")
        raw = raw[:limit]

    usable: list[ImageItem] = []
    for number, data in enumerate(raw, 1):
        try:
            mime, width, height = _check_one(data)
        except ValueError as exc:
            notes.append(f"이미지 {number}은(는) 읽을 수 없어 건너뛰었습니다: {exc}")
        else:
            usable.append(ImageItem(number, data, mime, width, height))
    return usable, notes
