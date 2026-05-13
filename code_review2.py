# TODO(PR #316): Companion scratch script from same Jules report as code_review.py—no production use; remove with that TODO when cleaned up.
import sys
import subprocess

def get_commits():
    try:
        out3 = subprocess.check_output(["git", "log", "--all", "--since=48 hours ago", "--format=%H %cd %s", "--date=iso"], text=True)
        print("Commits in last 48 hours:")
        print(out3)

    except Exception as e:
        print(e)

if __name__ == "__main__":
    get_commits()
