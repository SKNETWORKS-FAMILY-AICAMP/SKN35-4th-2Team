from src.graph.state import RAGState
from src.rag.filter_documents_by_score import filter_documents_by_score


def filter_documents_by_score_node(state: RAGState):
    print("filter_documents_by_score_node 진입", end="\n\n")

    documents = state.get("documents", [])

    print("기존 documents 문서 수", len(documents), end="\n\n")

    filtered_documents = filter_documents_by_score(documents)

    print("이후 filtered_documents 문서 수", len(filtered_documents), end="\n\n")

    return {"documents": filtered_documents}
