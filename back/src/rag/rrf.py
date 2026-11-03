def reciprocal_rank_fusion(multi_query_documents, k=60, top_n=5):

    scores = {}
    results = {}

    for documents in multi_query_documents:
        for rank, document in enumerate(documents, start=1):
            source = str(document.metadata.get("source", ""))
            page = str(document.metadata.get("page", ""))
            doc_id = f"{source}_{page}"
            score = 1 / (k + rank)

            scores[doc_id] = scores.get(doc_id, 0) + score

            results[doc_id] = document

    ranked_documents = sorted(
        results.items(), key=lambda item: scores[item[0]], reverse=True
    )

    return [document for _, document in ranked_documents[:top_n]]
