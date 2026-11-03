"""
3단계: 모델에 보낼 형태로 바꾸기.

이미지 목록  -->  [이 단계]  -->  모델 메시지에 그대로 넣을 content 조각 목록

- 모델은 이미지 파일을 직접 받지 못하고 base64 문자열(data URL)로 받는다.
- 이미지마다 "[이미지 N]"이라는 글자를 앞에 붙여서, 일부가 건너뛰어져도 올린 순서의 번호를 유지한다.
- 이미지를 읽는 정밀도(detail)는 src/const/multi_modal_config.py의 IMAGE_DETAIL이다.
"""

import base64

from src.const import multi_modal_config as cfg
from src.multi_modal.validate_images import ImageItem


def encode_images(images: list[ImageItem]) -> list[dict]:
    parts: list[dict] = []
    for item in images:
        encoded = base64.b64encode(item.data).decode("ascii")
        parts.append({"type": "text", "text": f"[이미지 {item.number}]"})
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{item.mime};base64,{encoded}", "detail": cfg.IMAGE_DETAIL},
            }
        )
    return parts
