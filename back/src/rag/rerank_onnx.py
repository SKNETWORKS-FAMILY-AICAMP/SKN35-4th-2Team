"""
ONNX int8 재정렬기: sentence-transformers의 CrossEncoder와 같은 모양(.predict)으로 쓸 수 있다.

    OnnxReranker(폴더).predict([(질문, 문서 글), ...])  -->  관련도 점수 목록 (0~1, 클수록 관련 있음)

- 원래 모델(BAAI/bge-reranker-v2-m3)을 ONNX로 바꾸고 int8로 압축한 파일을 onnxruntime으로 실행한다.
  torch와 transformers를 불러오지 않아서 앱을 켤 때 훨씬 빠르고(라이브러리 약 25초 -> 1초 이내), 모델도 약 2.2GB -> 약 570MB로 작다.
- 점수는 CrossEncoder와 같은 방식(질문-문서 쌍을 최대 512 토큰으로 자르고 sigmoid)으로 만든다.
  int8 압축 때문에 점수가 조금 달라질 수 있다 (2026-10 평가: 검색 지표 차이는 오차 범위 안, 재정렬 시간은 약 절반).
- 폴더에 있어야 하는 파일: model_int8.onnx, model_int8.onnx.data, tokenizer.json
  (src/rag/export_reranker_onnx.py가 만든다. 용량이 커서 git에는 올리지 않는다.)
"""

from pathlib import Path

MODEL_FILE = "model_int8.onnx"
DATA_FILE = "model_int8.onnx.data"
TOKENIZER_FILE = "tokenizer.json"
MAX_LENGTH = 512
BATCH_SIZE = 8


def onnx_model_ready(directory) -> bool:
    """ONNX 재정렬 모델 파일이 모두 있고 onnxruntime을 불러올 수 있으면 True."""
    directory = Path(directory)
    if not all((directory / name).exists() for name in (MODEL_FILE, DATA_FILE, TOKENIZER_FILE)):
        return False
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError:
        return False
    return True


class OnnxReranker:
    def __init__(self, directory, batch_size: int = BATCH_SIZE):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        directory = Path(directory)
        if not onnx_model_ready(directory):
            raise FileNotFoundError(
                f"ONNX 재정렬 모델이 없습니다: {directory}\n"
                "python -m src.rag.export_reranker_onnx 로 만들거나, 설정 RERANK_BACKEND=torch 로 원래 방식을 쓰세요."
            )
        self._np = np
        self.batch_size = batch_size
        self.session = ort.InferenceSession(str(directory / MODEL_FILE), providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(directory / TOKENIZER_FILE))
        self.tokenizer.enable_truncation(max_length=MAX_LENGTH)
        self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id("<pad>"), pad_token="<pad>")

    def _scores(self, batch):
        np = self._np
        encoded = self.tokenizer.encode_batch([(str(question), str(text)) for question, text in batch])
        input_ids = np.array([item.ids for item in encoded], dtype=np.int64)
        attention_mask = np.array([item.attention_mask for item in encoded], dtype=np.int64)
        logits = self.session.run(["logits"], {"input_ids": input_ids, "attention_mask": attention_mask})[0]
        return 1 / (1 + np.exp(-logits[:, 0]))  # CrossEncoder와 같은 sigmoid

    def predict(self, pairs, *args, **kwargs):
        """(질문, 글) 쌍 목록의 점수를 numpy 배열로 돌려준다. 쌍이 없으면 빈 배열."""
        np = self._np
        pairs = list(pairs)
        if not pairs:
            return np.array([], dtype=np.float32)
        scores = [self._scores(pairs[start : start + self.batch_size]) for start in range(0, len(pairs), self.batch_size)]
        return np.concatenate(scores)
