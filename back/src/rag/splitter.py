# Document 를 검색용 Chunk 로 나누는 모듈
#
#   Document(문서 1개) → Document(청크 여러 개)
#
# - Markdown 문서(loader 결과): 제목 단위로 묶고, 코드 블록(```)은 중간에서 자르지 않음
#   (긴 코드 블록은 줄 단위로 나누되 조각마다 ``` 를 다시 열고 닫음)
# - 그 밖의 문서: RecursiveCharacterTextSplitter 로 문단 → 줄 → 문장 → 단어 순서로 자름
# - 청크마다 문서 제목을 맨 앞에 붙임 → 짧은 청크도 무슨 문서인지 알 수 있어 검색 정확도↑
# - 너무 짧은 청크(50자 미만)와 같은 기술 안의 중복 청크는 버림
# - 청크 metadata: 문서 metadata + chunk_index, chunk_id
#     chunk_id 예: langchain-errors-invalid_prompt_input-002  (Pinecone 벡터 ID 로 사용)
#
# 실행 (프로젝트 루트에서)
#   python -m src.rag.splitter        → data/processed/chunks.jsonl 저장 (내용 확인용)

import hashlib
import json
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.const.config import CHUNK_OVERLAP, CHUNK_SIZE, CHUNKS_PATH

MIN_CHUNK_CHARS = 50


FENCE_PREFIXES = ("```", "~~~")


def _markdown_blocks(text: str) -> list[tuple[str, str]]:
    """Markdown 을 [(종류, 내용)] 블록으로 나눔. 종류: heading / code / text
    코드 블록(```...```)은 한 덩어리로 묶어서 중간에 잘리지 않게 함."""
    blocks, buf, in_code, fence = [], [], False, ""

    def flush_text():
        if buf and "".join(buf).strip():
            blocks.append(("text", "\n".join(buf).strip()))
        buf.clear()

    code: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if in_code:
            code.append(line)
            if stripped.startswith(fence) and stripped.strip(fence[0]) == "":
                blocks.append(("code", "\n".join(code)))
                code, in_code = [], False
            continue
        if stripped.startswith(FENCE_PREFIXES):
            flush_text()
            in_code, fence, code = True, stripped[:3], [line]
            continue
        if line.startswith("#"):
            flush_text()
            blocks.append(("heading", line.strip()))
            continue
        if stripped == "":
            flush_text()
            continue
        buf.append(line)
    flush_text()
    if code:
        blocks.append(("code", "\n".join(code)))
    return blocks


def _split_long_code(code: str, chunk_size: int) -> list[str]:
    """chunk_size 보다 긴 코드 블록은 줄 단위로 나누되 조각마다 ``` 를 다시 열고 닫음."""
    lines = code.split("\n")
    opener, body = lines[0], lines[1:-1] if lines[-1].strip().startswith(FENCE_PREFIXES) else lines[1:]
    closer = opener.strip()[:3]
    pieces, cur = [], []
    for line in body:
        if cur and len("\n".join(cur)) + len(line) > chunk_size - 2 * len(opener):
            pieces.append("\n".join([opener, *cur, closer]))
            cur = []
        cur.append(line)
    if cur:
        pieces.append("\n".join([opener, *cur, closer]))
    return pieces


def split_markdown(text: str, chunk_size: int, fallback: RecursiveCharacterTextSplitter) -> list[str]:
    """제목·코드 블록 경계를 지키며 chunk_size 안으로 묶음.
    - 새 제목(##, ###)이 나오면 가능하면 새 청크 시작
    - 청크가 제목 중간에서 시작하면 현재 소제목을 맨 앞에 다시 붙여 문맥 유지"""
    chunks, cur = [], []
    latest_heading = ""          # 지금까지 나온 마지막 소제목
    start_heading = ""           # 지금 청크가 시작될 때의 소제목

    def flush():
        if cur:
            body = "\n\n".join(cur)
            if start_heading and not body.startswith("#"):
                body = f"{start_heading}\n\n{body}"
            chunks.append(body)
            cur.clear()

    def add(piece: str):
        nonlocal start_heading
        if not cur:
            start_heading = latest_heading
        cur.append(piece)

    for kind, block in _markdown_blocks(text):
        if kind == "heading":
            if cur and len("\n\n".join(cur)) > chunk_size * 0.3:
                flush()
            latest_heading = block
            add(block)
            continue

        pieces = [block]
        if len(block) > chunk_size:
            pieces = _split_long_code(block, chunk_size) if kind == "code" else fallback.split_text(block)
        for piece in pieces:
            if cur and len("\n\n".join(cur)) + len(piece) > chunk_size:
                flush()
            add(piece)
    flush()
    return chunks


def split_documents(documents):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", "。", " ", ""],
    )

    chunks = []
    seen_hashes = set()

    for document in documents:
        title = document.metadata.get("title", "")
        technology = document.metadata.get("technology", "")

        if document.metadata.get("format") == "markdown":
            parts = split_markdown(document.page_content, CHUNK_SIZE, splitter)
        else:
            parts = splitter.split_text(document.page_content)

        index = 0

        for part in parts:
            if len(part.strip()) < MIN_CHUNK_CHARS:
                continue

            # 같은 기술 문서 안에 똑같은 문단 → 한 번만
            digest = hashlib.sha256((technology + part.strip()).encode("utf-8")).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)

            text = part if not title or part.startswith(f"# {title}") else f"{title}\n{part}"

            metadata = dict(document.metadata)
            metadata["chunk_index"] = index
            metadata["chunk_id"] = f"{metadata.get('parent_id', 'doc')}-{index:03d}"

            chunks.append(Document(page_content=text, metadata=metadata))
            index += 1

    print(f"전체 Chunk 개수: {len(chunks)}  (chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})")

    return chunks


def save_chunks(chunks: list[Document], path: Path = CHUNKS_PATH) -> Path:
    """청크를 jsonl 로 저장 (한 줄 = 청크 1개). 내용 확인·평가(C 파트)용."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps({"text": c.page_content, **c.metadata}, ensure_ascii=False) + "\n")
    print(f"[splitter] 저장: {path}")
    return path


def load_chunks(path: Path = CHUNKS_PATH) -> list[Document]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} 가 없습니다. 먼저 python -m src.rag.splitter 를 실행하세요.")
    chunks = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                text = row.pop("text")
                chunks.append(Document(page_content=text, metadata=row))
    return chunks


if __name__ == "__main__":
    from src.rag.loader import load_documents

    chunks = split_documents(load_documents())
    save_chunks(chunks)

    if chunks:
        print("예시:", chunks[0].metadata["chunk_id"], "|", chunks[0].page_content[:200])
