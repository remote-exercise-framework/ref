#!/usr/bin/env bash
#
# Install git hooks for this repository.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

echo "Installing git hooks..."
git config core.hooksPath hooks

echo "Git hooks installed successfully."
echo "Installed hooks:"
echo "  - pre-commit: Runs linting checks before each commit"
echo "  - pre-push: Verifies submodule commits exist on remotes, prevents dev/main from diverging"
