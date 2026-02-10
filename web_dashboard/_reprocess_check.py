"""Reprocess news articles with 2+ tickers to get per-ticker sentiment.

Uses GLM-4.5-air via Z.AI (faster than 4.7, same quality for this task).
Sequential with retry on 429 + exponential backoff.
"""
import io, os, sys, time, json, logging
import requests as req_lib

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'), override=False)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s', stream=sys.stdout)
logging.getLogger('ollama_client').setLevel(logging.CRITICAL)

from glm_config import get_zhipu_api_key, ZHIPU_BASE_URL
from summary_common import get_summary_system_prompt, parse_summary_response

key = get_zhipu_api_key()
if not key:
    print("ERROR: ZHIPU_API_KEY not found.")
    sys.exit(1)

from research_repository import ResearchRepository

MODEL = "glm-4.5-air"
MAX_RETRIES = 5
BASE_DELAY = 5       # seconds between successful calls
MAX_CHARS = 6000

repo = ResearchRepository()

# Load model config
cfg_path = os.path.join(os.path.dirname(__file__), "model_config.json")
me = {}
if os.path.exists(cfg_path):
    with open(cfg_path, "r", encoding="utf-8") as f:
        mc = json.load(f)
    me = (mc.get("models") or {}).get(MODEL, mc.get("default_config") or {})
MAX_TOKENS = me.get("max_tokens") or me.get("num_predict") or 4096
TEMPERATURE = float(me.get("temperature", 0.1))

url = f"{ZHIPU_BASE_URL.rstrip('/')}/chat/completions"
headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def call_glm(text: str, article_type: str = "") -> dict:
    """Call Z.AI with retry + exponential backoff on 429."""
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "..."

    system_prompt = get_summary_system_prompt(article_text=text, article_type=article_type)
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}]
    payload = {
        "model": MODEL, "messages": messages, "stream": False,
        "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE,
    }

    for attempt in range(MAX_RETRIES):
        try:
            r = req_lib.post(url, json=payload, headers=headers, timeout=120)
            if r.status_code == 429:
                wait = 15 * (2 ** attempt)  # 15, 30, 60, 120, 240s
                print(f"    429 rate limit (attempt {attempt+1}/{MAX_RETRIES}), waiting {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            raw = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if raw and raw.strip():
                return parse_summary_response(raw.strip())
            return {}
        except req_lib.exceptions.HTTPError as e:
            if "429" in str(e):
                wait = 15 * (2 ** attempt)
                print(f"    429 (attempt {attempt+1}/{MAX_RETRIES}), waiting {wait}s...")
                time.sleep(wait)
                continue
            print(f"    HTTP error: {e}")
            return {}
        except Exception as e:
            print(f"    Error: {e}")
            return {}
    print(f"    All {MAX_RETRIES} retries exhausted")
    return {}


# --- Main ---
candidates = repo.client.execute_query("""
    SELECT id, title, content, tickers, article_type, array_length(tickers, 1) as ticker_count
    FROM research_articles
    WHERE tickers IS NOT NULL AND array_length(tickers, 1) >= 2
    AND article_type NOT IN ('ETF Change', 'Opportunity Discovery')
    AND summary IS NOT NULL AND summary != ''
    AND content IS NOT NULL AND content != ''
    AND (ticker_sentiment IS NULL OR ticker_sentiment = '[]'::jsonb)
    ORDER BY fetched_at DESC
""")

total = len(candidates)
print(f"Model: {MODEL} | MaxTokens: {MAX_TOKENS} | Temp: {TEMPERATURE}")
print(f"Candidates: {total} | Delay: {BASE_DELAY}s between calls")
print(f"Est: ~{(35 * total) / 60:.0f} min sequential")
print("Starting...\n")

success = 0
failed = 0
skipped = 0
start_wall = time.time()

for i, article in enumerate(candidates):
    aid = str(article['id'])
    title = (article['title'] or '')[:60]
    old_count = article['ticker_count']
    content = article['content'] or ''
    atype = article.get('article_type', '')

    if len(content.strip()) < 50:
        skipped += 1
        continue

    t0 = time.time()
    summary_data = call_glm(content, article_type=atype)
    elapsed = time.time() - t0

    if not summary_data or not isinstance(summary_data, dict):
        print(f"[{i+1}/{total}] FAIL ({elapsed:.0f}s, no data): {title}...")
        failed += 1
        time.sleep(BASE_DELAY)
        continue

    new_summary = summary_data.get("summary", "")
    if not new_summary or len(new_summary.strip()) < 20:
        print(f"[{i+1}/{total}] FAIL ({elapsed:.0f}s, empty): {title}...")
        failed += 1
        time.sleep(BASE_DELAY)
        continue

    new_tickers = summary_data.get("tickers", [])
    new_ts = summary_data.get("ticker_sentiment", [])

    ok = repo.update_article_analysis(
        article_id=aid,
        summary=new_summary,
        tickers=new_tickers if new_tickers else None,
        sentiment=summary_data.get("sentiment"),
        sentiment_score=summary_data.get("sentiment_score"),
        claims=summary_data.get("claims"),
        fact_check=summary_data.get("fact_check"),
        conclusion=summary_data.get("conclusion"),
        logic_check=summary_data.get("logic_check"),
        ticker_sentiment=new_ts,
    )

    new_count = len(new_tickers) if new_tickers else 0
    delta = old_count - new_count
    done = success + failed + skipped + 1
    wall = time.time() - start_wall
    rate = wall / max(done, 1)
    eta = rate * (total - done)

    if ok:
        success += 1
    else:
        failed += 1

    status = "OK" if ok else "DB-FAIL"
    print(
        f"[{i+1}/{total}] {status} ({elapsed:.0f}s): {title}... "
        f"t:{old_count}->{new_count}({'+' if delta < 0 else '-'}{abs(delta)}) "
        f"s={summary_data.get('sentiment')}  "
        f"[{success}ok {failed}fail] ETA:{eta/60:.0f}m"
    )

    time.sleep(BASE_DELAY)

wall_elapsed = time.time() - start_wall
print(f"\n{'='*60}")
print(f"Done! Success: {success}, Failed: {failed}, Skipped: {skipped}")
print(f"Total: {success + failed + skipped}/{total}")
print(f"Wall time: {wall_elapsed/60:.1f} min")
