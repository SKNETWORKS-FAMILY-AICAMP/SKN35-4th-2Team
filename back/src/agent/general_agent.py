from langgraph.graph import END, START, StateGraph

from src.graph.node.general.general_node import general_node
from src.graph.state import State


def general_agent():
    builder = StateGraph(State)

    builder.add_node("general_node", general_node)
    builder.add_edge(START, "general_node")
    builder.add_edge("general_node", END)

    general_graph = builder.compile()

    return general_graph
