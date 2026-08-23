"""One-shot NVIDIA Ollama smoke test (qwen3.8 27B on the local 3090)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3.8:27b-mtp-q4_K_M"
PAYLOAD = {
    "model": MODEL,
    "prompt": "Reply with the single word pong.",
    "stream": False,
    "think": False,
    "keep_alive": "7m",
    "options": {
        "num_ctx": 65536,
        "num_predict": 16,
        "temperature": 0,
    },
}


def main() -> int:
    req = urllib.request.Request(
        URL,
        data=json.dumps(PAYLOAD).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print(f"SMOKE FAIL: {exc}", file=sys.stderr)
        return 1
    text = (body.get("response") or "").strip()
    eval_count = body.get("eval_count")
    eval_ns = body.get("eval_duration") or 0
    toks = float(eval_count) if eval_count else 0.0
    tok_s = (toks / (eval_ns / 1e9)) if eval_ns else 0.0
    print(f"model={MODEL}")
    print(f"response={text!r}")
    print(f"done_reason={body.get('done_reason')}")
    print(f"eval_count={eval_count} eval_tok_s={tok_s:.1f}")
    print(f"prompt_eval_count={body.get('prompt_eval_count')}")
    if not text:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
