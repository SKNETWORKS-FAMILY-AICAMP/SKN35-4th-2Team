import os
from pathlib import Path

from dotenv import load_dotenv

# ======================== File 경로 ========================

# 프로젝트 루트 절대경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 프로젝트 루트의 .env 를 읽음 (어느 폴더에서 실행해도 같은 .env 사용)
load_dotenv(PROJECT_ROOT / ".env")

# data 폴더 절대경로
DATA_PATH = PROJECT_ROOT / "data"

# data/raw 폴더 절대경로
RAW_PATH = DATA_PATH / "raw"

# data/raw/langchain 폴더 절대경로
RAW_LANGCHAIN_PATH = RAW_PATH / "langchain"

# data/raw/langgraph 폴더 절대경로
RAW_LANGGRAPH_PATH = RAW_PATH / "langgraph"

# data/raw/mcp 폴더 절대경로
RAW_MCP_PATH = RAW_PATH / "mcp"

# data/raw/snippets 폴더 절대경로 (LangChain 문서의 코드 예제)
RAW_SNIPPETS_PATH = RAW_PATH / "snippets"

# data/processed 폴더 절대경로 (전처리 결과, chunks.jsonl)
PROCESSED_PATH = DATA_PATH / "processed"

# data/processed/langchain 폴더 절대경로
PROCESSED_LANGCHAIN_PATH = PROCESSED_PATH / "langchain"

# data/processed/langgraph 폴더 절대경로
PROCESSED_LANGGRAPH_PATH = PROCESSED_PATH / "langgraph"

# data/processed/mcp 폴더 절대경로
PROCESSED_MCP_PATH = PROCESSED_PATH / "mcp"

# 청크 파일 절대경로 (splitter 결과 확인·평가용)
CHUNKS_PATH = PROCESSED_PATH / "chunks.jsonl"

# BM25 Sparse 인코더 학습 결과 (retriever 의 Hybrid 검색에 사용, build 때 생성)
BM25_PATH = PROCESSED_PATH / "bm25_params.json"

# 기술 이름 목록
TECHS = ["langchain", "langgraph", "mcp"]

# 기술별 원본 폴더
RAW_PATHS = {
    "langchain": RAW_LANGCHAIN_PATH,
    "langgraph": RAW_LANGGRAPH_PATH,
    "mcp": RAW_MCP_PATH,
}

# 기술별 전처리 폴더
PROCESSED_PATHS = {
    "langchain": PROCESSED_LANGCHAIN_PATH,
    "langgraph": PROCESSED_LANGGRAPH_PATH,
    "mcp": PROCESSED_MCP_PATH,
}


# ======================== ENV ========================

# OPENAI API KEY (.env 에 OPENAI_API_KEY 로 적어도 읽음)
OPEN_API_KEY = os.getenv("OPEN_API_KEY") or os.getenv("OPENAI_API_KEY")

# OPENAI LLM MODEL NAME (Query Rewrite, Multi-Query, Context 압축)
OPEN_MODEL = os.getenv("OPEN_MODEL", "gpt-4o-mini")

# OPENAI EMBEDDING MODEL NAME
OPEN_EMBEDDING_MODEL = os.getenv("OPEN_EMBEDDING", "text-embedding-3-small")

# PINECONE API KEY
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

# PINECONE INDEX NAME (소문자·숫자·하이픈만)
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "skn35-rag")


# ======================== RAG 설정 ========================

# 임베딩 벡터 차원 (text-embedding-3-small 1536, text-embedding-3-large 3072)
# Pinecone 인덱스 차원과 반드시 같아야 함
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))

# RERANK MODEL NAME (Cross-Encoder, 로컬 실행: 다국어라 한국어 질문 ↔ 영어 문서 OK)
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

# 재정렬 실행 방식: auto(기본) / onnx / torch
#   onnx  : ONNX int8 모델 (torch 없이 실행. 시작이 빠르고 가볍다. src/rag/export_reranker_onnx.py로 한 번 만들어 둔다)
#   torch : sentence-transformers CrossEncoder (원래 방식. 첫 실행 때 모델 약 2GB 다운로드)
#   auto  : ONNX 모델 파일이 있으면 onnx, 없으면 torch
RERANK_BACKEND = os.getenv("RERANK_BACKEND", "auto").strip().lower()

# ONNX int8 재정렬 모델 폴더 (model_int8.onnx, model_int8.onnx.data, tokenizer.json). git에는 올라가지 않는다.
RERANK_ONNX_DIR = Path(os.getenv("RERANK_ONNX_DIR") or DATA_PATH / "onnx" / "bge-reranker-v2-m3-int8")

# PINECONE 서버리스 위치 (무료 플랜은 aws / us-east-1)
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1")

# 청크 크기 (글자 수, 영어 1,000자 ≈ 250 토큰)
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))


# 채팅 UI 설정 및 기존 NVIDIA 호환 설정
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or OPEN_API_KEY
OPENAI_MODEL = os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL")
NVIDIA_EMBEDDING_MODEL = os.getenv("NVIDIA_EMBEDDING")
NVIDIA_RERANK_API_KEY = os.getenv("NVIDIA_RERANK_API_KEY")
NVIDIA_RERANK_MODEL = os.getenv("NVIDIA_RERANK_MODEL")
