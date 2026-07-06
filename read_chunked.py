import sys

def chunk_print(filename, chunk_size=40):
    with open(filename, 'r') as f:
        lines = f.readlines()

    for i in range(0, len(lines), chunk_size):
        chunk = lines[i:i+chunk_size]
        print("".join(chunk))
        print(f"--- Chunk ended at line {i+len(chunk)} ---")

chunk_print('the_diff.diff')
