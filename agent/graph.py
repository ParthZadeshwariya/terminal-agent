from langgraph.graph import START, END, StateGraph
from .nodes import generate_command, check_command, confirm_command, execute_command
from .state import AgentState 

def if_risky(state: AgentState) -> str:
    if state["is_risky"]:
        return "confirm_command"
    else:
        return "execute_command"


def ask_user(state: AgentState) -> str:
    if state["confirmation"] == "yes":
        return "execute"
    else:
        return "do_not_execute"


graph = StateGraph(AgentState)

graph.add_node("generate_command", generate_command)
graph.add_node("check_command", check_command)
graph.add_node("confirm_command", confirm_command)
graph.add_node("execute_command", execute_command)

graph.add_edge(START, "generate_command")
graph.add_edge("generate_command", "check_command")
graph.add_conditional_edges(
    "check_command",        
    if_risky,  
    {
        "confirm_command": "confirm_command",   
        "execute_command": "execute_command"
    }
)
graph.add_conditional_edges(
    "confirm_command", 
    ask_user, 
    {
        "execute": "execute_command",
        "do_not_execute": END
    }
)
graph.add_edge("execute_command", END)


app = graph.compile()