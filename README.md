# Codex Skills

Custom Codex skills by Elliot Shohet.

## Skills

| Skill | Purpose |
| --- | --- |
| [task-cost](skills/task-cost/SKILL.md) | Report recorded Codex usage and estimated credits by task, model, and linked subagent. |

## Install task-cost

Clone this repository, then copy `skills/task-cost` into your Codex skills directory, usually `~/.codex/skills/task-cost`. If you set `CODEX_HOME`, use `$CODEX_HOME/skills/task-cost` instead. Back up an existing copy before replacing it.

In a Codex session where the skill is available, ask:

```text
$task-cost Show the cost of this thread by task.
```

The helpers use Python 3's standard library and read local Codex session metadata. Automatic session resolution currently supports the `state_5.sqlite` index; explicit rollout paths can be supplied when that index is unavailable. Reports distinguish estimates from actual billed charges and disclose incomplete usage coverage. The bundled rate card is dated; consult its official source for current rates.

## Development

Run the synthetic tests without reading your own session history:

```sh
python3 -m unittest discover -s skills/task-cost/scripts -p 'test_*.py' -v
```

Keep each skill under `skills/<name>/` with its `SKILL.md` and required supporting files. Do not commit session logs, usage reports, credentials, or local databases.
