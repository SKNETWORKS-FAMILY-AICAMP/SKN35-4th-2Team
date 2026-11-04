from src.graph.state import RAGState
from src.rag.query_rewrite import query_rewrite


def query_rewrite_node(state: RAGState):
    print("query_rewrite 진입", end="\n\n")

    question = (
        state.get("rewritten_question")
        if state.get("rewritten_question")
        else state.get("original_question")
    )

    retry_count = state.get("retry_count", 0)
    previous_queries = state.get("multi_questions", [])

    rewritten_question = query_rewrite(question, retry_count, previous_queries)

    print("rewritten_question : ", rewritten_question)

    return {"rewritten_question": rewritten_question}
