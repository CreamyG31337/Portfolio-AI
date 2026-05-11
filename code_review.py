import sys
import subprocess

def get_commits():
    try:
        # Get commits from the last 12 hours (currently it's May 11, 2026, 14:51 UTC, 12 hours ago is May 11, 2026 02:51 UTC)
        # We will use git log --since="12 hours ago"
        out = subprocess.check_output(["git", "log", "--all", "--since=12 hours ago", "--format=%H %cd %s", "--date=iso"], text=True)
        print("Commits in last 12 hours:")
        print(out)

        out2 = subprocess.check_output(["git", "log", "--all", "--since=24 hours ago", "--format=%H %cd %s", "--date=iso"], text=True)
        print("Commits in last 24 hours:")
        print(out2)

    except Exception as e:
        print(e)

if __name__ == "__main__":
    get_commits()
