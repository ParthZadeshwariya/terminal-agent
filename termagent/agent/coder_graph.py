from langgraph.graph import START, END, StateGraph
from .state import CoderState
from .coder_nodes import coder_react_node

coder_graph = StateGraph(CoderState)
coder_graph.add_node("coder_react_node", coder_react_node)
coder_graph.add_edge(START, "coder_react_node")
coder_graph.add_edge("coder_react_node", END)

coder_app = coder_graph.compile()