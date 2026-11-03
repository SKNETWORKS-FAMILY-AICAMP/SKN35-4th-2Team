from typing import Any, NotRequired

from langchain_core.documents import Document
from langgraph.graph import MessagesState


class State(MessagesState):
    original_question: str

    image: NotRequired[Any]
    image_analysis: NotRequired[str]

    retrieved_docs: NotRequired[list]
    mcp_results: NotRequired[list]

    route: NotRequired[str]
    reason: NotRequired[str]

    completed_routes: NotRequired[list[str]]

    answer: NotRequired[str]


class RAGState(MessagesState):
    original_question: str
    rewritten_question: NotRequired[str]
    documents: NotRequired[list[Document]]
    context: NotRequired[str]
    multi_questions: NotRequired[list[str]]
    multi_questions_documents: NotRequired[list[list[Document]]]
    retry_count: NotRequired[int]


class MCPState(MessagesState):
    original_question: str
    image_analysis: NotRequired[str]
    mcp_results: NotRequired[list]

    mcp_tools: NotRequired[list[dict]]
    mcp_call: NotRequired[dict | None]
    mcp_attempts: NotRequired[int]
    mcp_failures: NotRequired[list[dict]]
    mcp_error: NotRequired[dict | None]
    mcp_outcome: NotRequired[dict | None]


class MultiModalState(MessagesState):
    original_question: str
    image: NotRequired[Any]

    images: NotRequired[list]  # 검사를 통과한 이미지 (ImageItem 목록)
    notes: NotRequired[list[str]]  # 건너뛰었거나 줄였다는 안내
    parts: NotRequired[list[dict]]  # 모델에 보낼 형태(base64)로 바꾼 이미지
    raw_text: NotRequired[str | None]  # 모델이 읽은 글. 읽지 못했으면 None

    image_analysis: NotRequired[str]
    question_with_image: NotRequired[str | None]  # 읽은 내용을 붙인 질문 (읽기에 성공한 경우에만)
