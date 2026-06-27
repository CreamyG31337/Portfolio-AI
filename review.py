import re

def parse_patch(file_path):
    with open(file_path, "r") as f:
        content = f.read()

    commit_sha = re.search(r"commit\s+([0-9a-f]{40})", content).group(1)
    message = []

    lines = content.split('\n')
    idx = 0
    while not lines[idx].startswith("diff --git"):
        message.append(lines[idx])
        idx += 1

    return {
        "sha": commit_sha,
        "message": "\n".join(message),
    }

patches = ["diff_20578839.patch", "diff_356b7fc5.patch", "diff_99fd59b5.patch", "diff_bfa11af0.patch", "diff_d156395c.patch"]
for patch in patches:
    print(parse_patch(patch)['sha'])
