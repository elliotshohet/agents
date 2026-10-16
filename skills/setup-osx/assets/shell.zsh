# Shared terminal baseline. Local startup files source this managed file.
# Homebrew may live at either architecture's standard prefix.
if [[ -z "$HOMEBREW_PREFIX" ]]; then
  for setup_osx_brew in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [[ -x "$setup_osx_brew" ]]; then
      eval "$("$setup_osx_brew" shellenv)"
      break
    fi
  done
  unset setup_osx_brew
fi
typeset -U path PATH
path=("$HOME/.local/bin" $path)
export PATH

export NVM_DIR="$HOME/.nvm"
if [[ -s "$NVM_DIR/nvm.sh" && ! -v functions[nvm] ]]; then
  source "$NVM_DIR/nvm.sh"
fi

[[ -o interactive ]] || return 0
autoload -Uz compinit add-zsh-hook vcs_info
if (( ! $+functions[compdef] )); then
  compinit -d "${ZDOTDIR:-$HOME}/.zcompdump"
fi
if [[ -r "$HOME/.config/setup-osx/codex.zsh" ]]; then
  source "$HOME/.config/setup-osx/codex.zsh"
fi
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Z}'
zstyle ':completion:*' list-colors 'di=34' 'ln=36' 'ex=32'
zmodload zsh/complist
HISTFILE="$HOME/.zsh_history"
HISTSIZE=20000
SAVEHIST=20000
setopt HIST_IGNORE_DUPS HIST_IGNORE_SPACE SHARE_HISTORY AUTO_CD
bindkey -e
bindkey '^[[A' history-beginning-search-backward
bindkey '^[[B' history-beginning-search-forward
zstyle ':vcs_info:*' enable git
zstyle ':vcs_info:git:*' formats ' %F{magenta}on %b%f'
zstyle ':vcs_info:git:*' actionformats ' %F{magenta}on %b (%a)%f'
add-zsh-hook -d precmd vcs_info
add-zsh-hook precmd vcs_info
setopt PROMPT_SUBST
PROMPT=$'\n%F{blue}%B%~%b%f${vcs_info_msg_0_}\n%(?.%F{green}.%F{red})❯%f '
RPROMPT=''
export CLICOLOR=1
export LSCOLORS=ExGxBxDxCxEgEdxbxgxcxd
alias ll='ls -lah'
alias la='ls -A'

if [[ -n "$HOMEBREW_PREFIX" && -r "$HOMEBREW_PREFIX/share/zsh-autosuggestions/zsh-autosuggestions.zsh" && ! -v functions[_zsh_autosuggest_start] ]]; then
  source "$HOMEBREW_PREFIX/share/zsh-autosuggestions/zsh-autosuggestions.zsh"
fi
if [[ -s "$HOME/.scm_breeze/scm_breeze.sh" && -z "$_SETUP_OSX_SCM_LOADED" ]]; then
  source "$HOME/.scm_breeze/scm_breeze.sh"
  typeset -g _SETUP_OSX_SCM_LOADED=1
fi

# Attach only real Apple Terminal sessions; never verification, SSH, or scripts.
if [[ "$SETUP_OSX_VERIFY" != 1 && -t 0 && -t 1 && "$TERM_PROGRAM" == Apple_Terminal && -z "$TMUX" && -z "$SSH_CONNECTION" && "$TERM" != dumb ]] && (( $+commands[tmux] )); then
  tmux new-session -A -s main
fi
