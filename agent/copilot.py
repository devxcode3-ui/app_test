import argparse
import json
import os
import re
from typing import List, Any, Dict

from .main import run_tool_assistant, AgentMemory
from .tools import structured_output, read_file, write_file, list_directory


class ProjectCopilot:
    def __init__(self, memory: AgentMemory | None = None):
        self.memory = memory or AgentMemory()

    def plan(self, task: str) -> List[str]:
        # Very small, heuristic planner: split on sentences/semicolons and imperative clauses
        parts = [p.strip() for p in re.split(r"[;\n]\s*|\.\s+", task) if p.strip()]
        if len(parts) <= 1:
            # try verb-driven split
            verbs = re.split(r"\band then\b|\bthen\b|\bnext\b|\bafter that\b", task, flags=re.I)
            parts = [p.strip() for p in verbs if p.strip()]
        return parts or [task]

    def execute(self, task: str, max_steps: int = 4) -> Dict[str, Any]:
        steps = self.plan(task)
        execution_results: List[Dict[str, Any]] = []
        # Heuristic: if the task asks to summarize README and save a note, run deterministic tools
        low = task.lower()
        if "summar" in low and "readme" in low and ("save" in low or "note" in low or ".txt" in low):
            # determine project root (repo root: parent of agent package)
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            read_path = os.path.join(project_root, "README.md")
            try:
                read_res = read_file(file_path=read_path, start_line=0, end_line=400)
            except Exception as e:
                read_res = {"error": str(e)}
            execution_results.append({"step": "read README", "result": read_res})

            # create a model-generated summary using the run_tool_assistant
            content = read_res.get("content", "") if isinstance(read_res, dict) else ""
            prompt = (
                "Please write a short, plain-text summary of the following README (max 5 sentences). "
                "Do not include file paths or markup — just the summary.\n\n" + content
            )
            try:
                summary_resp = run_tool_assistant(prompt, max_steps=2, memory=self.memory)
            except Exception as e:
                summary_resp = {"error": str(e)}

            # attempt to extract textual summary from the agent response
            summary_text = None
            if isinstance(summary_resp, dict):
                # common locations: 'text', 'message', 'content', or in 'results'
                for key in ("text", "message", "content", "summary"):
                    if key in summary_resp and isinstance(summary_resp[key], str) and summary_resp[key].strip():
                        summary_text = summary_resp[key].strip()
                        break
                if summary_text is None and summary_resp.get("results"):
                    try:
                        # join text-like results
                        parts = []
                        for item in summary_resp.get("results", []):
                            if isinstance(item, dict):
                                parts.append(json.dumps(item, ensure_ascii=False))
                            else:
                                parts.append(str(item))
                        summary_text = "\n".join(parts)[:2000]
                    except Exception:
                        summary_text = None
            if not summary_text:
                # fallback to first 8 non-empty lines
                summary_lines = [ln.strip() for ln in content.splitlines() if ln.strip()][:8]
                summary_text = "\n".join(summary_lines) or "(README empty or unavailable)"
            execution_results.append({"step": "summarize README (model)", "result": {"summary": summary_text, "model_resp": summary_resp}})

            # write note to file
            note_path = os.path.join(project_root, "agent_notes.txt")
            try:
                write_res = write_file(file_path=note_path, content=summary_text, overwrite=True)
            except Exception as e:
                write_res = {"error": str(e)}
            execution_results.append({"step": f"write note to {note_path}", "result": write_res})
        else:
            for i, step in enumerate(steps, start=1):
                call_prompt = step
                # If the user provided an absolute Windows path like C:\\Aarav, handle it directly
                path_match = re.search(r'([A-Za-z]:\\[^\s]+)', step)
                path = None
                if path_match:
                    path = path_match.group(1)
                else:
                    # fallback: look for ' in <path>' and validate existence
                    if " in " in step.lower():
                        candidate = step.split(" in ", 1)[1].strip().strip('"\'')
                        if os.path.exists(candidate):
                            path = candidate
                if "list" in step.lower() and path:
                    try:
                        res = list_directory(path=path)
                    except Exception as e:
                        res = {"error": str(e)}
                    execution_results.append({"step": step, "result": res})
                    # Short-circuit: we executed a deterministic tool for this explicit path.
                    # Avoid invoking the model/tool loop which may produce unrelated fallbacks.
                    title = "Project Copilot Run"
                    summary_lines = [f"Task: {task}", f"Steps executed: {len(steps)}"]
                    for r in execution_results:
                        s = r.get("result")
                        summary_lines.append(f"- {r['step']}: {s.get('path') if isinstance(s, dict) else str(s)}")
                    summary_text = "\n".join(summary_lines)
                    summary_obj = structured_output(title=title, summary=summary_text, status="ok", tags=["copilot"])
                    return {"task": task, "plan": steps, "results": execution_results, "summary": summary_obj}

                # Execute using the tool-assistant loop
                res = run_tool_assistant(call_prompt, max_steps=max_steps, memory=self.memory)
                execution_results.append({"step": step, "result": res})
        # Produce final structured summary using the helper tool
        title = "Project Copilot Run"
        summary_lines = [f"Task: {task}", f"Steps executed: {len(steps)}"]
        for r in execution_results:
            s = r.get("result")
            summary_lines.append(f"- {r['step']}: {s.get('type') if isinstance(s, dict) else str(s)}")
        summary_text = "\n".join(summary_lines)
        summary_obj = structured_output(title=title, summary=summary_text, status="ok", tags=["copilot"])
        return {"task": task, "plan": steps, "results": execution_results, "summary": summary_obj}

    def execute_verbose(self, task: str, max_steps: int = 4) -> Dict[str, Any]:
        """Run the task while printing reasoning, tool selection, tool calls, and results."""
        print(f"Task: {task}")
        steps = self.plan(task)
        print(f"Planned steps: {len(steps)}")
        results = []
        for idx, step in enumerate(steps, start=1):
            print(f"\n=== Step {idx}/{len(steps)}: {step}")
            # For README-summary deterministic flow, show deterministic actions
            low = task.lower()
            if "summar" in low and "readme" in low and ("save" in low or "note" in low or ".txt" in low):
                print("-> Deterministic read/write flow selected")
                # read
                print("-> Calling tool: read_file(...) ⏳")
                read_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "README.md")
                try:
                    read_res = read_file(file_path=read_path, start_line=0, end_line=400)
                    print(f"   ✔ read_file -> {read_res.get('path')} ({read_res.get('line_count',0)} lines)")
                except Exception as e:
                    read_res = {"error": str(e)}
                    print(f"   ❌ read_file error: {e}")

                # model summarization
                content = read_res.get("content", "") if isinstance(read_res, dict) else ""
                prompt = (
                    "Please write a short, plain-text summary of the following README (max 5 sentences). "
                    "Do not include file paths or markup — just the summary.\n\n" + content
                )
                print("-> Calling model to summarize README (run_tool_assistant) ⏳")
                summary_resp = run_tool_assistant(prompt, max_steps=2, memory=self.memory)
                print("   ✔ Model response type:", summary_resp.get("type"))
                if summary_resp.get("function_calls"):
                    print("   Suggested function calls:", summary_resp.get("function_calls"))
                # try to extract summary
                summary_text = None
                for key in ("text", "message", "content", "summary"):
                    if key in summary_resp and isinstance(summary_resp[key], str) and summary_resp[key].strip():
                        summary_text = summary_resp[key].strip()
                        break
                if not summary_text and summary_resp.get("results"):
                    summary_text = "\n".join([str(x) for x in summary_resp.get("results")])[:2000]
                if not summary_text:
                    summary_text = "(no digest from model)"
                print("   Summary (excerpt):", summary_text.splitlines()[0] if summary_text else "(empty)")

                # write note
                note_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "agent_notes.txt")
                print(f"-> Calling tool: write_file({note_path}) ⏳")
                try:
                    write_res = write_file(file_path=note_path, content=summary_text, overwrite=True)
                    print(f"   ✔ write_file -> wrote {write_res.get('bytes_written')} bytes to {write_res.get('path')}")
                except Exception as e:
                    write_res = {"error": str(e)}
                    print(f"   ❌ write_file error: {e}")

                results.append({"step": step, "read": read_res, "summary": summary_text, "write": write_res})
            else:
                # detect explicit Windows path and call list_directory directly for clarity
                path_match = re.search(r'([A-Za-z]:\\[^\s]+)', step)
                path = None
                if path_match:
                    path = path_match.group(1)
                else:
                    if " in " in step.lower():
                        candidate = step.split(" in ", 1)[1].strip().strip('"\'')
                        if os.path.exists(candidate):
                            path = candidate
                if "list" in step.lower() and path:
                    print(f"-> Calling tool: list_directory({path}) ⏳")
                    try:
                        resp = list_directory(path=path)
                        print(f"   ✔ list_directory -> {resp.get('path')} ({len(resp.get('entries',[]))} entries)")
                    except Exception as e:
                        resp = {"error": str(e)}
                        print(f"   ❌ list_directory error: {e}")
                    results.append({"step": step, "result": resp})
                    # Short-circuit: return immediately to avoid the model loop producing fallbacks.
                    title = "Project Copilot Run"
                    summary_lines = [f"Task: {task}", f"Steps executed: {len(steps)}"]
                    for r in results:
                        if r.get("summary"):
                            summary_lines.append(f"- {r['step']}: {r.get('summary')[:200]}")
                        else:
                            summary_lines.append(f"- {r['step']}: executed")
                    summary_text = "\n".join(summary_lines)
                    summary_obj = structured_output(title=title, summary=summary_text, status="ok", tags=["copilot"])
                    print("\n=== Final Summary ===")
                    print(summary_text)
                    return {"task": task, "plan": steps, "detailed_results": results, "summary": summary_obj}
                else:
                    print("-> Calling model/tool loop: run_tool_assistant ⏳")
                    resp = run_tool_assistant(step, max_steps=max_steps, memory=self.memory)
                    print("   ✔ Model response type:", resp.get("type"))
                    if resp.get("function_calls"):
                        print("   Suggested function calls:", resp.get("function_calls"))
                    print("   Executed results:", resp.get("results"))
                    results.append({"step": step, "result": resp})

        # final summary
        title = "Project Copilot Run"
        summary_lines = [f"Task: {task}", f"Steps executed: {len(steps)}"]
        for r in results:
            if r.get("summary"):
                summary_lines.append(f"- {r['step']}: {r.get('summary')[:200]}")
            else:
                summary_lines.append(f"- {r['step']}: executed")
        summary_text = "\n".join(summary_lines)
        summary_obj = structured_output(title=title, summary=summary_text, status="ok", tags=["copilot"])
        print("\n=== Final Summary ===")
        print(summary_text)
        return {"task": task, "plan": steps, "detailed_results": results, "summary": summary_obj}


