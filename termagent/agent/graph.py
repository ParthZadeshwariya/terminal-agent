from langgraph.graph import START, END, StateGraph
from .nodes import classify_intent, generate_command, check_command, confirm_command, execute_command, chat_node, email_node, pre_check, generate_email, doc_node
from .state import AgentState 

def if_risky(state: AgentState) -> str:
    if state["is_risky"]:
        return "ask_user"
    else:
        return "execute_command"

def ask_user(state: AgentState) -> str:
    if state["confirmation"] == "yes":
        return "execute"
    else:
        return "do_not_execute"

def route_pre_check(state: AgentState) -> str:
    if state.get("early_exit", False):
        return "end"
    return "classify_intent"              

def route_intent(state: AgentState) -> str:
    if state["intent"] == "command":
        return "command"
    elif state["intent"] == "email":
        return "generate_email"
    elif state["intent"] == "document":
        return "create_document"       
    else:
        return "chat"

graph = StateGraph(AgentState)

graph.add_node("pre_check", pre_check)
graph.add_node("classify_intent", classify_intent)    
graph.add_node("doc_node", doc_node)
graph.add_node("generate_command", generate_command)
graph.add_node("generate_email", generate_email)
graph.add_node("chat_node", chat_node)
graph.add_node("email_node", email_node)
graph.add_node("check_command", check_command)
graph.add_node("confirm_command", confirm_command)
graph.add_node("execute_command", execute_command)

graph.add_edge(START, "pre_check")

graph.add_conditional_edges(
    "pre_check",
    route_pre_check,
    {
        "end": END,
        "classify_intent": "classify_intent"          
    }
)

graph.add_conditional_edges(                          
    "classify_intent",
    route_intent,
    {
        "command": "generate_command",   
        "chat": "chat_node",
        "compose_email": "generate_email",
        "create_document": "doc_node"
    }
)

graph.add_edge("generate_command", "check_command")   
graph.add_edge("chat_node", END)
graph.add_edge("generate_email", "email_node")
graph.add_edge("email_node", END)
graph.add_edge("doc_node", END)

graph.add_conditional_edges(
    "check_command",
    if_risky,
    {
        "ask_user": "confirm_command",
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