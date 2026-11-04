"""
서버를 켤 때 재정렬 모델(ONNX) 폴더가 있는지 미리 확인해서, 없으면 이유와 해결 방법을 알려 준다.

모델 폴더(back/data/onnx/)는 용량(약 570MB) 때문에 git에 올리지 않는다. 없는 PC에서 질문하면 코어가 원래 방식(sentence-transformers)으로
넘어가려다 실패하고, 화면에는 원인을 알 수 없는 "답변을 받지 못했습니다" 문장만 보인다. 그래서 서버를 켤 때 먼저 알려 준다.
"""

from importlib.util import find_spec

from django.core.checks import Warning, register


def reranker_problem():
    """재정렬 모델을 쓸 수 없으면 사용자에게 보여 줄 문장(이유와 해결 방법)을, 문제가 없으면 None을 돌려준다."""
    from src.const.config import RERANK_BACKEND, RERANK_ONNX_DIR
    from src.rag.rerank_onnx import onnx_model_ready

    if RERANK_BACKEND == "torch":
        return None  # 원래 방식을 직접 고른 경우
    if onnx_model_ready(RERANK_ONNX_DIR):
        return None
    if RERANK_BACKEND != "onnx" and find_spec("sentence_transformers") is not None:
        return None  # 모델 폴더는 없지만 원래 방식으로 대신 실행할 수 있다
    return (
        f"재정렬 모델 폴더가 없어서 질문에 답할 수 없습니다: {RERANK_ONNX_DIR}  "
        "(폴더 안에 model_int8.onnx, model_int8.onnx.data, tokenizer.json이 있어야 합니다.)"
    )


RERANKER_HINT = "종원에게 back/data/onnx 폴더를 받아서 back/data/ 안에 넣으세요. 직접 만들려면 README의 '재정렬 모델 준비'를 보세요."


@register()
def check_reranker_model(app_configs, **kwargs):
    problem = reranker_problem()
    return [Warning(problem, hint=RERANKER_HINT, id="chat.W001")] if problem else []
