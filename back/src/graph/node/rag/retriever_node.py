from src.graph.state import RAGState
from src.rag.retriever import create_hybrid_retriever


def retriever_node(state: RAGState):
    print("retriever 진입", end="\n\n")

    retriever = create_hybrid_retriever(
        filters=None,
        use_query_rewrite=False,
        use_multi_query=False,
        use_rerank=False,
    )

    if state.get("multi_questions"):
        print('state["multi_questions"] : ', state["multi_questions"])
        multi_questions_documents = []

        for question in state["multi_questions"]:
            documents = retriever.invoke(question)
            multi_questions_documents.append(documents)

        return {"multi_questions_documents": multi_questions_documents}

    else:
        print('state["rewritten_question"]')
        documents = retriever.invoke(state["rewritten_question"])

        return {"documents": documents}
