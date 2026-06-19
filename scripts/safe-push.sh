#!/usr/bin/env bash
# safe-push — the only sanctioned way to push.
#
# Runs the full quality gate, rebases onto the remote (to catch breakage another
# session pushed before yours), re-runs the gate, and only then pushes. Refuses
# to push a red branch and never masks an exit code.
#
# Usage:  scripts/safe-push.sh [--allow-rebased-red]
#   --allow-rebased-red : escape hatch for coordinated, purely-inherited
#                         breakage (post-rebase failure that is not yours).
set -euo pipefail

BRANCH="claude/vigilant-wozniak-oueczq"
ALLOW_REBASED_RED="${1:-}"

cd "$(git rev-parse --show-toplevel)"

current="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$current" != "$BRANCH" ]]; then
  echo "✗ on '$current' but the only push target is '$BRANCH'. Aborting." >&2
  exit 1
fi

echo "==> Quality gate (pre-rebase)"
make check

echo "==> Fetch + rebase onto origin/$BRANCH"
git fetch origin "$BRANCH" || true
if git rev-parse --verify --quiet "origin/$BRANCH" >/dev/null; then
  git rebase "origin/$BRANCH"
fi

echo "==> Quality gate (post-rebase)"
if ! make check; then
  if [[ "$ALLOW_REBASED_RED" == "--allow-rebased-red" ]]; then
    echo "⚠ post-rebase gate failed; pushing anyway (--allow-rebased-red)." >&2
  else
    echo "✗ post-rebase gate failed — refusing to push a red branch." >&2
    exit 1
  fi
fi

echo "==> Push to $BRANCH"
git push -u origin "$BRANCH"
echo "✓ pushed $BRANCH"
