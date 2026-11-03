from langgraph.graph import END, START, StateGraph

from src.const.rag_config import MAX_RETRY, RERANK_SCORE_THRESHOLD
from src.graph.node.rag.clear_documents_node import clear_documents_node
from src.graph.node.rag.context_compressor_node import context_compressor_node
from src.graph.node.rag.filter_documents_by_score_node import (
    filter_documents_by_score_node,
)
from src.graph.node.rag.multi_query_node import multi_query_node
from src.graph.node.rag.query_rewrite_node import query_rewrite_node
from src.graph.node.rag.rerank_node import rerank_node
from src.graph.node.rag.retriever_node import retriever_node
from src.graph.node.rag.retry_counter_node import retry_counter_node
from src.graph.node.rag.rrf_node import rrf_node
from src.graph.state import RAGState, State


def route_after_rerank(state: RAGState) -> str:
    print("route_after_rerank 진입", end="\n\n")

    documents = state.get("documents", [])
    retry_count = state.get("retry_count", 0)

    print("retry_count:", retry_count, end="\n\n")

    scores = [
        doc.metadata["rerank_score"]
        for doc in documents
        if "rerank_score" in doc.metadata
    ]

    print("scores:", scores, end="\n\n")

    top_score = max(scores) if scores else None

    if top_score is not None and top_score >= RERANK_SCORE_THRESHOLD:
        result = "compress"

    elif retry_count < MAX_RETRY:
        result = "retry"

    else:
        result = "give_up"

    print("result:", result, end="\n\n")

    return result


def rag_agent():
    builder = StateGraph(RAGState)

    builder.add_node("query_rewrite", query_rewrite_node)
    builder.add_node("multi_query", multi_query_node)
    builder.add_node("retriever", retriever_node)
    builder.add_node("rrf", rrf_node)
    builder.add_node("rerank", rerank_node)
    builder.add_node("retry_counter", retry_counter_node)
    builder.add_node("filter_documents_by_score", filter_documents_by_score_node)
    builder.add_node("context_compressor", context_compressor_node)
    builder.add_node("clear_documents", clear_documents_node)

    builder.add_edge(START, "query_rewrite")
    builder.add_edge("query_rewrite", "multi_query")
    builder.add_edge("multi_query", "retriever")
    builder.add_edge("retriever", "rrf")
    builder.add_edge("rrf", "rerank")

    builder.add_conditional_edges(
        "rerank",
        route_after_rerank,
        {
            "compress": "filter_documents_by_score",
            "retry": "retry_counter",
            "give_up": "clear_documents",
        },
    )
    builder.add_edge("filter_documents_by_score", "context_compressor")
    builder.add_edge("clear_documents", END)
    builder.add_edge("retry_counter", "query_rewrite")

    builder.add_edge("context_compressor", END)

    return builder.compile()


def rag_node(state: State):
    rag_graph = rag_agent()

    rag_result = rag_graph.invoke(
        {
            "messages": state["messages"],
            "original_question": state["original_question"],
            "retry_count": 0,
        },
    )

    return {
        "retrieved_docs": rag_result.get("documents", []),
        "completed_routes": state.get("completed_routes", []) + ["rag"],
    }
