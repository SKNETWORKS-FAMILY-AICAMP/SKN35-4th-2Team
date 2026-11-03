from src.graph.state import RAGState


def retry_counter_node(state: RAGState):
    return {"retry_count": state.get("retry_count", 0) + 1}
