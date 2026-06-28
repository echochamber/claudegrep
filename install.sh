#!/usr/bin/env bash
# install.sh — symlink `claudegrep` onto your PATH.
#
# Usage:
#   ./install.sh                      # symlink into ~/.local/bin
#   ./install.sh --prefix DIR         # symlink into DIR instead
#   ./install.sh --dry-run            # show what would happen
#   ./install.sh --force              # replace an existing regular file
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/claudegrep"

prefix="$HOME/.local/bin"
dry_run=false
force=false

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) prefix="${2:?--prefix requires a directory}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --force) force=true; shift ;;
    -h|--help)
      echo "Usage: install.sh [--prefix DIR] [--dry-run] [--force]"
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

target="$prefix/claudegrep"

if [ ! -f "$SRC" ]; then
  echo "error: $SRC not found" >&2
  exit 1
fi
chmod +x "$SRC"

if $dry_run; then
  echo "would symlink $target -> $SRC"
else
  mkdir -p "$prefix"
  if [ -e "$target" ] && [ ! -L "$target" ] && ! $force; then
    echo "SKIP  $target (existing file; use --force to replace)"
    exit 0
  fi
  ln -sf "$SRC" "$target"
  echo "linked $target -> $SRC"
fi

case ":$PATH:" in
  *":$prefix:"*) ;;
  *) echo ""; echo "Note: $prefix is not on your PATH. Add:"
     echo "  export PATH=\"$prefix:\$PATH\"" ;;
esac

if ! command -v rg >/dev/null 2>&1; then
  echo ""
  echo "Tip: install ripgrep (rg) for the fast path — https://github.com/BurntSushi/ripgrep"
fi
