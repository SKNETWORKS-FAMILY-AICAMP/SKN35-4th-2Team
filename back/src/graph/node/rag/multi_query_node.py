from src.graph.state import RAGState
from src.rag.multi_query import multi_query


def multi_query_node(state: RAGState):
    print("multi_query 진입", end="\n\n")

    query_list = multi_query(state["rewritten_question"])

    return {"multi_questions": query_list}
