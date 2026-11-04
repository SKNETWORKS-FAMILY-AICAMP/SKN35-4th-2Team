from src.multi_modal.resize_images import resize_images


def resize_images_node(state):
    print("resize_images_node 진입", end="\n\n")

    images, resize_notes = resize_images(state["images"])

    return {"images": images, "notes": [*state.get("notes", []), *resize_notes]}
