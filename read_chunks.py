import sys

def read_file_in_chunks(filepath, lines_per_chunk=20):
    with open(filepath, 'r') as f:
        lines = f.readlines()

    for i in range(0, len(lines), lines_per_chunk):
        chunk = "".join(lines[i:i+lines_per_chunk])
        print(f"--- CHUNK {i//lines_per_chunk + 1} ({i+1}-{min(i+lines_per_chunk, len(lines))}) ---")
        print(chunk)

read_file_in_chunks('/tmp/target_commit.diff', 40)
