#!/usr/bin/env bash
# Rebase a linear stack of PR branches onto origin/main and force-push each.
#
# Usage:
#   scripts/rebase-stack.sh <branch_1> <branch_2> ... <branch_N>
#
#   branch_1 — bottom of the stack (rebases directly onto origin/main).
#   branch_K — rebases onto branch_{K-1} in the new (already-rebased) state.
#
# Call this after the current bottom PR merges into main. The script drops
# commits from each branch that correspond to the already-merged PR(s) by
# remembering each branch's old tip *before* any rebase runs, then using
# `git rebase --onto <new_base> <old_base>` so duplicate content is skipped
# cleanly even when main received the PR as a squash merge with a different
# SHA.
#
# Requires a clean working tree. Does not touch refs other than the ones
# listed on the command line.

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "usage: $0 <branch_1> [<branch_2> ...]" >&2
    echo "  branch_1 is the bottom of the stack (rebases onto origin/main)." >&2
    exit 2
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "working tree is dirty — commit or stash first" >&2
    exit 1
fi

git fetch origin

# Snapshot every branch's tip BEFORE any rebase runs. For branch N, the old
# tip is what we pass as --onto's <upstream>: the point at which branch N+1
# diverged from branch N. After we rebase branch N, its ref moves, but
# branch N+1 still has to be rebased against the *original* divergence
# point, not the new tip.
declare -A OLD_TIP
for B in "$@"; do
    if ! git rev-parse --verify --quiet "refs/heads/$B" > /dev/null; then
        echo "no such local branch: $B" >&2
        exit 1
    fi
    OLD_TIP[$B]=$(git rev-parse "$B")
done

# For the bottom of the stack, the "old base" is the merge-base with
# origin/main — i.e. the fork point, since origin/main has moved.
PREV_OLD=$(git merge-base "$1" origin/main)
PREV_NEW="origin/main"

for B in "$@"; do
    echo ""
    echo "→ $B: rebase --onto $PREV_NEW $PREV_OLD"
    git checkout "$B"
    git rebase --onto "$PREV_NEW" "$PREV_OLD"
    git push --force-with-lease origin "$B"

    PREV_OLD="${OLD_TIP[$B]}"
    PREV_NEW="$B"
done

echo ""
echo "✓ stack rebased and pushed: $*"
