# from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq

from .state import AgentState
from pydantic import BaseModel, Field, field_validator
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

AGENT_PERSONA = SystemMessage(content=f"""
    You are Termagent, a Windows terminal assistant.
    
    RULES:
    - Be concise and direct. No fluff.
    - Address the user by name if known.
    - For greetings or small talk, respond briefly and naturally.
    - Never invent system data, file contents, email counts, or any information
      you were not explicitly given. If you don't know something, say so.
    - Never fabricate actions that aren't in history.

    IMPORTANT NOTE:
    - When history shows an action was completed, you may reference it accurately.
""")

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
    recipient: str = Field(..., description="The recipient of the email")
    subject: str = Field(..., description="The subject of the email")
    body: str = Field(..., description="The body of the email")
    attachment: list[str] = Field(default_factory=list, description="Always a list of filenames. For a single attachment use a one-element list. Use empty list if no attachments.")

    @field_validator("attachment", mode="before")
    @classmethod
    def coerce_to_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v

class CommandOutput(BaseModel):
    cmd: str = Field(..., description="The PowerShell command to execute")

class IntentOutput(BaseModel):
    intent: Literal["command", "chat", "email"] = Field(..., description="The user's intent")

def classify_intent(state: AgentState) -> AgentState:
    messages = [
        SystemMessage(content="""
            Classify the user's intent into exactly one category:
            - "command": wants to perform a file/system operation RIGHT NOW
            - "email": wants to SEND a new email RIGHT NOW
            - "chat": question, conversation, follow-up, or anything else

            CRITICAL RULES:
            - If the user is asking WHETHER something was done, that is "chat"
            - If the user is asking ABOUT a past action, that is "chat"
            - Only classify as "email" if the user is explicitly requesting
              a NEW email to be sent, e.g. "send", "write", "compose", "draft"
            - Questions like "did you...", "have you...", "was the email sent..."
              are ALWAYS "chat"

            EXAMPLES:
            "send an email to john@example.com" → email
            "did you send the email to john?" → chat
            "was the email sent?" → chat
            "have you mailed him?" → chat
            "email him again" → email
            "list files in this folder" → command
            "did you delete that file?" → chat
        """),
        *state.get("messages", [])[-3:],
        HumanMessage(content=state["text"])
    ]
    llm = ChatGroq(model="llama-3.3-70b-versatile")
    model = llm.with_structured_output(IntentOutput)
    response = model.invoke(messages)
    return {"intent": response.intent}

def generate_email(state: AgentState) -> AgentState:
    messages = [
        AGENT_PERSONA,
        SystemMessage(content="""
            You are an expert email composer. Generate a professional email based on the user's request.

            RULES:
            - Use a proper greeting, clear body paragraphs, and a sign-off.
            - Sign off using the name provided in "User's name". Never use placeholders like [Your Name].
            - After the sign-off, add a new line: "Sent via Termagent."
            - If an attachment is mentioned, populate the attachment field with the filename.
            - Keep the tone professional unless the user specifies otherwise.
        """),
        HumanMessage(content=f"User's name: {state.get('user_name', 'User')}\nUser request: {state['text']}")
    ]
    llm = ChatGroq(model="llama-3.3-70b-versatile")
    model = llm.with_structured_output(EmailOutput)
    response = model.invoke(messages)
    return {
        "email": response.model_dump() if response else None
    }

def generate_command(state: AgentState) -> AgentState:
    messages = [
        SystemMessage(content="""
            Generate a PowerShell command for the user's request.
            
            RULES:
            - Use simple built-in PowerShell cmdlets only
            - Never use Add-Type, .NET assemblies, cmd.exe style commands
            - No explanations, no markdown, no backticks
            
            PREFERRED CMDLETS:
            - Files/Folders: New-Item, Remove-Item, Copy-Item, Move-Item, Rename-Item, Get-ChildItem
            - Read/Write: Set-Content, Get-Content, Add-Content
            - Info: Get-Location, Get-Process, Get-Service, ipconfig, whoami
            
            EXAMPLES:
            User: write "hello world" to notes.txt
            cmd: Set-Content -Path "notes.txt" -Value "hello world"

            User: create a file called "readme.txt" and write "hello world" in it
            cmd: New-Item -ItemType File -Name "readme.txt" -Force; Set-Content -Path "readme.txt" -Value "hello world"
        """),
        HumanMessage(content=f"CWD: {state['cwd']}\nRequest: {state['text']}")
    ]
    llm = ChatGroq(model="llama-3.3-70b-versatile")
    model = llm.with_structured_output(CommandOutput)
    response = model.invoke(messages)
    return {"cmd": response.cmd}
    
def chat_node(state: AgentState) -> AgentState:
    user_name = state.get('user_name', '')
    
    persona = AGENT_PERSONA
    if user_name:
        persona = SystemMessage(content=
            AGENT_PERSONA.content + f"\n\nThe user's name is {user_name}. Use it only for greetings, never in every reply."
        )
    
    messages = [
        persona,
        *state.get("messages", [])[-10:],   
        HumanMessage(content=f"User request: {state['text']}")
    ]
    llm = ChatGroq(model="llama-3.3-70b-versatile")
    response = llm.invoke(messages)
    return {"result": response.content}


def check_command(state: AgentState) -> AgentState:
    cmd = state['cmd']

    messages = [
        SystemMessage(content=f"""
                  You are a security analyst reviewing a PowerShell command for potential risks. Analyze this command and determine if it contains any potentially dangerous operations that could harm the system, compromise security, or cause data loss.     
            """),
        HumanMessage(content=f"Command to analyze: {cmd}")
    ]

    llm = ChatGroq(model="llama-3.3-70b-versatile")

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