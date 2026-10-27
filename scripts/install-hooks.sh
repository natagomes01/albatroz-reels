#!/bin/sh
# Point git at the repo hooks (pre-commit media guard). Run once per clone.
git -C "$(dirname "$0")/.." config core.hooksPath scripts/hooks
echo "hooks installed: core.hooksPath=scripts/hooks"
