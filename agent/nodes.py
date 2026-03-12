from langchain_ollama import ChatOllama
# from langchain_groq import ChatGroq
from .state import AgentState
from pydantic import BaseModel, Field
from typing import Literal
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.system import SystemMessage
import subprocess
from dotenv import load_dotenv
load_dotenv()

BLACKLIST = [
        # System Critical Paths
        "system32", "system64", "c:\\windows", "c:/windows",
        
        # Disk/Partition Operations  
        "diskpart", "format-volume", "clear-disk", "initialize-disk",
        
        # Registry
        "regedit", "reg delete", "reg add", "remove-itemproperty",
        "set-itemproperty", "new-itemproperty",

        # Security/Permissions
        "icacls", "takeown", "secedit", "set-acl",
        "disable-localuser", "remove-localuser",

        # Remote Code Execution (MOST DANGEROUS)
        "invoke-expression", "iex", "downloadstring", 
        "downloadfile", "start-bitstransfer",
        "invoke-webrequest", "curl", "wget",
        "net.webclient", "start-process http",

        # System State
        "shutdown", "restart-computer", "stop-computer",

        # Scheduled Tasks (can hide malware)
        "register-scheduledtask", "new-scheduledtask",

        # Firewall/Network config
        "netsh", "set-netfirewallrule", "disable-netfirewallrule",

        # Disable Security
        "set-mppreference", "disable-windowsoptionalfeature",
        "uninstall-windowsfeature"
    ]

class safety_check(BaseModel):
    is_risky: bool = Field(..., description="Whether the command is potentially risky")

class CommandOutput(BaseModel):
    intent: Literal["command", "chat"] = Field(..., description="Whether the user request is to execute a command or just a casual chat")
    cmd: str = Field("", description="The PowerShell command to execute, if intent is 'command'")
    response: str = Field("", description="The response to return to the user, if intent is 'chat'")

def generate_command(state: AgentState) -> str:

    messages = [
    SystemMessage(content="""
        You are a Windows PowerShell assistant that can either generate commands or answer questions.

        First, classify the user's intent:
        - "command": user wants to perform a system operation
        - "chat": user is asking a question or having a conversation

        RULES FOR COMMANDS:
        - Use simple built-in PowerShell cmdlets only
        - Never use Add-Type, .NET assemblies, cmd.exe style commands
        - No explanations, no markdown, no backticks
        - If the intent is "chat", return an empty string for cmd and provide the answer in response
        - If the intent is "command", provide the PowerShell command in cmd and leave response empty

        PREFERRED CMDLETS:
        - Files/Folders: New-Item, Remove-Item, Copy-Item, Move-Item, Rename-Item, Get-ChildItem
        - Read/Write: Set-Content, Get-Content, Add-Content
        - Info: Get-Location, Get-Process, Get-Service, ipconfig, whoami

        EXAMPLES:
        User: create a folder named project
        intent: command
        cmd: New-Item -ItemType Directory -Name "project"
        response: ""

        User: delete file hello.txt
        intent: command
        cmd: Remove-Item -Path "hello.txt"
        response: ""

        User: write "hello world" to notes.txt
        intent: command
        cmd: Set-Content -Path "notes.txt" -Value "hello world"
        response: ""

        User: what are AI agents?
        intent: chat
        cmd: ""
        response: AI agents are autonomous systems that perceive their environment and take actions to achieve goals.

        User: how are you?
        intent: chat
        cmd: ""
        response: I'm doing great! How can I help you today?
        """),
    HumanMessage(content=f"Current working directory: {state['cwd']}\nUser request: {state['text']}")
]
    # llm = ChatGroq(model="llama-3.1-8b-instant")
    llm = ChatOllama(model="qwen2.5-coder:3b")
    model = llm.with_structured_output(CommandOutput)

    response = model.invoke(messages)

    # print(f"DEBUG response: {response}")
    return {"cmd": response.cmd, "intent": response.intent, "response": response.response}

def chat_node(state: AgentState) -> AgentState:
    return {"result": state["response"]}


def check_command(state: AgentState) -> AgentState:
    cmd = state['cmd']

    messages = [
        SystemMessage(content=f"""
                  You are a security analyst reviewing a PowerShell command for potential risks. Analyze this command and determine if it contains any potentially dangerous operations that could harm the system, compromise security, or cause data loss.     
            """),
        HumanMessage(content=f"Command to analyze: {cmd}")
    ]

    llm = ChatOllama(model="qwen2.5-coder:3b")
    model = llm.with_structured_output(safety_check)

    response = model.invoke(messages)

    cmd_lower = cmd.lower()
    if any(r in cmd_lower for r in BLACKLIST) or response.is_risky:        
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