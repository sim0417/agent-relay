"""Store handoffs locally and scope each packet to its workspace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid


def publish(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        draft = Path(stream.name)
        stream.write(json.dumps(data, ensure_ascii=False).encode())
    try:
        os.replace(draft, path)
    finally:
        draft.unlink(missing_ok=True)


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--store", type=Path, default=Path.home() / ".local/state/agent-relay")
    cli.add_argument("--workspace", type=Path, default=Path.cwd())
    sub = cli.add_subparsers(dest="op", required=True)
    for name in ("put", "take", "ack"):
        parser = sub.add_parser(name)
        parser.add_argument("--to-agent", required=True, choices=["claude", "codex"])
        parser.add_argument("--session", help="Receiving session, when known")
        if name in ("take", "ack"):
            parser.add_argument("--offline", action="store_true", help="Read a known packet ID outside Orca")
        if name == "ack":
            parser.add_argument("--id", required=True, type=uuid.UUID)
        else:
            parser.add_argument("--task", default="")
        if name == "take":
            parser.add_argument("--id", type=uuid.UUID)
        if name == "put":
            parser.add_argument("--from-agent", required=True, choices=["claude", "codex"])
    args = cli.parse_args()
    if getattr(args, "offline", False) and not args.id:
        cli.error("--offline requires an explicit packet --id")
    cwd = str(args.workspace.resolve(strict=True))
    if not Path(cwd).is_dir():
        cli.error("--workspace must be a directory")
    shard = hashlib.sha256(os.fsencode(cwd)).hexdigest()
    folder = args.store.resolve() / shard
    if args.op == "put":
        note = sys.stdin.read().strip()
        if not note:
            cli.error("empty handoff")
        folder.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        folder.mkdir(mode=0o700, exist_ok=True)
        packet = dict(id=str(uuid.uuid4()), cwd=cwd, task=args.task,
                      sender=args.from_agent, recipient=args.to_agent,
                      session=args.session, note=note)
        publish(folder / (packet["id"] + ".json"), packet)
        print(json.dumps({"id": packet["id"]}))
        return
    packets = []
    paths = [folder / (str(args.id) + ".json")] if args.id else sorted(folder.glob("*.json"))
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        try:
            packet = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if packet["cwd"] != cwd or packet["recipient"] != args.to_agent:
            continue
        if packet["session"] and packet["session"] != args.session:
            if not (args.offline and str(args.id) == packet["id"]):
                continue
        receipt = path.with_suffix(".ack")
        if args.op == "ack":
            if packet["id"] == str(args.id):
                publish(receipt, {"id":packet["id"]})
                print(json.dumps({"ack":packet["id"]}))
                return
        elif not receipt.exists() and (not args.task or packet["task"] == args.task):
            if not args.id or str(args.id) == packet["id"]:
                packets.append(packet)
    if len(packets) == 1:
        print(json.dumps(packets[0], ensure_ascii=False))
        return
    print(json.dumps({"status":"choose" if packets else "empty",
                      "choices":[{"id":p["id"],"task":p["task"]} for p in packets]}))
    sys.exit(2 if packets else 1)


if __name__ == "__main__":
    main()
