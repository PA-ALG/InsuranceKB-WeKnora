"""Claude Code headless judge sessions under the same fresh-session contract as codex exec.

A dual-v1 plan whose model starts with ``claude-`` runs ``claude -p`` in the session directory
(the working directory is the session's own copy of AGENTS.md, requests/ and sources/). The
boundary the codex sandbox gives elsewhere — read only the own directory, write only answers —
comes here from Claude Code's permission rules: ``dontAsk`` refuses every permission that is not
listed, reads are allowed only under the working directory and writes only under responses/.
There is no shell tool, and no user/project settings, MCP servers or saved sessions enter the
judge, so a later round cannot see an earlier one. The codex sandbox probe does not apply to
these sessions; answers() still rejects any change to the copied inputs.

Added 2026-11-12 because Codex quota ran out; the reviewer choice is the operator's per plan.
"""

from __future__ import annotations

from typing import Any

PREFIX = "claude-"
EFFORT = "high"
TOOLS = ("Read", "Grep", "Glob", "Write")
ALLOWED = ("Read(./**)", "Grep", "Glob", "Write(./responses/**)", "Edit(./responses/**)")


def applies(model: str) -> bool:
    return model.startswith(PREFIX)


def command(model: str, prompt: str) -> list[str]:
    return [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--effort",
        EFFORT,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "dontAsk",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--tools",
        *TOOLS,
        "--allowedTools",
        *ALLOWED,
    ]


def thread(event: Any) -> Any:
    """The session id an event announces, in either executor's event format, else None."""
    if not isinstance(event, dict):
        return None
    if event.get("type") == "thread.started":
        return event.get("thread_id")
    if event.get("type") == "system" and event.get("subtype") == "init":
        return event.get("session_id")
    return None


def finished(events: list[Any]) -> bool:
    """Exactly one final result, and it reports success without error."""
    results = [e for e in events if isinstance(e, dict) and e.get("type") == "result"]
    return (
        len(results) == 1
        and results[0].get("subtype") == "success"
        and results[0].get("is_error") is False
    )
