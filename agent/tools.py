import json
import os
import subprocess
import urllib.request
from typing import Any

import needle


@needle.tool
def list_directory(path: str = ".") -> dict[str, Any]:
    """List file and folder names in a directory.

    Args:
        path: directory to inspect, relative or absolute
    """
    root = os.path.abspath(path)
    entries = []
    for name in sorted(os.listdir(root)):
        full_path = os.path.join(root, name)
        entries.append({
            "name": name,
            "path": full_path,
            "is_dir": os.path.isdir(full_path),
        })
    return {"path": root, "entries": entries}


@needle.tool
def read_file(file_path: str, start_line: int = 0, end_line: int = 200) -> dict[str, Any]:
    """Read a text file and return only a selected range of lines.

    Args:
        file_path: absolute or relative path to the file
        start_line: first line number to include, zero-indexed
        end_line: last line number to include, zero-indexed and inclusive
    """
    with open(file_path, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    start = max(0, start_line)
    stop = min(len(lines), max(start, end_line + 1))
    chunk = lines[start:stop]
    return {
        "path": os.path.abspath(file_path),
        "line_count": len(lines),
        "start_line": start,
        "end_line": stop - 1,
        "content": "".join(chunk),
    }


@needle.tool
def write_file(file_path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
    """Write text content to a file."""
    path = os.path.abspath(file_path)
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return {"path": path, "bytes_written": len(content.encode("utf-8")), "overwrite": overwrite}


@needle.tool
def search_in_files(root_path: str, query: str, file_types: str | None = None, max_matches: int = 20) -> dict[str, Any]:
    """Search text files for a query and return matches with file and line numbers.

    Args:
        root_path: folder to search under
        query: substring to match
        file_types: optional comma-separated extensions like '.py,.md,.txt'
        max_matches: maximum matches to return
    """
    root = os.path.abspath(root_path)
    allowed = set()
    if file_types:
        allowed = {ext.lower() if ext.startswith(".") else "." + ext.lower() for ext in file_types.split(",")}

    matches: list[dict[str, Any]] = []
    for dirpath, _, filenames in os.walk(root):
        for filename in sorted(filenames):
            ext = os.path.splitext(filename)[1].lower()
            if allowed and ext not in allowed:
                continue
            full_path = os.path.join(dirpath, filename)
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as handle:
                    lines = handle.readlines()
            except OSError:
                continue
            for index, line in enumerate(lines, start=1):
                if query.lower() in line.lower():
                    matches.append({"path": full_path, "line": index, "text": line.rstrip()})
                    if len(matches) >= max_matches:
                        return {"query": query, "root": root, "matches": matches}
    return {"query": query, "root": root, "matches": matches}


@needle.tool
def run_shell_command(command: str, timeout: int = 20) -> dict[str, Any]:
    """Run a shell command and return captured stdout, stderr, and exit code.

    Args:
        command: shell command to execute
        timeout: maximum time in seconds before the command is terminated
    """
    completed = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


@needle.tool
def http_get(url: str, timeout: int = 10) -> dict[str, Any]:
    """Fetch a URL and return parsed JSON if possible, otherwise the text body.

    Args:
        url: URL to GET
        timeout: timeout in seconds
    """
    req = urllib.request.Request(url, headers={"User-Agent": "needle-agent/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        content_type = response.headers.get_content_type()
        try:
            payload = json.loads(body) if content_type == "application/json" else body
        except Exception:
            payload = body
        return {
            "url": url,
            "status": getattr(response, "status", None),
            "content_type": content_type,
            "body": payload,
        }


@needle.tool
def structured_output(
    title: str,
    summary: str,
    status: str = "ok",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create a structured result object for downstream use.

    Args:
        title: short title for the result
        summary: plain-language summary
        status: final status, e.g. ok, warning, or error
        tags: optional labels associated with the result
    """
    return {
        "title": title,
        "summary": summary,
        "status": status,
        "tags": tags or [],
    }
