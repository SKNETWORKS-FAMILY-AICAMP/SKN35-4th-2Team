from src.const.models import create_rerank

reranker = create_rerank()


def rerank(documents, question, top_n=5):
    if not documents:
        return []

    pairs = [(question, document.page_content) for document in documents]

    scores = reranker.predict(pairs)

    ranked_documents = sorted(
        zip(documents, scores),
        key=lambda item: float(item[1]),
        reverse=True,
    )

    results = []

    for document, score in ranked_documents[:top_n]:
        document.metadata["rerank_score"] = float(score)
        results.append(document)

    return results
