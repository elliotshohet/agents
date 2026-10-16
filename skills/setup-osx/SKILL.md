---
name: setup-osx
description: Install and reproduce the shared macOS Terminal, zsh, tmux, and developer-tool baseline on another Mac. Use for new-Mac terminal setup, matching terminals across computers, or repairing drift from this preset.
---

# Set Up macOS Terminal

Make the target Mac match the packaged terminal baseline. Use the versioned assets as the source of truth, not the machine running the agent. Do not copy live dotfiles, history, account credentials, SSH keys, Codex authentication, session data, or machine-specific paths between computers.

## Establish the target

- Identify the intended Mac and whether execution is local or remote. Do not apply locally when the user means another computer. Confirm macOS, CPU architecture, current shell, existing installations, and `ZDOTDIR` before making changes.
- Read [the baseline and verification guide](references/baseline.md). The preset includes the Midnight Bloom Terminal profile with Menlo, zsh completion/history/prompt behavior, autosuggestions, tmux with resource status, SCM Breeze, and pinned nvm, Node, and Codex versions.
- Run `python3 scripts/setup_osx.py` for a dry run. Use the skill directory's absolute path if working elsewhere. Review conflicts, symlinks, and existing custom startup behavior before applying.
- The helper targets standard `~/.zshrc` and `~/.zprofile` files. If `ZDOTDIR` points elsewhere, resolve that explicitly rather than configuring files the shell will never read.

## Install and configure

The user's request to set up or match the terminal authorizes ordinary scoped installation and configuration. Proceed without redundant approval. Preserve existing work and use the helper's backups; report any actual password or OS-interaction blocker.

1. Check Homebrew and Python 3 availability. If Homebrew is absent, use its [official installation instructions](https://docs.brew.sh/Installation), inspect the official installer before running it, and complete any required system prerequisite through supported tools. Never invent an alternative privileged install. If Python is absent, install it through Homebrew before running this helper.
2. Run `python3 scripts/setup_osx.py --apply --install-tools` on the intended Mac. The helper installs missing formulae and the pinned tools, writes managed configuration, adds startup sources, and applies only the packaged Terminal profile. Do not change Codex's global model, permission, or authentication settings.
3. If existing nvm or SCM Breeze repositories differ from the pin or contain local changes, preserve them and resolve the reported mismatch without resetting or silently replacing them. Preserve customized SCM configuration and report differences from the preset.
4. Check for earlier prompt frameworks, tmux autoattach blocks, or conflicting aliases in existing startup files. Managed blocks preserve unrelated content; resolve only identified conflicts with backups. Do not claim terminals are identical while earlier startup behavior or local overrides still change the result.
5. Ensure `/bin/zsh` is the target user's shell. If a shell change is needed, use the supported account-scoped `chsh` flow; do not change another user's shell. Terminal changes apply to new windows. Do not quit an active Terminal or kill tmux sessions to force an appearance refresh.

## Verify and compare

- Run `python3 scripts/setup_osx.py --verify`. Also check a fresh login shell and an interactive non-login shell, with `SETUP_OSX_VERIFY=1` to suppress the managed tmux autoattach behavior.
- Open a new Terminal window on the target when UI access is available. Check the profile, font, colors, prompt, completions, suggestions, tmux status bar, and split shortcuts. Distinguish visual verification from configuration read-back when UI access is unavailable.
- Compare the installed managed-file hashes and the pinned tool versions across Macs. Homebrew formula and macOS versions may differ by platform; report those differences instead of promising identical binaries or pixels across operating-system versions.
- Rerun the dry run: managed configuration should require no further edits. Do not report successful setup if installation, validation, or a required version check failed.
- Summarize what changed, verification results, retained local differences, backup locations, and whether a new Terminal window is required.

For development or review, use `--home /absolute/temporary/home --apply` to exercise file installation without touching the real account. Alternate-home mode must not install software, change Terminal preferences, or claim a real Mac has been configured. Run the packaged synthetic tests before publishing changes to this skill.
