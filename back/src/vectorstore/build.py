"""
벡터 DB 만들기: documents.jsonl → 청크 → BM25 학습 → Pinecone Hybrid 업로드

실행 (프로젝트 루트에서)
  python -m src.vectorstore.build                   # 세 기술 전부 (기존 벡터를 지우고 새로)
  python -m src.vectorstore.build --tech mcp        # 일부만 (기존 벡터는 그대로 두고 덮어씀, 테스트용)

실제 코드는 src/rag/retriever.py 의 build_pinecone() 입니다.
"""

import argparse

from src.rag.retriever import build_pinecone


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tech", nargs="+", help="langchain / langgraph / mcp 중 일부만")
    args = parser.parse_args()

    build_pinecone(technologies=args.tech)


if __name__ == "__main__":
    main()
