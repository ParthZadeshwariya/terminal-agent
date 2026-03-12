from typing import TypedDict, Literal, Optional

class AgentState(TypedDict):

    text: str
    cwd: str
    cmd: str
    is_risky: bool
    confirmation: Optional[Literal["yes", "no"]]
    result: str

