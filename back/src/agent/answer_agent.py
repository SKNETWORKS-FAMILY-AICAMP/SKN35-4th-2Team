from langgraph.graph import END, START, StateGraph

from src.graph.node.answer.answer_node import answer_node
from src.graph.state import State


def answer_agent():
    builder = StateGraph(State)

    builder.add_node("answer_node", answer_node)
    builder.add_edge(START, "answer_node")
    builder.add_edge("answer_node", END)

    answer_graph = builder.compile()

    return answer_graph
