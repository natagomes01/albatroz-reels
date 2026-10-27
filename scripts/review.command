#!/bin/sh
# macOS. Double-click (or `scripts/review.command [job]`): starts the review page and opens it.
# On Windows use scripts\review.cmd.
# With no job it takes the most recently changed folder in jobs/. If the page is already
# running, it only opens the browser.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1
job="${1:-$(ls -t jobs | grep -v '^_' | head -1)}"
if lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
  open "http://127.0.0.1:8765"
  exit 0
fi
echo "Review page for $job (close this window or press Ctrl+C to stop it)"
exec uv run shorts review "$job" --port 8765
