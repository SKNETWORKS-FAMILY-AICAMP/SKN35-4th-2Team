"""
이미지 검증 / 썸네일 / 용량 줄이기.

- DB 계층(add_image)이 쓰는 검증 함수와, 이미지를 올리는 쪽(UI 등)이 올리기 전에 쓸 수 있는 shrink_image가 들어 있다.
- 형식(png/jpeg/webp)은 사용자가 알려 준 확장자나 mime이 아니라 파일의 실제 앞부분 바이트로 판별한다
  (이름만 .png인 다른 파일을 막기 위해).
- Pillow가 있으면 이미지가 정상인지(깨졌는지)와 크기(가로x세로)까지 확인하고 썸네일을 만든다.
  Pillow가 없으면 앞부분 바이트 검사만 하고 썸네일은 만들지 않는다. (프로젝트 의존성에는 Pillow가 있다.)

설정(환경변수, 비워 두면 기본값)
- IMAGE_MAX_BYTES        : 이미지 한 장의 최대 크기(바이트). 기본 DEFAULT_MAX_BYTES
- IMAGE_MAX_PER_MESSAGE  : 한 메시지에 붙일 수 있는 이미지 수. 기본 3
"""

import hashlib
import io
import os

from src.const import db_config as cfg

# 값과 기본값(근거가 된 DB 시험 결과 포함)은 src/const/db_config.py에 있다.
# 아래는 이 모듈과 테스트가 기존 이름 그대로 쓸 수 있게 한 별칭이다.
DEFAULT_MAX_BYTES = cfg.DEFAULT_IMAGE_MAX_BYTES
DEFAULT_MAX_PER_MESSAGE = cfg.DEFAULT_IMAGE_MAX_PER_MESSAGE
MAX_ANALYSIS_CHARS = cfg.IMAGE_ANALYSIS_MAX_CHARS
MAX_PIXELS = cfg.IMAGE_MAX_PIXELS
THUMB_EDGE = cfg.IMAGE_THUMB_EDGE
ALLOWED_MIME = cfg.IMAGE_ALLOWED_MIME


def max_image_bytes() -> int:
    return int(os.getenv("IMAGE_MAX_BYTES") or DEFAULT_MAX_BYTES)


def max_images_per_message() -> int:
    return int(os.getenv("IMAGE_MAX_PER_MESSAGE") or DEFAULT_MAX_PER_MESSAGE)


