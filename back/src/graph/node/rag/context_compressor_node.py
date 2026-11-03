from src.graph.state import RAGState
from src.rag.context_compressor import context_compressor


def context_compressor_node(state: RAGState):
    print("context_compressor 진입", end="\n\n")

    rewritten_question = state["rewritten_question"]

    if isinstance(rewritten_question, dict):
        question = rewritten_question.get("rewritten_query", "")
    else:
        question = rewritten_question

    if not isinstance(question, str):
        question = str(question)

    documents = state["documents"]

    compressed_documents = context_compressor(
        question,
        documents,
    )

    return {"documents": compressed_documents}
