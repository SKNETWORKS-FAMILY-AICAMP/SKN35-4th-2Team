from src.multi_modal.validate_images import validate_images


def validate_images_node(state):
    print("validate_images_node 진입", end="\n\n")

    # 읽을 수 있는 이미지만 남기고, 건너뛴 이미지는 안내로 남긴다
    images, notes = validate_images(state.get("image"))

    return {"images": images, "notes": notes}
