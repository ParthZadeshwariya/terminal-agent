import os
from .state import CoderState
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from typing import Literal

# Folders that are never useful to explore
IGNORE = {
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", ".idea", ".vscode"
}

def explore_node(state: CoderState) -> CoderState:
    """
    Scans the working directory and builds a readable tree.
    Ignores noise folders. Does not read file contents yet.
    """
    cwd = state["cwd"]
    lines = []

    for root, dirs, files in os.walk(cwd):
        # Prune ignored directories in-place
        dirs[:] = [d for d in dirs if d not in IGNORE]

        depth = root.replace(cwd, "").count(os.sep)
        indent = "    " * depth
        folder_name = os.path.basename(root) or cwd
        lines.append(f"{indent}{folder_name}/")

        for file in files:
            lines.append(f"{indent}    {file}")

    tree = "\n".join(lines)
    return {"directory_tree": tree}

class FileOperation(BaseModel):
    file: str = Field(..., description="Relative path to the file e.g. src/app.py")
    action: Literal["create", "edit"] = Field(..., description="Either 'create' or 'edit'")
    description: str = Field(..., description="What exactly needs to be done in this file")

class CoderPlan(BaseModel):
    operations: list[FileOperation] = Field(..., description="Ordered list of file operations")
    reasoning: str = Field(..., description="Brief explanation of the overall approach")

def plan_node(state: CoderState) -> CoderState:
    """
    Takes the task + directory tree and produces an ordered
    list of file operations. Distinguishes create vs edit.
    """
    llm = ChatGroq(model="llama-3.3-70b-versatile")
    model = llm.with_structured_output(CoderPlan)

    messages = [
        SystemMessage(content="""
            You are a senior software engineer planning implementation tasks.

            Given a user task and the current directory structure, produce an
            ordered list of file operations needed to complete the task.

            RULES:
            - If a file already exists in the directory tree, action must be "edit"
            - If a file does not exist in the directory tree, action must be "create"
            - Order operations so that foundational files come first
              (e.g. models before routes, config before app)
            - Be specific in description — it will be used by another agent to write the code
            - Never include package install steps — only file operations
            - Keep the plan minimal — only files that are strictly necessary
            - Never modify files unrelated to the task
        """),
        HumanMessage(content=f"""
            Task: {state["task"]}

            Current directory structure:
            {state["directory_tree"]}
        """)
    ]

    response = model.invoke(messages)

    plan = [op.model_dump() for op in response.operations]

    return {
        "plan": plan,
        "messages": state.get("messages", []) + [
            HumanMessage(content=f"Task: {state['task']}"),
        ]
    }

_confirm_plan_fn = None  # Pluggable callback, overridden by UI

def confirm_plan_node(state: CoderState) -> CoderState:
    """
    Shows the plan to the user and waits for y/n approval.
    Uses _confirm_plan_fn if set by the UI, otherwise falls back to CLI input.
    """
    plan = state["plan"]

    # Format plan for display
    lines = []
    for i, op in enumerate(plan, 1):
        icon = "✦" if op["action"] == "create" else "✎"
        lines.append(f"  {i}. [{icon} {op['action'].upper()}] {op['file']}")
        lines.append(f"       {op['description']}")
    
    plan_text = "\n".join(lines)

    if _confirm_plan_fn is not None:
        approved = _confirm_plan_fn(plan_text)
    else:
        # CLI fallback
        print("\nProposed plan:\n")
        print(plan_text)
        answer = input("\nProceed with this plan? (y/n): ").strip().lower()
        approved = answer == "y"

    return {
        "plan_approved": approved,
        "current_index": 0,
        "context_files": {},
        "completed": []
    }

def read_node(state: CoderState) -> CoderState:
    """
    For the current file in the plan:
    - If action is 'edit', read the file into context_files
    - If action is 'create', skip — nothing to read
    """
    plan = state["plan"]
    index = state["current_index"]

    if index >= len(plan):
        return {}  # nothing to do, loop will exit

    op = plan[index]
    filepath = os.path.join(state["cwd"], op["file"])
    context_files = state.get("context_files", {})

    if op["action"] == "edit":
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    contents = f.read()
                context_files[op["file"]] = contents
            except Exception as e:
                context_files[op["file"]] = f"Could not read file: {str(e)}"
        else:
            # Marked as edit but file doesn't exist — treat as create
            plan[index]["action"] = "create"

    return {
        "context_files": context_files,
        "plan": plan   # updated action if file was missing
    }

def _build_context_summary(state: CoderState) -> str:
    """
    Returns a formatted string of all files read so far.
    Used to give the write agent awareness of existing code.
    """
    context_files = state.get("context_files", {})
    if not context_files:
        return "No existing files read yet."

    parts = []
    for filepath, contents in context_files.items():
        parts.append(f"--- {filepath} ---\n{contents}\n")

    return "\n".join(parts)

_confirm_edit_fn = None  # Pluggable callback, overridden by UI

