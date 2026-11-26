# Agent Relay

Pass unfinished work between Claude Code and Codex on the same machine. The receiving agent can use a saved handoff or recover a selected local transcript if the sending agent has already stopped. Git and Orca are optional.

## Install

Requires Python 3.10+ and Claude Code or Codex. To install in both agents with the Skills CLI:

```sh
npx skills add sim0417/agent-relay --skill agent-relay -g -a claude-code -a codex
```

Alternatively, clone this repository and link its `skills/agent-relay` directory into `~/.agents/skills/agent-relay` for Codex and `~/.claude/skills/agent-relay` for Claude Code. Start a new chat after installation. To update a linked installation, pull changes in your clone.

## Use

- Claude Code input: `/agent-relay Hand this task off to Codex.`
- Codex input: `$agent-relay Receive the handoff for this folder.`
- After a usage limit: `$agent-relay Continue the Claude Code session for this folder.`
- Return trip with Orca: ask for a handoff to the original chat in the same workspace.

The local handoff store defaults to `~/.local/state/agent-relay`. It is scoped by workspace path. Keep both agents in the same directory, or pass the same workspace path explicitly. Recovery supports the local Claude Code and Codex JSONL formats used by the scripts, subject to session availability and client format changes. Set a custom reader home with `--home` if a client uses a separate profile.

The session picker borrows the idea of stable session selection from [claude-session-handoff](https://github.com/fvhreimert/claude-session-handoff). The resume procedure was informed by [agent-session-resume](https://github.com/hacktivist123/agent-session-resume).
