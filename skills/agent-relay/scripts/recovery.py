"""Discover and recover a selected local Claude Code or Codex transcript."""
import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re


@dataclass(frozen=True)
class Candidate:
    provider: str
    session: str
    path: Path
    cwd: Path
    title: str


def row_at_start(path, provider):
    # Read exactly the metadata line, including on unrelated Codex rollouts.
    with path.open("rb", buffering=0) as data:
        while line := data.readline(256 * 1024):
            if not line.endswith(b"\n"):
                # Cannot identify a session safely from a partial or oversized header.
                return {}
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError):
                return {}
            if provider == "claude" and row.get("type") in {"queue-operation", "file-history-snapshot"}:
                continue
            if provider == "codex" and row.get("type") != "session_meta":
                return {}
            return row
    return {}


def candidates(store, provider, cwd, session=None, topic=None):
    cwd = cwd.resolve()
    index = store / "session_index.jsonl"
    titles = {}
    if provider == "codex":
        if index.exists():
            for line in index.read_text().splitlines():
                try:
                    row = json.loads(line)
                    titles[row["id"]] = row.get("thread_name", "")
                except (TypeError, KeyError, ValueError):
                    continue
        paths = sorted((store / "sessions").rglob("*.jsonl"))
        paths += sorted((store / "archived_sessions").rglob("*.jsonl"))
    elif provider == "claude":
        project = re.sub(r"[^a-zA-Z0-9]", "-", str(cwd))
        paths = sorted((store / "projects" / project).glob("*.jsonl"))
    else:
        raise ValueError(provider)
    possible = []
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(store.resolve()):
            continue
        try:
            head = row_at_start(path, provider)
        except OSError:
            continue
        metadata = head.get("payload", {}) if provider == "codex" else head
        if not metadata.get("cwd") or Path(metadata["cwd"]).resolve() != cwd:
            continue
        sid = metadata.get("id" if provider == "codex" else "sessionId")
        if not sid or session and sid != session:
            continue
        title = titles.get(sid, "") or metadata.get("customTitle", "")
        possible.append(Candidate(provider, sid, path, cwd, title))
    if topic and not session:
        # A titleless session may be the intended one. Leave uncertainty visible.
        ticket = re.compile(r"(?<![\w-])" + re.escape(topic) + r"(?![\w-])", re.I)
        possible = [c for c in possible if not c.title or ticket.search(c.title)]
    return possible


def pieces(content):
    if isinstance(content, str):
        return content
    return "\n".join(x.get("text", "") for x in content
                     if isinstance(x, dict) and x.get("type") in {"text", "input_text", "output_text"})


def events(provider, row):
    payload = row.get("payload", {}) if provider == "codex" else row
    if provider == "codex" and row.get("type") != "response_item":
        return []
    if payload.get("type") == "function_call_output":
        return [("result", payload.get("output", ""))]
    if payload.get("type") == "function_call":
        return [("call", payload.get("name", ""))]
    message = payload.get("message", payload)
    role = message.get("role", row.get("type"))
    if role not in {"user", "assistant"}:
        return []
    content = message.get("content", "")
    out = []
    if isinstance(content, list):
        for part in content:
            if part.get("type") == "tool_result":
                out.append(("result", pieces(part.get("content", ""))))
            if part.get("type") == "tool_use":
                out.append(("call", part.get("name", "")))
    text = pieces(content)
    if text == "/clear" or "<command-name>/clear</command-name>" in text:
        return [("reset", "")]
    if text:
        out.append((role, text))
    return out


def recover(candidate, ack=None):
    blob = candidate.path.read_bytes()
    complete_lines = blob.splitlines(keepends=True)
    partial = bool(complete_lines and not complete_lines[-1].endswith(b"\n"))
    if partial:
        complete_lines.pop()
    complete = b"".join(complete_lines)
    start = 0
    state = "ok"
    key = [candidate.provider, str(candidate.cwd), candidate.session]
    if ack is not None:
        valid = (ack["key"] == key and ack["bytes"] <= len(complete) and
                 sha256(complete[:ack["bytes"]]).hexdigest() == ack["hash"])
        if not valid:
            return {"state": "checkpoint-mismatch", "events": [], "ack": None}
        start = ack["bytes"]
    found = []
    for line in complete[start:].splitlines():
        try:
            row = json.loads(line)
            for role, value in events(candidate.provider, row):
                if role == "reset":
                    found.clear()
                else:
                    found.append((role, value))
        except (ValueError, UnicodeError):
            state = "gap"
    return {"state": "gap" if partial else state, "events": found,
            "ack": {"key": key, "bytes": len(complete), "hash": sha256(complete).hexdigest()}
                   if state == "ok" else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["list", "read"])
    parser.add_argument("--source", required=True, choices=["claude", "codex"])
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--home", type=Path, help="Override the source client's data directory")
    parser.add_argument("--session")
    parser.add_argument("--topic")
    parser.add_argument("--checkpoint", type=Path, help="Read an explicitly selected checkpoint JSON")
    args = parser.parse_args()
    if args.operation == "read" and not args.session:
        parser.error("read requires --session")
    configured_home = os.getenv("CLAUDE_CONFIG_DIR" if args.source == "claude" else "CODEX_HOME")
    home = args.home or Path(configured_home or Path.home() / ("." + args.source))
    matches = candidates(home.expanduser(), args.source, args.workspace,
                         session=args.session, topic=args.topic)
    if args.operation == "list":
        listing = [{"session": row.session, "title": row.title, "workspace": str(row.cwd)}
                   for row in matches]
        print(json.dumps(listing, ensure_ascii=False))
        return
    if len(matches) != 1:
        parser.error("the selected session must resolve to exactly one transcript in this workspace")
    ack = json.loads(args.checkpoint.read_text(encoding="utf-8")) if args.checkpoint else None
    print(json.dumps(recover(matches[0], ack), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
