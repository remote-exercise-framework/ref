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
echo "The pre-commit hook will now run linting checks before each commit."
