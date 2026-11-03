from src.graph.state import RAGState
from src.rag.rerank import rerank


def rerank_node(state: RAGState):
    print("rerank 진입", end="\n\n")

    documents = rerank(state["documents"], state["rewritten_question"], top_n=5)

    return {"documents": documents}
