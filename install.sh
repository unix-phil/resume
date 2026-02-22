#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LINK_PATH="/usr/local/bin/resume"
COMP_DIR="/usr/local/share/zsh/site-functions"

# Install binary symlink
if [ -e "$LINK_PATH" ]; then
    echo "Removing existing $LINK_PATH"
    sudo rm "$LINK_PATH"
fi
sudo ln -s "$SCRIPT_DIR/resume" "$LINK_PATH"
echo "Installed: $LINK_PATH -> $SCRIPT_DIR/resume"

# Install zsh completions
if [ -n "${ZSH_VERSION:-}" ] || [ "$(basename "$SHELL")" = "zsh" ]; then
    sudo mkdir -p "$COMP_DIR"
    sudo ln -sf "$SCRIPT_DIR/completions/_resume" "$COMP_DIR/_resume"
    echo "Installed: $COMP_DIR/_resume"
    echo "Run 'exec zsh' to reload completions."
fi
