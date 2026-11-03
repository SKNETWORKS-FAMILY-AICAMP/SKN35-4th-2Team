"""
재정렬 모델(BAAI/bge-reranker-v2-m3)을 ONNX int8로 바꿔서 data/onnx/ 아래에 만든다.

    python -m src.rag.export_reranker_onnx [--out 폴더] [--force]

- 한 번만 하면 된다 (약 2~3분). 원래 모델(약 2.2GB)이 내려받아져 있어야 하고, 이 변환에는 torch와 onnx가 필요하다.
- 만들어지는 파일(model_int8.onnx, model_int8.onnx.data, tokenizer.json, 약 570MB)은 git에 올리지 않는다. 각자 한 번 만든다.
- 만든 뒤에는 설정 RERANK_BACKEND가 auto이면 앱이 알아서 ONNX를 쓴다 (원래 방식으로 되돌리려면 RERANK_BACKEND=torch).
- 중간 파일(압축 전 모델)은 임시 폴더에 만들고 끝나면 지운다.
"""

import argparse
import tempfile
import time
from pathlib import Path

from src.const.config import RERANK_MODEL, RERANK_ONNX_DIR
from src.rag.rerank_onnx import DATA_FILE, MAX_LENGTH, MODEL_FILE, TOKENIZER_FILE


def export(out_dir: Path, force: bool = False) -> Path:
    out_dir = Path(out_dir)
    if (out_dir / MODEL_FILE).exists() and not force:
        print(f"이미 있습니다: {out_dir} (다시 만들려면 --force)")
        return out_dir

    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    tokenizer = AutoTokenizer.from_pretrained(RERANK_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(RERANK_MODEL).eval()
    batch = tokenizer([("질문 예시", "문서 예시 글")], return_tensors="pt", padding=True, truncation=True, max_length=MAX_LENGTH)

    with tempfile.TemporaryDirectory() as tmp:
        fp32 = Path(tmp) / "model.onnx"
        print("1/3 ONNX로 변환 중 ...", flush=True)
        torch.onnx.export(
            model,
            (batch["input_ids"], batch["attention_mask"]),
            str(fp32),
            input_names=["input_ids", "attention_mask"],
            output_names=["logits"],
            dynamic_axes={"input_ids": {0: "batch", 1: "seq"}, "attention_mask": {0: "batch", 1: "seq"}, "logits": {0: "batch"}},
            opset_version=17,
            dynamo=False,
        )
        print("2/3 int8로 압축 중 (1~2분) ...", flush=True)
        for old in (out_dir / MODEL_FILE, out_dir / DATA_FILE):
            old.unlink(missing_ok=True)
        quantize_dynamic(str(fp32), str(out_dir / MODEL_FILE), weight_type=QuantType.QInt8, use_external_data_format=True)

    print("3/3 토크나이저 복사 ...", flush=True)
    tokenizer.save_pretrained(out_dir)
    if not (out_dir / TOKENIZER_FILE).exists():
        raise RuntimeError(f"{TOKENIZER_FILE}를 만들지 못했습니다. 토크나이저 종류를 확인하세요.")

    size = sum(path.stat().st_size for path in out_dir.iterdir() if path.is_file()) / 1e6
    print(f"완료: {out_dir} ({size:.0f}MB, {time.time() - started:.0f}초)")
    return out_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(RERANK_ONNX_DIR), help="만들 폴더 (기본: 설정 RERANK_ONNX_DIR)")
    parser.add_argument("--force", action="store_true", help="이미 있어도 다시 만든다")
    args = parser.parse_args()
    export(Path(args.out), force=args.force)


if __name__ == "__main__":
    main()
