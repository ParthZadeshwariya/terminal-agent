from langgraph.graph import START, END, StateGraph
from .state import CoderState
from .coder_nodes import (
    explore_node,
    plan_node,
    confirm_plan_node,
    read_node,
    confirm_edit_node,
    write_node,
    summary_node,
)

def route_after_plan(state: CoderState) -> str:
    if state.get("plan_approved", False):
        return "execute"
    return "cancelled"

def route_loop(state: CoderState) -> str:
    """Keep looping until all files in the plan are processed."""
    index = state.get("current_index", 0)
    plan = state.get("plan", [])
    if index >= len(plan):
        return "done"
    return "continue"

def route_after_confirm_edit(state: CoderState) -> str:
    """
    If confirmed or it's a create, write it.
    If skipped, go back to read_node for the next file.
    """
    plan = state.get("plan", [])
    index = state.get("current_index", 0)
    if index >= len(plan):
        return "done"
    op = plan[index]
    if op["action"] == "create" or state.get("file_confirmed", False):
        return "write"
    return "skip"

# ── Build the graph ───────────────────────────────────────────────────────────

coder_graph = StateGraph(CoderState)

coder_graph.add_node("explore_node", explore_node)
coder_graph.add_node("plan_node", plan_node)
coder_graph.add_node("confirm_plan_node", confirm_plan_node)
coder_graph.add_node("read_node", read_node)
coder_graph.add_node("confirm_edit_node", confirm_edit_node)
coder_graph.add_node("write_node", write_node)
coder_graph.add_node("summary_node", summary_node)

# Linear start
coder_graph.add_edge(START, "explore_node")
coder_graph.add_edge("explore_node", "plan_node")
coder_graph.add_edge("plan_node", "confirm_plan_node")

# After plan confirmation — proceed or cancel
coder_graph.add_conditional_edges(
    "confirm_plan_node",
    route_after_plan,
    {
        "execute": "read_node",
        "cancelled": "summary_node"
    }
)

# After edit confirmation — write or skip
coder_graph.add_conditional_edges(
    "confirm_edit_node",
    route_after_confirm_edit,
    {
        "write": "write_node",
        "skip": "write_node",   # write_node handles skip via file_confirmed=False
        "done": "summary_node"
    }
)

# After write — loop back or finish
coder_graph.add_conditional_edges(
    "write_node",
    route_loop,
    {
        "continue": "read_node",
        "done": "summary_node"
    }
)

# Read always goes to confirm
coder_graph.add_edge("read_node", "confirm_edit_node")

coder_graph.add_edge("summary_node", END)

coder_app = coder_graph.compile()