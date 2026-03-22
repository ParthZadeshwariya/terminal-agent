from typing import TypedDict, Literal, Optional

class AgentState(TypedDict):
    text: str
    cwd: str
    cmd: str
    is_risky: bool
    confirmation: Optional[Literal["yes", "no"]]
    intent: Optional[Literal["command", "chat", "email"]]
    response: Optional[str]
    result: Optional[str]
    email: Optional[dict]
    user_name: Optional[str]
    email_enabled: Optional[bool]
    early_exit: Optional[bool]