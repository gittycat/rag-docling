#!/usr/bin/env zsh
#
# Select the AWS environment for THIS shell.
#
#   setenv prod        switch to prod
#   setenv none        clear the selection (aliases: unset, off, clear)
#   setenv             show what is currently selected
#
# REQUIRES A SHIM IN ~/.zshrc. This file must be SOURCED, not executed — an
# executed script sets its variables in a child process that then exits, leaving
# the calling shell untouched — and a shell cannot know the name `setenv` before
# something defines it. So ~/.zshrc carries a small loader that finds this file
# at the root of whatever git repo you are in and sources it:
#
#   setenv() {
#     local root script
#     root=$(git rev-parse --show-toplevel 2>/dev/null) \
#       || { print -u2 "setenv: not in a git repo"; return 1 }
#     script="$root/setenv.zsh"
#     [[ -r $script ]] || { print -u2 "setenv: no $script in $root"; return 1 }
#     source "$script" "$@"
#   }
#
# That shim is deliberately generic: it names no account, profile or project, so
# any repo adopting the ./setenv.zsh convention works with the same ~/.zshrc.
# Without it, `source ./setenv.zsh prod` from the repo root still works.
#
# Nothing else sets AWS_PROFILE: there is no .envrc and no [default] profile in
# ~/.aws/config. With no environment selected the AWS CLI fails with "Unable to
# locate credentials" and infra/lib/config.ts refuses to synthesize. That is the
# point — no selection means no command runs anywhere, rather than running
# somewhere convenient.

# Deliberately duplicated from ENVIRONMENTS in infra/lib/config.ts: a zsh
# function cannot import TypeScript. Drift is survivable because config.ts
# checks envName against the *live* credentials, so a wrong pairing here fails
# loudly at synth rather than deploying to the wrong account.
typeset -gA _SETENV_PROFILES=(
  dev     sdlc-admin
  staging sdlc-admin
  demo    demo-admin
  prod    prod-admin
)

# Hash iteration order is undefined in zsh, so keep a stable one for messages.
typeset -ga _SETENV_ORDER=(dev staging demo prod)

# Executing rather than sourcing is the one mistake this file cannot recover
# from, so say so plainly instead of appearing to succeed.
if [[ "${ZSH_EVAL_CONTEXT:-}" != *file* ]]; then
  print -u2 -r -- "setenv.zsh must be sourced, not executed — an executed script"
  print -u2 -r -- "cannot change the calling shell's environment. Use:"
  print -u2 -r -- "  setenv <${(j:|:)_SETENV_ORDER}|none>   (or: source ${0} <env>)"
  exit 1
fi

# Only prod gets a colour. Four colour-coded environments would be a legend to
# decode; one deviation from normal is something you notice without decoding.
typeset -g _SETENV_PROD_BG='#2b0a0a'

# tmux swallows OSC sequences unless they are wrapped in its passthrough form.
_setenv_osc() {
  if [[ -n "${TMUX:-}" ]]; then
    printf '\ePtmux;\e%s\e\\' "$1"
  else
    printf '%s' "$1"
  fi
}

_setenv_paint() {
  case "$1" in
    prod) _setenv_osc $'\e]11;'"${_SETENV_PROD_BG}"$'\a' ;;
    *)    _setenv_osc $'\e]111\a' ;;   # reset to the terminal's configured default
  esac
}

# Exactly one of these is ever set; starship styles them differently so prod
# stands out in the prompt as well as in the background.
_setenv_prompt() {
  unset AWS_ENV_PROD AWS_ENV_SAFE
  case "$1" in
    '')     ;;
    prod)   export AWS_ENV_PROD="$1" ;;
    *)      export AWS_ENV_SAFE="$1" ;;
  esac
}

setenv() {
  local target="${1:-}"

  if [[ -z "$target" ]]; then
    if [[ -n "${AWS_ENV:-}" ]]; then
      print -r -- "${AWS_ENV} (AWS_PROFILE=${AWS_PROFILE:-unset})"
    else
      print -r -- "no environment selected — setenv <${(j:|:)_SETENV_ORDER}|none>"
    fi
    return 0
  fi

  if [[ "$target" == (none|unset|off|clear) ]]; then
    unset AWS_ENV AWS_PROFILE
    _setenv_prompt ''
    _setenv_paint ''
    print -r -- "cleared — AWS calls will now fail until you select an environment"
    return 0
  fi

  local profile="${_SETENV_PROFILES[$target]:-}"
  if [[ -z "$profile" ]]; then
    print -u2 -r -- "setenv: unknown environment '$target'"
    print -u2 -r -- "  known: ${(j:, :)_SETENV_ORDER}, none"
    return 1
  fi

  export AWS_ENV="$target"
  export AWS_PROFILE="$profile"
  _setenv_prompt "$target"
  _setenv_paint "$target"

  # Resolve the account now rather than at the first real command: this is the
  # moment you want to learn the SSO session has expired, and seeing the account
  # id confirms the profile reaches where you think it does.
  local account
  if account=$(aws sts get-caller-identity --query Account --output text 2>/dev/null); then
    print -r -- "${target} → ${profile} (${account})"
  else
    print -u2 -r -- "${target} → ${profile} — credentials not valid; run: aws sso login --sso-session kiluna"
  fi
}

# Leaving a terminal painted prod-red after the shell exits would mislead the
# next thing that reuses the window.
_setenv_restore_bg() { [[ -n "${AWS_ENV_PROD:-}" ]] && _setenv_osc $'\e]111\a' }
add-zsh-hook zshexit _setenv_restore_bg 2>/dev/null || {
  autoload -Uz add-zsh-hook && add-zsh-hook zshexit _setenv_restore_bg
}

compdef '_values environment ${_SETENV_ORDER} none' setenv 2>/dev/null

# Sourcing with an argument selects in the same step. This is what lets the
# ~/.zshrc shim be a one-liner, and what makes `source ./setenv.zsh prod` work
# on a machine that has no shim.
[[ -n "${1:-}" ]] && setenv "$1"
