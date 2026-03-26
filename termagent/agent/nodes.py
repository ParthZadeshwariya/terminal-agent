# from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq

from .state import AgentState
from pydantic import BaseModel, Field
from typing import Literal, Optional

from langchain_core.messages.human import HumanMessage
from langchain_core.messages.system import SystemMessage

import subprocess

import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from dotenv import load_dotenv
load_dotenv()

_confirm_fn = None  # Pluggable callback for UI to override confirm_command

# OLLAMA_MODEL = ""

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

class EmailOutput(BaseModel):
    recipient: str = Field(..., description="The recipent of the email")
    subject: str = Field(..., description="The subject of the email")
    body: str = Field(..., description="The body of the email")
    attachment: Optional[list[str]] = Field(None, description="The attachment of the email")

class CommandOutput(BaseModel):
    intent: Literal["command", "chat", "email"] = Field(..., description="Whether the user request is to execute a command, send an email or just a casual chat")
    cmd: str = Field("", description="The PowerShell command to execute, if intent is 'command'")
    response: str = Field("", description="The response to return to the user, if intent is 'chat'")
    email: Optional[EmailOutput] = Field(None, description="The email to send, if intent is 'email'")

def generate_command(state: AgentState) -> str:

    messages = [
    SystemMessage(content="""
        You are Termagent, a Windows PowerShell assistant that can either generate commands or answer questions.

        First, classify the user's intent:
        - "command": user wants to perform a system operation
        - "chat": user is asking a question or having a conversation
        - "email": user wants to send an email

        RULES FOR COMMANDS:
        - Use simple built-in PowerShell cmdlets only
        - Never use Add-Type, .NET assemblies, cmd.exe style commands
        - No explanations, no markdown, no backticks
        - If the intent is "chat", return an empty string for cmd and provide the answer in response
        - If the intent is "command", provide the PowerShell command in cmd and leave response empty
        - If the intent is "email", populate the email field with recipient, subject, body, and attachment (if any). 
            Add a disclaimer at the end of the body that the email is sent by 'Termagent'. Leave cmd and response empty.  
        - When composing email bodies, sign off with the user's actual name provided in "User's name", never use placeholders like [your name]. 
        - Keep the mail structure well formatted.
        
        PREFERRED CMDLETS:
        - Files/Folders: New-Item, Remove-Item, Copy-Item, Move-Item, Rename-Item, Get-ChildItem
        - Read/Write: Set-Content, Get-Content, Add-Content
        - Info: Get-Location, Get-Process, Get-Service, ipconfig, whoami
        
        EXAMPLES:
        User: create a folder named project
        intent: command
        cmd: New-Item -ItemType Directory -Name "project"
        response: ""

        User: write "hello world" to notes.txt
        intent: command
        cmd: Set-Content -Path "notes.txt" -Value "hello world"
        response: ""

        User: what are AI agents?
        intent: chat
        cmd: ""
        response: AI agents are autonomous systems that perceive their environment and take actions to achieve goals.
   
        User: create a file called "readme.txt" and write "hello world" in it 
        intent: command  
        cmd: New-Item -ItemType File -Name "readme.txt" -Force; Set-Content -Path "readme.txt" -Value "hello world"
        response: ""
                  
        User: send report.pdf to john@gmail.com
        intent: email
        cmd: ""
        response: ""
        email: {
            "recipient": "john@gmail.com",
            "subject": "Report",
            "body": "Please find the attached report.",
            "attachment": "report.pdf"
        }
        """),
    HumanMessage(content=f"Current working directory: {state['cwd']}\nUser's name: {state.get('user_name', 'User')}\nUser request: {state['text']}")
    ]
    llm = ChatGroq(model="llama-3.3-70b-versatile")
    # llm = ChatOllama(model=OLLAMA_MODEL)
    model = llm.with_structured_output(CommandOutput)

    response = model.invoke(messages)

    print(f"DEBUG response: {response}")
    return {
        "cmd": response.cmd,
        "intent": response.intent,
        "response": response.response,
        "email": response.email.model_dump() if response.email else None
    }

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

    llm = ChatGroq(model="llama-3.3-70b-versatile")
    # llm = ChatOllama(model=OLLAMA_MODEL)
    model = llm.with_structured_output(safety_check)

    response = model.invoke(messages)

    cmd_lower = cmd.lower()
    if any(r in cmd_lower for r in BLACKLIST) or response.is_risky:        
        return {"is_risky": True}
    else:
        return {"is_risky": False}  


def confirm_command(state: AgentState) -> AgentState:
    if _confirm_fn is not None:
        return _confirm_fn(state)
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
            ["powershell", "-Command", f"{state['cmd']}; Get-Location | Select-Object -ExpandProperty Path"],
            capture_output=True,
            text=True,
            cwd=state['cwd']
        )

        if result.returncode == 0:
            lines = result.stdout.strip().splitlines()
            new_cwd = lines[-1].strip() if lines else state['cwd']
            output = "\n".join(lines[:-1]) if len(lines) > 1 else "Command executed successfully."
            return {"result": output, "cwd": new_cwd}        
        else:
            return {"result": f"Error: {result.stderr}", "cwd": state['cwd']}
    else:
        return {"result": "Command cancelled by user.", "cwd": state['cwd']}


def email_node(state: AgentState) -> AgentState:
    email_data = state['email']
    
    if not email_data:
        return {"result": "No email data found."}

    sender = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")

    if not sender or not password:
        return {"result": "EMAIL_SETUP_REQUIRED"}

    try:
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = email_data['recipient']
        msg['Subject'] = email_data['subject']
        msg.attach(MIMEText(email_data['body'], 'plain'))

        # Attach file if provided
        if email_data.get('attachment'):
            for file in email_data['attachment']:
                attachment_path = os.path.join(state['cwd'], file)
                with open(attachment_path, 'rb') as f:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename={os.path.basename(attachment_path)}'
                )
                msg.attach(part)

        # Send via Gmail SMTP
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender, password)
            server.sendmail(sender, email_data['recipient'], msg.as_string())

        return {"result": f"Email sent to {email_data['recipient']} successfully."}

    except FileNotFoundError:
        return {"result": f"Error: Attachment file '{email_data['attachment']}' not found in {state['cwd']}"}
    except smtplib.SMTPAuthenticationError:
        return {"result": "Error: Email authentication failed. Check your EMAIL_ADDRESS and EMAIL_PASSWORD in .env"}
    except Exception as e:
        return {"result": f"Error sending email: {str(e)}"}
    

# Keywords that indicate user wants to send an email
EMAIL_KEYWORDS = [
    "send email", "send an email", "send a email",
    "send mail", "send a mail", "send an mail",
    "email to", "mail to", "mail", "email", "e-mail", "e-mail to",
    "compose email", "compose a mail", "compose an email",
    "write email", "write a mail", "write an email",
    "draft email", "draft a mail", "draft an email",
]

def pre_check(state: AgentState) -> AgentState:
    """Check if the user is requesting email functionality before invoking the LLM.
    If email keywords are detected and email is not enabled, short-circuit immediately.
    """
    text_lower = state["text"].lower()
    is_email_request = any(kw in text_lower for kw in EMAIL_KEYWORDS)

    if is_email_request and not state.get("email_enabled", False):
        return {"result": "EMAIL_SETUP_REQUIRED", "early_exit": True}

    return {"early_exit": False}