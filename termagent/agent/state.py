from typing import TypedDict, Literal, Optional
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    text: str
    messages: list[BaseMessage]
    cwd: str
    cmd: str
    is_risky: bool
    confirmation: Optional[Literal["yes", "no"]]
    intent: Optional[Literal["command", "chat", "email", "github"]]
    response: Optional[str]
    result: Optional[str]
    email: Optional[dict]
    user_name: Optional[str]
    email_enabled: Optional[bool]
    early_exit: Optional[bool]

class CoderState(TypedDict):
    # Input
    task: str
    cwd: str

    # Exploration
    directory_tree: str

    # Planning
    plan: list[dict]       # [{"file": "app.py", "action": "create", "description": "..."}]
    plan_approved: bool

    # Execution loop
    current_index: int
    context_files: dict    # {filepath: contents} of files read so far
    completed: list[str]   # files successfully written

    # Per-file confirmation
    pending_confirmation: Optional[str]   # filepath awaiting user approval
    file_confirmed: bool

    # Output
    result: str
    messages: list         # conversation history within this agent