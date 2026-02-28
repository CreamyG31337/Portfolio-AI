import subprocess
import os

commits_output = subprocess.check_output(['git', 'log', '--since="12 hours ago"', '--oneline']).decode('utf-8')

print("## Commits in the last 12 hours\n")
print(commits_output)

commits = [line.split()[0] for line in commits_output.strip().split('\n')]
for commit in commits:
    print(f"\n### Commit {commit}")
    diff_stat = subprocess.check_output(['git', 'show', '--stat', commit]).decode('utf-8')
    print("```")
    print(diff_stat[:1000])
    print("...")
    print("```")
