import os
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

IGNORE = {
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", ".idea", ".vscode"
}


def _make_tools(cwd: str):
    """Create the four coder tools bound to the given working directory."""

    @tool
    def explore_directory(path: str = ".") -> str:
        """Scan and return the directory tree rooted at path (relative to cwd).
        Ignores __pycache__, .git, node_modules, .venv, dist, build, etc."""
        root_path = os.path.join(cwd, path) if path != "." else cwd
        lines = []
        for dirpath, dirs, files in os.walk(root_path):
            dirs[:] = [d for d in dirs if d not in IGNORE]
            depth = dirpath.replace(root_path, "").count(os.sep)
            indent = "    " * depth
            folder_name = os.path.basename(dirpath) or root_path
            lines.append(f"{indent}{folder_name}/")
            for file in files:
                lines.append(f"{indent}    {file}")
        return "\n".join(lines) if lines else "(empty directory)"

    @tool
    def read_file(filepath: str) -> str:
        """Read and return the full contents of a file.
        filepath is relative to the project working directory."""
        abs_path = os.path.join(cwd, filepath)
        if not os.path.exists(abs_path):
            return f"Error: file not found — {filepath}"
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading {filepath}: {e}"

    @tool
    def write_file(filepath: str, contents: str) -> str:
        """Create a new file with the given contents.
        Creates any required parent directories automatically.
        filepath is relative to the project working directory.
        Use this only for NEW files — use edit_file for existing ones."""
        abs_path = os.path.join(cwd, filepath)
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(contents)
            return f"Created: {filepath}"
        except Exception as e:
            return f"Error writing {filepath}: {e}"

    @tool
    def edit_file(filepath: str, old_str: str, new_str: str) -> str:
        """Replace an exact block of text in an existing file.
        old_str must match the current file content exactly (whitespace included).
        Use this instead of write_file for files that already exist."""
        abs_path = os.path.join(cwd, filepath)
        if not os.path.exists(abs_path):
            return f"Error: file not found — {filepath}. Use write_file for new files."
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                current = f.read()
            if old_str not in current:
                return (
                    f"Error: old_str not found in {filepath}. "
                    "Call read_file first and copy the exact text to replace."
                )
            updated = current.replace(old_str, new_str, 1)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(updated)
            return f"Edited: {filepath}"
        except Exception as e:
            return f"Error editing {filepath}: {e}"

    return [explore_directory, read_file, write_file, edit_file]


SYSTEM_PROMPT = """\
You are an expert software engineer working inside a ReAct coding loop.

Your task and working directory are given below.

WORKFLOW — follow this every time:
1. Call explore_directory first to understand what already exists.
2. For any file you plan to EDIT, call read_file first so you have the exact contents.
3. Use write_file for NEW files that do not exist yet.
4. Use edit_file for EXISTING files — pass the exact old_str block and your replacement.
5. Keep iterating until the task is fully complete.
6. When done, respond with a clean summary of everything you created or changed.

RULES:
- Always call explore_directory before doing anything else.
- Always call read_file before edit_file on any existing file.
- Never overwrite existing code unrelated to the task.
- Match the existing code style, imports, and conventions you find.
- Write complete, working code — no stubs, no TODO placeholders.
- Do not explain your plan in text — just call tools and get it done.
"""


def coder_react_node(state: dict) -> dict:
    """
    Single ReAct loop node for the coder agent.
    The LLM autonomously explores, reads, writes, and edits files
    until the task is complete (max 20 iterations).
    """
    task = state["task"]
    cwd = state["cwd"]

    tools = _make_tools(cwd)
    tool_map = {t.name: t for t in tools}

    llm = ChatGroq(model="openai/gpt-oss-120b")
    llm_with_tools = llm.bind_tools(tools)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Working directory: {cwd}\n\nTask: {task}"),
    ]

    response = None
    for _ in range(20):
        response = llm_with_tools.invoke(messages)
        if not response.tool_calls:
            break
        messages.append(response)
        for tc in response.tool_calls:
            fn = tool_map.get(tc["name"])
            result = fn.invoke(tc["args"]) if fn else f"Unknown tool: {tc['name']}"
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    summary = response.content if response else "No response from model."
    return {"result": summary, "messages": messages}