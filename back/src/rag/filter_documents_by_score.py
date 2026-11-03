from src.const.rag_config import RERANK_SCORE_THRESHOLD


def filter_documents_by_score(documents):
    filtered_documents = [
        doc
        for doc in documents
        if doc.metadata.get("rerank_score") is not None
        and doc.metadata["rerank_score"] >= RERANK_SCORE_THRESHOLD
    ]

    return filtered_documents
