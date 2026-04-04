import asyncio
import os
import subprocess
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import requests
from langchain_core.tools import StructuredTool
from pydantic import create_model, Field as PydanticField
from typing import Optional as Opt
# ── Low-level async core ──────────────────────────────────────────────────────

async def _call_tool_async(tool_name: str, args: dict) -> str:
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        return "Error: GITHUB_PERSONAL_ACCESS_TOKEN not set."

    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={**os.environ, "GITHUB_PERSONAL_ACCESS_TOKEN": token}
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                texts = [
                    block.text
                    for block in result.content
                    if hasattr(block, "text")
                ]
                return "\n".join(texts) if texts else "Tool executed successfully."

    except Exception as e:
        # Print full traceback so we can see the real cause
        import traceback
        traceback.print_exc()
        return f"MCP Error: {str(e)}"
        
async def _list_tools_async() -> list:
    """Returns all tools the GitHub MCP server exposes."""
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        return []

    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={**os.environ, "GITHUB_PERSONAL_ACCESS_TOKEN": token}
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.tools
    except Exception:
        return []


# ── Public sync interface ─────────────────────────────────────────────────────
# Termagent's nodes are synchronous (LangGraph + Textual worker threads).
# asyncio.run() lets us call the async MCP client from sync code.
# This works because github_node runs inside @work(thread=True) — it has no
# existing event loop, so asyncio.run() is safe to call directly.

def call_github_tool(tool_name: str, args: dict) -> str:
    """
    Public sync entry point for all GitHub MCP tool calls.
    
    Usage in nodes.py:
        result = call_github_tool("create_release", {
            "owner": "alice",
            "repo": "my-project",
            "tag_name": "v1.0.0",
            "name": "v1.0.0",
            "body": "Release notes here"
        })
    """
    return asyncio.run(_call_tool_async(tool_name, args))


def list_github_tools() -> list:
    """
    Returns available GitHub MCP tools.
    Useful for debugging: 'what can the GitHub server actually do?'
    """
    return asyncio.run(_list_tools_async())


# ── Dynamic LangChain tool creation from MCP ─────────────────────────────────

_cached_lc_tools = None

def get_mcp_langchain_tools() -> list:
    """
    Fetch all tools from the GitHub MCP server and convert them
    to LangChain StructuredTools.  Cached after first call.

    Each returned tool, when invoked, spins up a fresh MCP session
    and calls the underlying tool — matching the existing pattern.
    """
    global _cached_lc_tools
    if _cached_lc_tools is not None:
        return _cached_lc_tools

    mcp_tools = list_github_tools()
    if not mcp_tools:
        return []

    TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    lc_tools = []
    for mt in mcp_tools:
        schema = mt.inputSchema or {}
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        # Build Pydantic fields dynamically from the JSON schema
        fields = {}
        for prop_name, prop_info in properties.items():
            py_type = TYPE_MAP.get(prop_info.get("type", "string"), str)
            desc = prop_info.get("description", "")

            if prop_name in required:
                fields[prop_name] = (py_type, PydanticField(description=desc))
            else:
                fields[prop_name] = (Opt[py_type], PydanticField(default=None, description=desc))

        ArgsModel = create_model(f"{mt.name}_args", **fields)

        # Closure needs name captured by value (default arg trick)
        def _make_fn(tool_name: str):
            def _invoke(**kwargs):
                args = {k: v for k, v in kwargs.items() if v is not None}
                return call_github_tool(tool_name, args)
            return _invoke

        lc_tools.append(
            StructuredTool(
                name=mt.name,
                description=(mt.description or mt.name)[:1024],
                func=_make_fn(mt.name),
                args_schema=ArgsModel,
            )
        )

    _cached_lc_tools = lc_tools
    return lc_tools


# ── Git helpers ───────────────────────────────────────────────────────────────
# These don't use MCP — they're plain git subprocess calls.
# Kept here because they're GitHub-workflow related and used by github_node.

def get_git_diff(cwd: str) -> str:
    try:
        # Check for any changes — staged, unstaged, or untracked
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=cwd
        )
        if not status.stdout.strip():
            return "No changes detected."

        # Get diff of tracked files
        diff = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True, text=True, cwd=cwd
        ).stdout.strip()

        # Get list of untracked files
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=cwd
        ).stdout.strip()

        if untracked:
            diff += f"\n\nNew untracked files:\n{untracked}"

        return diff if diff.strip() else f"New untracked files:\n{untracked}"

    except Exception as e:
        return f"Error getting diff: {str(e)}"


def get_git_remote_info(cwd: str) -> tuple[str, str]:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=cwd
        )
        url = result.stdout.strip()

        # HTTPS format
        if "github.com/" in url:
            path = url.split("github.com/")[-1].removesuffix(".git")  # ← fixed
            parts = path.split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]

        # SSH format
        if "github.com:" in url:
            path = url.split("github.com:")[-1].removesuffix(".git")  # ← fixed
            parts = path.split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]

        return "", ""
    except Exception:
        return "", ""

def run_git_commands(commands: list[str], cwd: str) -> tuple[bool, str]:
    """
    Runs a list of git commands sequentially.
    Stops and returns the error if any command fails.
    
    Returns (success: bool, output: str)
    """
    outputs = []
    for cmd in commands:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, cwd=cwd
        )
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            return False, f"Failed at `{cmd}`:\n{error}"
        if result.stdout.strip():
            outputs.append(result.stdout.strip())

    return True, "\n".join(outputs) if outputs else "Done."

def create_github_release(owner: str, repo: str, tag: str, title: str, notes: str) -> str:
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    response = requests.post(
        f"https://api.github.com/repos/{owner}/{repo}/releases",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"
        },
        json={
            "tag_name": tag,
            "name": title,
            "body": notes,
            "draft": False,
            "prerelease": False
        }
    )
    if response.status_code == 201:
        return f"Release created: {response.json()['html_url']}"
    else:
        return f"Failed: {response.json().get('message', 'unknown error')}"