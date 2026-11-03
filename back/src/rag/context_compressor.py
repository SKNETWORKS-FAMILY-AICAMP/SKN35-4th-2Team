from langchain_core.documents import Document

from src.const.models import create_openai_model
from src.prompt.context_compressor_prompt import CONTEXT_COMPRESSOR_SYSTEM_PROMPT

model = create_openai_model()


def context_compressor(
    question: str,
    documents: list[Document],
) -> list[Document]:
    compressed_documents = []

    for document in documents:
        title = document.metadata.get("title", "제목 없음")
        source_url = document.metadata.get("source_url", "")

        document_content = (
            f"문서 제목: {title}\n"
            f"문서 출처: {source_url}\n\n"
            f"문서 본문:\n{document.page_content}"
        )

        print(f"\n압축 대상 문서: {title}")
        print(f"질문: {question}")
        print(f"원본 문서 길이: {len(document.page_content)}")

        try:
            response = model.invoke(
                [
                    {
                        "role": "system",
                        "content": CONTEXT_COMPRESSOR_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": (f"질문: {question}\n\n 문서 : {document_content}"),
                    },
                ]
            )

            content = response.content

            if not isinstance(content, str):
                content = str(content)

            content = content.strip()

            is_irrelevant = (not content) or content.startswith("관련 내용 없음")

            if is_irrelevant:
                print(f"무관 문서 제외: {title}")
                continue

            compressed_documents.append(
                Document(
                    page_content=content,
                    metadata=document.metadata.copy(),
                )
            )

        except Exception as e:
            print(f"압축 실패: {title} / {type(e).__name__}: {e}")
            compressed_documents.append(document)

    return compressed_documents
