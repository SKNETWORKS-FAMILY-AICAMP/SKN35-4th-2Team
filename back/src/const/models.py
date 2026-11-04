from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.const.config import (
    OPEN_API_KEY,
    OPEN_EMBEDDING_MODEL,
    OPEN_MODEL,
    RERANK_BACKEND,
    RERANK_MODEL,
    RERANK_ONNX_DIR,
)


# OPENAI LLM MODEL
def create_openai_model(temperature=0.0, timeout=600):
    model = ChatOpenAI(
        api_key=OPEN_API_KEY,
        model=OPEN_MODEL,
        temperature=temperature,
        timeout=timeout,
    )

    return model


# OPENAI EMBEDDING MODEL
def create_openai_embedding():
    embedding = OpenAIEmbeddings(api_key=OPEN_API_KEY, model=OPEN_EMBEDDING_MODEL)

    return embedding


# RERANK MODEL (Cross-Encoder)
def rerank_backend():
    """재정렬 실행 방식을 정한다: "onnx" 또는 "torch" (설정 RERANK_BACKEND, auto면 ONNX 모델 파일이 있을 때 onnx)."""
    from src.rag.rerank_onnx import onnx_model_ready

    if RERANK_BACKEND == "torch":
        return "torch"
    if RERANK_BACKEND == "onnx":
        return "onnx"
    return "onnx" if onnx_model_ready(RERANK_ONNX_DIR) else "torch"


def create_rerank():
    if rerank_backend() == "onnx":
        # torch 없이 실행하므로 시작이 빠르다 (ONNX int8, 약 570MB)
        from src.rag.rerank_onnx import OnnxReranker

        return OnnxReranker(RERANK_ONNX_DIR)

    # pip install sentence-transformers (첫 실행 때 모델 약 2GB 다운로드, GPU 없으면 다소 느림)
    from sentence_transformers import CrossEncoder

    rerank = CrossEncoder(RERANK_MODEL, max_length=512)

    return rerank


# 개인 채팅 화면에서 사용하는 NVIDIA 지원도 유지합니다.
from src.const.config import (
    OPENAI_API_KEY, NVIDIA_API_KEY, NVIDIA_MODEL, NVIDIA_EMBEDDING_MODEL,
    NVIDIA_RERANK_API_KEY, NVIDIA_RERANK_MODEL,
)

# NVIDIA LLM MODEL
def create_nvidia_model(temperature=0.0, timeout=600):
    from langchain_nvidia_ai_endpoints import ChatNVIDIA
    model = ChatNVIDIA(
        api_key=NVIDIA_API_KEY,
        model=NVIDIA_MODEL,
        temperature=temperature,
        timeout=timeout,
    )

    return model


# NVIDIA EMBEDDING MODEL
def create_nvidia_embedding():
    from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
    embedding = NVIDIAEmbeddings(api_key=NVIDIA_API_KEY, model=NVIDIA_EMBEDDING_MODEL)

    return embedding


# NVIDIA RERANK MODEL
def create_nvidia_rerank():
    from langchain_nvidia_ai_endpoints import NVIDIARerank
    rerank = NVIDIARerank(api_key=NVIDIA_RERANK_API_KEY, model=NVIDIA_RERANK_MODEL)

    return rerank


# OPENAI CLIENT
def create_openai_client(timeout=60):
    from openai import OpenAI

    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY 설정이 필요합니다.")
    return OpenAI(api_key=OPENAI_API_KEY, timeout=timeout, max_retries=0)
