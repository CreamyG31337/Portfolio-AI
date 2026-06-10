#!/bin/bash
commits=$(git log --since="12 hours ago" --no-merges --format="%H")
for commit in $commits; do
    echo "========================================="
    echo "Commit: $commit"
    git show $commit
    echo "========================================="
done
