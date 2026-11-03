from src.db.masking import mask_secrets
from src.multi_modal.encode_images import encode_images


def encode_images_node(state):
    print("encode_images_node 진입", end="\n\n")

    try:
        return {"parts": encode_images(state["images"])}
    except Exception as exc:  # 어떤 단계가 실패해도 그래프 전체가 죽지 않게 한다
        notes = [*state.get("notes", []), f"이미지 분석에 실패했습니다: {type(exc).__name__}: {mask_secrets(str(exc))[:300]}"]
        return {"parts": [], "notes": notes, "raw_text": None}
