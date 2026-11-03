"""
2단계: 큰 이미지 줄이기.

이미지 목록  -->  [이 단계]  -->  (필요하면 줄인) 이미지 목록 + 안내 문구

- 긴 변이 RESIZE_MAX_EDGE(src/const/multi_modal_config.py)를 넘는 이미지만 그 크기에 맞춰 줄인다. 나머지는 그대로 둔다.
- 줄이면 모델에 보내는 토큰이 줄지만 작은 글자를 틀리게 읽을 수 있다. 값의 근거는 multi_modal_config.py에 있다.
- 사진의 회전 정보(EXIF)를 반영해서 똑바로 세운다.
- 형식은 유지한다: jpeg는 jpeg. png와 webp는 글자가 선명하게 남도록 png로 저장한다.
- 줄이는 데 실패하면 원본 그대로 두고 안내 문구만 남긴다 (읽기는 계속한다).
"""

import io

from PIL import Image, ImageOps

from src.const import multi_modal_config as cfg
from src.multi_modal.validate_images import ImageItem


def _shrink(item: ImageItem) -> ImageItem:
    with Image.open(io.BytesIO(item.data)) as src:
        img = ImageOps.exif_transpose(src)
        img.load()
    img.thumbnail((cfg.RESIZE_MAX_EDGE, cfg.RESIZE_MAX_EDGE), Image.LANCZOS)

    buf = io.BytesIO()
    if item.mime == "image/jpeg":
        img.convert("RGB").save(buf, "JPEG", quality=cfg.RESIZE_JPEG_QUALITY, optimize=True)
        mime = "image/jpeg"
    else:
        img.save(buf, "PNG", optimize=True)
        mime = "image/png"
    return ImageItem(item.number, buf.getvalue(), mime, img.width, img.height)


def resize_images(images: list[ImageItem]) -> tuple[list[ImageItem], list[str]]:
    """이미지 목록을 돌려준다. 줄인 이미지가 있으면 안내 문구도 함께 돌려준다."""
    result: list[ImageItem] = []
    notes: list[str] = []
    for item in images:
        if max(item.width, item.height) <= cfg.RESIZE_MAX_EDGE:
            result.append(item)
            continue
        try:
            result.append(_shrink(item))
        except Exception:  # 줄이지 못해도 원본으로 계속 읽는다
            result.append(item)
            notes.append(f"이미지 {item.number}은(는) 줄이지 못해 원본 크기로 읽었습니다.")
        else:
            notes.append(
                f"이미지 {item.number}은(는) 크기가 커서 긴 변을 {cfg.RESIZE_MAX_EDGE}px로 줄여 읽었습니다. "
                "작은 글자는 정확하지 않을 수 있습니다."
            )
    return result, notes
