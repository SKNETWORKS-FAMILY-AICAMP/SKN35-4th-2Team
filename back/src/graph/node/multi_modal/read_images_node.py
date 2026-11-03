from src.db.masking import mask_secrets
from src.graph.node.multi_modal.build_analysis_node import question_text
from src.multi_modal.read_images import read_images


def read_images_node(state):
    print("read_images_node 진입", end="\n\n")

    try:
        # 이미지를 한 번에 읽는다 (여러 장이어도 모델은 한 번만 부른다)
        return {"raw_text": read_images(state["parts"], question_text(state))}
    except Exception as exc:  # 네트워크, 한도, 키 오류 등
        notes = [*state.get("notes", []), f"이미지 분석에 실패했습니다: {type(exc).__name__}: {mask_secrets(str(exc))[:300]}"]
        return {"raw_text": None, "notes": notes}
