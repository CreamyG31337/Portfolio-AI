#!/bin/bash
commits=$(git log --since="12 hours ago" --no-merges --format="%H")
for commit in $commits; do
    echo "========================================="
    echo "Commit: $commit"
    git show --stat $commit
    echo "-----------------------------------------"
    git diff $commit^ $commit --name-only
    echo "========================================="
done