def _run_cli():
    parser = argparse.ArgumentParser(description="Project Copilot: plan and execute multi-step tasks using Needle tools.")
    parser.add_argument("task", nargs="*", help="Task description to perform")
    parser.add_argument("--max-steps", type=int, default=4, help="max tool-using steps per subtask")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    parser.add_argument("--interactive", action="store_true", help="enter interactive prompt mode")
    parser.add_argument("--verbose", action="store_true", help="print detailed reasoning and tool calls")
    args = parser.parse_args()

    copilot = ProjectCopilot()

    if args.interactive:
        print("Project Copilot interactive. Type a task, or blank/CTRL-D to exit.")
        try:
            while True:
                task_text = input("copilot> ").strip()
                if not task_text:
                    break
                if args.verbose:
                    out = copilot.execute_verbose(task_text, max_steps=args.max_steps)
                    if args.pretty:
                        print(json.dumps(out, indent=2, ensure_ascii=False))
                else:
                    out = copilot.execute(task_text, max_steps=args.max_steps)
                    if args.pretty:
                        print(json.dumps(out, indent=2, ensure_ascii=False))
                    else:
                        print(json.dumps(out, ensure_ascii=False))
        except (EOFError, KeyboardInterrupt):
            print("\nExiting interactive copilot.")
    else:
        task_text = " ".join(args.task)
        if args.verbose:
            result = copilot.execute_verbose(task_text, max_steps=args.max_steps)
        else:
            result = copilot.execute(task_text, max_steps=args.max_steps)
        if args.pretty:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    _run_cli()
