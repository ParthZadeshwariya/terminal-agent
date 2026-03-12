from langchain_ollama import ChatOllama
# from langchain_groq import ChatGroq
from .state import AgentState
from pydantic import BaseModel, Field
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.system import SystemMessage
import subprocess
from dotenv import load_dotenv
load_dotenv()

class CommandOutput(BaseModel):
    cmd: str = Field(..., description="The command to execute")

def generate_command(state: AgentState) -> str:

    messages = [
    SystemMessage(content="You are a Windows PowerShell expert. Generate only PowerShell commands, never cmd.exe commands. Rules: 1) Use PowerShell cmdlets only (Remove-Item not rd/del, New-Item not md/mkdir, Get-ChildItem not dir). 2) Return only the raw command, no explanations, no markdown, no backticks. 3) Never generate harmful commands."),
    HumanMessage(content=f"Current working directory: {state['cwd']}\nUser request: {state['text']}")
]
    # llm = ChatGroq(model="llama-3.1-8b-instant")
    llm = ChatOllama(model="qwen2.5-coder:3b")
    model = llm.with_structured_output(CommandOutput)

    response = model.invoke(messages)

    return {"cmd": response.cmd}


def check_command(state: AgentState) -> AgentState:
    cmd = state['cmd']

    risky = ["rm", "del", "format", "shutdown", "restart", "regedit", "reg", "Remove-Item"]
    if any(r in cmd for r in risky):
        return {"is_risky": True}
    else:
        return {"is_risky": False}  


def confirm_command(state: AgentState) -> AgentState:
    if state['is_risky']:
        user_input = input(f"Are you sure you want to execute the command: {state['cmd']}? (yes/no): ")
        if user_input.lower() == "yes":
            return {"confirmation": "yes"}
        else:
            return {"confirmation": "no"}
    else:
        return {"confirmation": "yes"}
    

def execute_command(state: AgentState) -> AgentState:

    if state.get('confirmation', 'yes') == "yes":        
        result = subprocess.run(
            ["powershell", "-Command", state['cmd']],
            capture_output=True,
            text=True,
            cwd=state['cwd']
        )

        if result.returncode == 0:
            # returncode 0 means success
            output = result.stdout if result.stdout else "Command executed successfully."
            return {"result": output}
        else:
            # non-zero returncode means something went wrong
            return {"result": f"Error: {result.stderr}"}
    else:
        return {"result": "Command cancelled by user."}