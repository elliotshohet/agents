# Shared terminal baseline

The preset was captured from the reference Mac on 2026-10-16. Only allowlisted appearance settings were exported to `assets/Midnight Bloom.terminal`. The asset includes Menlo font settings and ANSI/background/text/cursor colors, not shell commands, working directories, window sessions, history, account data, or credentials.

## What matches

- Apple Terminal: Midnight Bloom profile, Menlo, the same color palette, cursor style, spacing, and initial 112-column by 32-row window size.
- zsh: two-line blue directory prompt with magenta Git branch and green/red command indicator; case-insensitive completion menu; shared 20,000-entry history limits; Emacs keybindings; history prefix search on up/down; `ll` and `la` aliases; Homebrew autosuggestions.
- tmux: `main` session autoattach only for interactive, non-SSH Apple Terminal sessions with a real TTY; mouse support; 20,000-line scrollback; bottom status bar with CPU/RAM and time; prefix + `r` reloads configuration. Standard splits remain prefix + `%` (side-by-side) and prefix + `"` (top/bottom).
- Development tools: Homebrew Git, tmux, zsh-autosuggestions, ripgrep, and GitHub CLI; nvm v0.40.8; Node v24.22.0 with bundled npm; Codex CLI 0.163.0 and zsh completion; SCM Breeze at the exact commit in `assets/manifest.json`.

The reference autosuggestions version is 0.7.1 and tmux version is 3.7c. Homebrew installs supported formula versions, so those observations are drift checks, not package locks. The system zsh, macOS, hardware, Terminal rendering, existing local overrides, and Homebrew packages can differ. A shared preset gives the same managed appearance and behavior; it does not make operating systems or every installed binary identical.

## Configuration layout

The installer writes shared shell configuration to `~/.config/setup-osx/shell.zsh`, shared tmux configuration to `~/.config/setup-osx/tmux.conf`, and the status helper to `~/.local/share/tmux/resources.sh`. Startup files contain marked source blocks so unrelated settings survive. Existing files that change are backed up under `~/.local/state/setup-osx/backups/`.

Preserved local configuration can still conflict. In particular, old autoattach blocks may execute before the managed block, and other prompt frameworks may replace hooks. Inspect these and resolve only identified conflicts; a successful file copy alone is not proof of identical interactive behavior.

## Verification

Run the helper's verification mode, then test both shell startup modes without attaching tmux:

```sh
SETUP_OSX_VERIFY=1 zsh -lic 'command -v git tmux rg gh codex; nvm --version; node --version; npm --version; codex --version'
SETUP_OSX_VERIFY=1 zsh -ic 'alias ll; bindkey "^[[A"; print -r -- "$HISTSIZE/$SAVEHIST"'
shasum -a 256 ~/.config/setup-osx/shell.zsh ~/.config/setup-osx/tmux.conf ~/.local/share/tmux/resources.sh
```

Compare hashes and versions on each Mac. Check SCM Breeze's revision and configuration separately. When a live tmux server already exists, a new config will not automatically update every server option; source `~/.tmux.conf` in that server when appropriate, then inspect it. Preserve running sessions and their work.

## Upstream sources

- Homebrew installation and architecture support: https://docs.brew.sh/Installation
- nvm install/version management: https://github.com/nvm-sh/nvm
- SCM Breeze installation and default configuration: https://github.com/scmbreeze/scm_breeze
- zsh autosuggestions: https://github.com/zsh-users/zsh-autosuggestions
- tmux: https://github.com/tmux/tmux/wiki

Pinned versions change only when intentionally updating this preset. Do not resolve `latest` independently on each computer and describe the result as version-identical.
