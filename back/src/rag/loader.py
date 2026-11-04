# 전처리된 Document 파일을 LangChain Document 객체로 읽는 모듈
#
# 전체 흐름 (PDF 변환 없음)
#   1. python -m src.preprocessing.mdx_to_document
#        data/raw/{tech}/**/*.mdx → data/processed/{tech}/documents.jsonl   (.mdx 정리, 1줄 = 문서 1개)
#   2. 이 파일: data/processed/{tech}/documents.jsonl → Document 리스트
#   3. splitter.split_documents → retriever.build_pinecone
#
# documents.jsonl 이 없으면 그 자리에서 전처리(1번)를 먼저 실행하고 읽는다.
#
# Document.metadata (전처리에서 만든 값 그대로)
#   technology    : langchain / langgraph / mcp
#   document_type : error / specification / tutorial / example / documentation
#   source        : data/raw/langchain/errors/INVALID_PROMPT_INPUT.mdx  (원본 .mdx, 프로젝트 루트 기준)
#   file_name     : INVALID_PROMPT_INPUT.mdx
#   title, description, source_url(문서 사이트), github_url, parent_id, format="markdown"
#
# 실행 (프로젝트 루트에서)
#   python -m src.rag.loader

import json
from pathlib import Path

from langchain_core.documents import Document

from src.const.config import (
    PROCESSED_LANGCHAIN_PATH,
    PROCESSED_LANGGRAPH_PATH,
    PROCESSED_MCP_PATH,
)

DOCUMENTS_FILE_NAME = "documents.jsonl"


def _detect_document_type(file_path: Path) -> str:
    """
    파일 경로를 기반으로 문서 유형을 간단하게 판단한다.
    (documents.jsonl 에 document_type 이 없을 때만 사용)
    """

    parts = file_path.parts

    if "errors" in parts:
        return "error"

    if "specification" in parts:
        return "specification"

    if "tutorials" in parts:
        return "tutorial"

    if "examples" in parts:
        return "example"

    if "docs" in parts:
        return "documentation"

    return "documentation"


def load_mdx_documents(
    root_dir: str,
    technology: str,
) -> list[Document]:
    """
    root_dir/documents.jsonl (전처리 결과)을 읽어
    LangChain Document 객체로 변환한다.

    Args:
        root_dir: 전처리 결과 폴더 (data/processed/{technology})
        technology: langchain / langgraph / mcp

    Returns:
        Document 리스트
    """

    root_path = Path(root_dir)

    file_path = root_path / DOCUMENTS_FILE_NAME

    if not file_path.exists():
        print(f"{file_path} 가 없어 .mdx 전처리를 먼저 실행합니다.")

        from src.preprocessing.mdx_to_document import convert_framework

        convert_framework(technology)

    if not file_path.exists():
        print(f"[건너뜀] {technology}: 문서가 없습니다. data/raw/{technology} 에 .mdx 파일이 있는지 확인하세요.")
        return []

    documents = []

    with file_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            row = json.loads(line)
            text = row.pop("text")

            metadata = row
            metadata.setdefault("technology", technology)
            metadata.setdefault("document_type", _detect_document_type(Path(metadata.get("source", ""))))
            metadata.setdefault("file_name", Path(metadata.get("source", "")).name)

            document = Document(
                page_content=text,
                metadata=metadata,
            )

            documents.append(document)

    return documents


def load_documents(technologies: list[str] | None = None):
    """technologies 를 주면 일부만 (예: ["mcp"]). 없으면 세 기술 전부."""

    data_dict = {
        "langchain": PROCESSED_LANGCHAIN_PATH,
        "langgraph": PROCESSED_LANGGRAPH_PATH,
        "mcp": PROCESSED_MCP_PATH,
    }

    documents = []

    for technology, path in data_dict.items():
        if technologies and technology not in technologies:
            continue

        loaded_documents = load_mdx_documents(
            root_dir=path,
            technology=technology,
        )

        print(f"{technology} Document 개수: {len(loaded_documents)}")

        documents.extend(loaded_documents)

    print(f"전체 Document 개수: {len(documents)}")

    return documents


if __name__ == "__main__":
    docs = load_documents()

    if docs:
        print()
        print(docs[0].metadata)
        print(docs[0].page_content[:300])
