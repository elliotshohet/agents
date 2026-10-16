# Codex Skills

Custom Codex skills by Elliot Shohet.

## Skills

| Skill | Purpose |
| --- | --- |
| [task-cost](skills/task-cost/SKILL.md) | Report recorded Codex usage and estimated credits by task, model, and linked subagent. |
| [setup-osx](skills/setup-osx/SKILL.md) | Reproduce the shared macOS Terminal profile, zsh, tmux, and developer-tool setup across Macs. |
| [use-repo-agents](skills/use-repo-agents/SKILL.md) | Install or update the shared AGENTS.md as global or project-specific Codex instructions. |

## Shared agent instructions

[AGENTS.md](AGENTS.md) contains the shared working agreements for delegation, worktrees, model selection, verification, and communication. It is published from the reference configuration and can be synchronized across computers with `use-repo-agents`.

Copy `skills/use-repo-agents` into your Codex skills directory, then ask:

```text
$use-repo-agents Install the repository's AGENTS.md as my global Codex instructions.
```

The skill fetches a specific commit from this public repository, previews the change, backs up existing instructions, and verifies the installed copy. Global installation uses `${CODEX_HOME:-$HOME/.codex}/AGENTS.md`; project scope must be requested explicitly. Existing overrides are reported and preserved. Start a new Codex session afterward to load the installed guidance.

## Install task-cost

Clone this repository, then copy `skills/task-cost` into your Codex skills directory, usually `~/.codex/skills/task-cost`. If you set `CODEX_HOME`, use `$CODEX_HOME/skills/task-cost` instead. Back up an existing copy before replacing it.

In a Codex session where the skill is available, ask:

```text
$task-cost Show the cost of this thread by task.
```

The helpers use Python 3's standard library and read local Codex session metadata. Automatic session resolution currently supports the `state_5.sqlite` index; explicit rollout paths can be supplied when that index is unavailable. Reports distinguish estimates from actual billed charges and disclose incomplete usage coverage. The bundled rate card is dated; consult its official source for current rates.

## Install setup-osx

Copy `skills/setup-osx` into your Codex skills directory, usually `~/.codex/skills/setup-osx`, then ask:

```text
$setup-osx Set up this Mac to match the shared terminal baseline.
```

The skill packages the Midnight Bloom Terminal profile, zsh prompt/completions/history, autosuggestions, tmux shortcuts and resource bar, and pinned nvm, Node, Codex, and SCM Breeze versions. Its installer previews changes by default and backs up changed configuration when applying. It adapts Homebrew paths for Apple Silicon and Intel and reports version or configuration drift rather than claiming every OS binary is identical.

Preview without changing your terminal:

```sh
python3 skills/setup-osx/scripts/setup_osx.py
```

## Development

Run the synthetic tests without reading your own session history:

```sh
python3 -m unittest discover -s skills/task-cost/scripts -p 'test_*.py' -v
python3 -m unittest discover -s skills/setup-osx/scripts -p 'test_*.py' -v
python3 -m unittest discover -s skills/use-repo-agents/scripts -p 'test_*.py' -v
```

Keep each skill under `skills/<name>/` with its `SKILL.md` and required supporting files. Do not commit session logs, usage reports, credentials, or local databases.