def confirm_edit_node(state: CoderState) -> CoderState:
    """
    If the current operation is 'edit', ask the user for confirmation.
    If it's 'create', approve automatically and move on.
    """
    plan = state["plan"]
    index = state["current_index"]

    if index >= len(plan):
        return {"file_confirmed": False}

    op = plan[index]

    # New files never need confirmation
    if op["action"] == "create":
        return {"file_confirmed": True}

    # Existing files always need confirmation
    existing_contents = state.get("context_files", {}).get(op["file"], "")

    # Trim preview to first 20 lines so it's not overwhelming
    preview_lines = existing_contents.splitlines()[:20]
    preview = "\n".join(preview_lines)
    if len(existing_contents.splitlines()) > 20:
        preview += "\n  ... (truncated)"

    edit_info = {
        "file": op["file"],
        "description": op["description"],
        "preview": preview
    }

    if _confirm_edit_fn is not None:
        confirmed = _confirm_edit_fn(edit_info)
    else:
        # CLI fallback
        print(f"\nAbout to edit: {op['file']}")
        print(f"Change: {op['description']}")
        print(f"\nCurrent contents (preview):\n{preview}\n")
        answer = input("Confirm edit? (y/n): ").strip().lower()
        confirmed = answer == "y"

    return {"file_confirmed": confirmed}


from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

def write_node(state: CoderState) -> CoderState:
    """
    Generates and writes code for the current file operation.
    - For 'create': generates a fresh file
    - For 'edit': makes targeted changes to existing content
    Skips if user did not confirm the edit.
    """
    plan = state["plan"]
    index = state["current_index"]

    if index >= len(plan):
        return {}

    op = plan[index]
    completed = state.get("completed", [])

    # If user skipped this file, move to next
    if not state.get("file_confirmed", True):
        return {
            "current_index": index + 1,
            "file_confirmed": False
        }

    existing = state.get("context_files", {}).get(op["file"], None)
    context_summary = _build_context_summary(state)

    # Build the prompt based on create vs edit
    if op["action"] == "create":
        task_prompt = f"""
            Create the file `{op["file"]}` from scratch.

            What it should do:
            {op["description"]}
        """
    else:
        task_prompt = f"""
            Edit the existing file `{op["file"]}`.

            Current contents:
            {existing}

            What to change:
            {op["description"]}

            RULES for editing:
            - Keep everything that is not mentioned in "what to change" exactly as is
            - Do not remove existing imports, functions, or logic unless explicitly required
            - Do not reformat or restructure unrelated code
            - Only add or modify what is described
        """

    messages = [
        SystemMessage(content=f"""
            You are an expert software engineer writing production quality code.

            CONTEXT:
            Overall task: {state["task"]}

            Directory structure:
            {state["directory_tree"]}

            Other files in context:
            {context_summary}

            Files completed so far: {", ".join(completed) if completed else "none"}

            RULES:
            - Output ONLY the raw file contents — no explanations, no markdown fences
            - Match the coding style and patterns visible in existing files
            - Use the same imports, frameworks, and conventions already present
            - Never add placeholder comments like "# add your code here"
            - Write complete, working code — not stubs
        """),
        HumanMessage(content=task_prompt)
    ]

    llm = ChatGroq(model="openai/gpt-oss-120b")
    response = llm.invoke(messages)
    code = response.content.strip()

    # Strip markdown fences if model adds them despite instructions
    if code.startswith("```"):
        lines = code.splitlines()
        lines = [l for l in lines if not l.startswith("```")]
        code = "\n".join(lines).strip()

    # Write to disk
    filepath = os.path.join(state["cwd"], op["file"])
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)

        # Add written file to context so subsequent files can see it
        context_files = state.get("context_files", {})
        context_files[op["file"]] = code
        completed = completed + [op["file"]]

        return {
            "context_files": context_files,
            "completed": completed,
            "current_index": index + 1,
            "file_confirmed": False  # reset for next file
        }

    except Exception as e:
        # Don't crash the whole loop — log and move on
        completed = completed + [f"{op['file']} (FAILED: {str(e)})"]
        return {
            "completed": completed,
            "current_index": index + 1,
            "file_confirmed": False
        }

def summary_node(state: CoderState) -> CoderState:
    """
    Produces a clean summary of everything that was done.
    """
    completed = state.get("completed", [])
    plan = state.get("plan", [])

    if not completed:
        return {"result": "No files were written."}

    lines = ["Done. Here's what was completed:\n"]
    for op in plan:
        file = op["file"]
        # Check if it failed
        failed = next((c for c in completed if c.startswith(f"{file} (FAILED")), None)
        if failed:
            lines.append(f"  ✗ {file} — failed")
        elif file in completed:
            icon = "✦" if op["action"] == "create" else "✎"
            lines.append(f"  {icon} [{op['action']}] {file}")
        else:
            lines.append(f"  ○ {file} — skipped")

    return {"result": "\n".join(lines)}