def sniff_mime(data: bytes) -> str | None:
    """파일의 앞부분 바이트로 형식을 판별한다. 허용하지 않는 형식이면 None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def clip_analysis(text: str | None) -> str | None:
    """분석 텍스트가 너무 길면 잘라서 표시를 남긴다 (실패시키지 않는다: 모델이 만든 텍스트라서)."""
    if text and len(text) > MAX_ANALYSIS_CHARS:
        return text[:MAX_ANALYSIS_CHARS] + cfg.CLIP_SUFFIX
    return text


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pillow():
    try:
        from PIL import Image

        return Image
    except ImportError:
        return None


def inspect_image(data: bytes) -> tuple[int | None, int | None]:
    """(가로, 세로)를 돌려준다. 깨진 이미지나 너무 큰 이미지는 ValueError. Pillow가 없으면 (None, None)."""
    Image = _pillow()
    if Image is None:
        return None, None
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            if width * height > MAX_PIXELS:
                raise ValueError(f"이미지 해상도가 너무 큽니다 ({width}x{height}).")
            img.verify()  # 파일이 깨졌는지 확인 (다 읽지는 않는다)
        return width, height
    except ValueError:
        raise
    except Exception as exc:  # Pillow가 던지는 다양한 오류를 하나로 묶는다
        raise ValueError("올바른 이미지 파일이 아닙니다.") from exc


def validate_image(data: bytes) -> tuple[str, int | None, int | None]:
    """저장해도 되는 이미지인지 검사한다. 통과하면 (mime, 가로, 세로), 아니면 ValueError.

    저장하기 전에 미리 부를 수 있어서, 메시지는 저장됐는데 이미지는 실패하는 상황을 막는 데 쓴다.
    """
    if not data:
        raise ValueError("이미지 데이터가 비어 있습니다.")
    limit = max_image_bytes()
    if len(data) > limit:
        raise ValueError(f"이미지는 {limit}바이트 이하여야 합니다 (현재 {len(data)}바이트).")
    mime = sniff_mime(data)
    if mime is None:
        raise ValueError("png, jpeg, webp 이미지만 저장할 수 있습니다.")
    width, height = inspect_image(data)  # 깨진 이미지, 너무 큰 해상도는 ValueError
    return mime, width, height


def make_thumbnail(data: bytes) -> bytes | None:
    """긴 변 THUMB_EDGE 픽셀의 작은 JPEG 미리보기. Pillow가 없거나 만들 수 없으면 None."""
    Image = _pillow()
    if Image is None:
        return None
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.thumbnail((THUMB_EDGE, THUMB_EDGE))
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, "white")  # 투명 배경은 흰색으로
                flat.paste(rgba, mask=rgba.split()[-1])
                img = flat
            elif img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=70, optimize=True)
            return buf.getvalue()
    except Exception:
        return None


def shrink_image(data: bytes, *, max_bytes: int | None = None, max_edge: int = 1600) -> tuple[bytes, str]:
    """이미지를 max_bytes 이하로 줄여서 (바이트, mime)을 돌려준다. 이미지를 올리는 쪽이 올리기 전에 쓴다.

    1) 긴 변을 max_edge 이하로 줄이고 PNG로 저장해 본다 (스크린샷의 글자가 선명하게 남는다).
    2) 그래도 크면 JPEG 품질을 단계적으로 낮추고, 그래도 크면 해상도를 더 줄인다.
    줄일 수 없으면 ValueError. Pillow가 필요하다.
    """
    Image = _pillow()
    if Image is None:
        raise RuntimeError("shrink_image는 Pillow가 필요합니다.")
    from PIL import ImageOps

    max_bytes = max_bytes or max_image_bytes()
    try:
        with Image.open(io.BytesIO(data)) as src:
            img = ImageOps.exif_transpose(src)  # 사진의 회전 정보를 반영
            img.load()
    except Exception as exc:
        raise ValueError("올바른 이미지 파일이 아닙니다.") from exc
    if max(img.size) > max_edge:
        img.thumbnail((max_edge, max_edge))

    def png(i) -> bytes:
        buf = io.BytesIO()
        i.save(buf, "PNG", optimize=True)
        return buf.getvalue()

    def jpeg(i, quality: int) -> bytes:
        buf = io.BytesIO()
        i.save(buf, "JPEG", quality=quality, optimize=True)
        return buf.getvalue()

    has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
    out = png(img if img.mode in ("RGB", "RGBA", "L", "LA", "P") else img.convert("RGB"))
    if len(out) <= max_bytes:
        return out, "image/png"

    rgb = img.convert("RGB")
    if has_alpha:
        rgba = img.convert("RGBA")
        rgb = Image.new("RGB", rgba.size, "white")
        rgb.paste(rgba, mask=rgba.split()[-1])
    for quality in (90, 80, 70, 60, 50):
        out = jpeg(rgb, quality)
        if len(out) <= max_bytes:
            return out, "image/jpeg"
    for _ in range(8):  # 해상도를 20%씩 줄여 가며 다시 시도
        rgb = rgb.resize((max(1, int(rgb.width * 0.8)), max(1, int(rgb.height * 0.8))), Image.LANCZOS)
        out = jpeg(rgb, 60)
        if len(out) <= max_bytes:
            return out, "image/jpeg"
    raise ValueError(f"이미지를 {max_bytes}바이트 이하로 줄일 수 없습니다.")
