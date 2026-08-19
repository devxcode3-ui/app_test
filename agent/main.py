import json
import os
import argparse

import needle

from .tools import (
    http_get,
    list_directory,
    read_file,
    run_shell_command,
    search_in_files,
    structured_output,
    write_file,
)

DEFAULT_SYSTEM = (
    "You are a helpful local agent. Use tools when needed. "
    "Prefer concise, structured results. "
    "Keep track of what has already been learned in memory and do not repeat work."
)

# Project root inferred dynamically (parent of the agent package)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _infer_tool_calls(query: str):
    text = query.strip()
    q = text.lower()
    if "list" in q and ("file" in q or "dir" in q or "directory" in q):
        # prefer any explicit absolute path in the query
        m = re.search(r'([A-Za-z]:\\[^\s"\']+)', query)
        path = m.group(1) if m else PROJECT_ROOT
        return [{"name": "list_directory", "arguments": {"path": path}}]
    if "search" in q and ("file" in q or "files" in q or "project" in q):
        needle_text = text.split("for", 1)[-1].strip().strip('"\'') or "needle"
        m = re.search(r'([A-Za-z]:\\[^\s"\']+)', query)
        root = m.group(1) if m else PROJECT_ROOT
        return [{"name": "search_in_files", "arguments": {"root_path": root, "query": needle_text, "max_matches": 10}}]
    if "read" in q and "file" in q:
        maybe = text.split("file", 1)[-1].strip().strip('"\'')
        default = "README.md" if "readme" in q else "README.md"
        path = maybe or default
        # if path looks absolute, use it; otherwise join with project root
        if re.match(r'^[A-Za-z]:\\', path):
            file_path = path
        else:
            file_path = os.path.join(PROJECT_ROOT, path)
        return [{"name": "read_file", "arguments": {"file_path": file_path, "start_line": 0, "end_line": 100}}]
    if "run" in q and ("command" in q or "shell" in q or "cmd" in q):
        cmd = text.split("command", 1)[-1].strip().strip('\"\'') or "dir"
        return [{"name": "run_shell_command", "arguments": {"command": cmd, "timeout": 20}}]
    return []


class AgentMemory:
    def __init__(self):
        self.items: list[dict[str, str]] = []

    def add(self, key: str, value: str):
        self.items.append({"key": key, "value": value})

    def snapshot(self) -> str:
        if not self.items:
            return "No memory recorded yet."
        lines = ["Session memory:"]
        for item in self.items:
            lines.append(f"- {item['key']}: {item['value']}")
        return "\n".join(lines)

    def clear(self):
        self.items.clear()


def build_agent(system: str | None = None, memory: AgentMemory | None = None):
    memory_context = memory.snapshot() if memory else "No memory recorded yet."
    agent_system = system or DEFAULT_SYSTEM
    if memory_context:
        agent_system = f"{agent_system}\n\n{memory_context}"
    return needle.Needle(
        tools=[
            list_directory,
            read_file,
            write_file,
            search_in_files,
            run_shell_command,
            http_get,
            structured_output,
        ],
        system=agent_system,
    )


def _execute_calls(agent, calls):
    executed = []
    for call in calls:
        name = call.get("name")
        fn = agent._functions.get(name)
        if fn is None:
            executed.append({"error": f"unknown tool: {name}"})
            continue
        try:
            args = call.get("arguments") or {}
            executed.append(fn(**args))
        except Exception as exc:  # pragma: no cover - runtime tool error path
            executed.append({"error": str(exc)})
    return executed


def run_tool_assistant(query: str, system: str | None = None, max_steps: int = 4, memory: AgentMemory | None = None):
    agent = build_agent(system, memory)
    inferred = _infer_tool_calls(query)
    response = agent.complete(query, max_new_tokens=256) if not inferred else {"type": "call", "function_calls": inferred}
    visited = []
    for _ in range(max_steps):
        calls = response.get("function_calls") or []
        if response.get("type") != "call" or not calls:
            break
        execution = _execute_calls(agent, calls)
        visited.extend(execution)
        if not execution:
            break
        response = agent.complete(json.dumps(execution, default=str), max_new_tokens=256)
    payload = {"type": response.get("type", "final") if isinstance(response, dict) else "final", "results": visited}
    if isinstance(response, dict):
        payload.update({k: v for k, v in response.items() if k != "results"})
    if memory is not None and visited:
        memory.add("last_result", json.dumps(visited, ensure_ascii=False, default=str)[:2000])
    return payload


def run_query(query: str, system: str | None = None, max_steps: int = 4, memory: AgentMemory | None = None):
    return run_tool_assistant(query, system=system, max_steps=max_steps, memory=memory)


def _run_cli():
    parser = argparse.ArgumentParser(description="Run a Needle-based local tool agent.")
    parser.add_argument("query", nargs="*", help="question or instruction for the agent")
    parser.add_argument("--system", default=None, help="override the system prompt")
    parser.add_argument("--max-steps", type=int, default=2, help="maximum tool-using turns")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args()

    memory = AgentMemory()
    memory.add("project_root", PROJECT_ROOT)
    query = " ".join(args.query) if args.query else (
        f"Use the list_directory tool with path \"{PROJECT_ROOT}\"."
    )
    response = run_query(query, system=args.system, max_steps=args.max_steps, memory=memory)
    if args.pretty:
        print(json.dumps(response, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    _run_cli()
