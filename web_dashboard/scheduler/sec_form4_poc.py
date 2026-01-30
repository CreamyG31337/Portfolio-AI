"""
SEC Form 4 proof-of-concept: download index, fetch sample filings, parse XML.

Tests whether we can:
1. Download quarterly form.idx and filter Form 4 rows
2. Fetch raw .txt filings and extract XML
3. Parse Form 4 XML (issuerTradingSymbol, reporting owner, nonDerivativeTable)
4. Map to insider_trades schema for data quality assessment

SEC requires User-Agent with contact info: set SEC_EDGAR_USER_AGENT or use default.
FlareSolverr: set FLARESOLVERR_URL (e.g. http://ts-ubuntu-server:8191 in web_dashboard/.env) to bypass 403.
Run from repo root: python web_dashboard/scheduler/sec_form4_poc.py
"""

import gzip
import io
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import requests

# Path setup for running from repo root or web_dashboard
_current = Path(__file__).resolve().parent
if _current.name == "scheduler":
    _project_root = _current.parent.parent
    _web_dashboard = _current.parent
else:
    _project_root = _current.parent
    _web_dashboard = _current

if str(_project_root) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_project_root))
if str(_web_dashboard) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_web_dashboard))

# Load env from project root and web_dashboard so FLARESOLVERR_URL is set
try:
    from dotenv import load_dotenv
    load_dotenv(_project_root / ".env")
    load_dotenv(_project_root / "web_dashboard" / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SEC_ARCHIVES = "https://www.sec.gov/Archives"
# SEC requires User-Agent with contact: "Company Name AdminContact@company.com" (see sec.gov/os/accessing-edgar-data)
DEFAULT_USER_AGENT = "LLM-Micro-Cap-Trading-Bot AdminContact@example.com"
# Target ~9 requests/sec to stay under SEC's 10/sec; limiter is global and thread-safe for parallel fetch
_REQUESTS_PER_SEC = 9.0
_rate_limit_lock = threading.Lock()
_last_request_time = 0.0


def _rate_limit_wait() -> None:
    """Wait until we can start another SEC request (thread-safe, ~9 req/s)."""
    global _last_request_time
    with _rate_limit_lock:
        now = time.monotonic()
        wait = (_last_request_time + (1.0 / _REQUESTS_PER_SEC)) - now
        if wait > 0:
            _rate_limit_lock.release()
            time.sleep(wait)
            _rate_limit_lock.acquire()
        _last_request_time = time.monotonic()


FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "").strip()

# Retry on transient server/rate-limit errors (503, 502, 429)
RETRYABLE_STATUS = (429, 502, 503)
SEC_FETCH_MAX_RETRIES = int(os.getenv("SEC_FETCH_MAX_RETRIES", "5"))
SEC_FETCH_BACKOFF_BASE = float(os.getenv("SEC_FETCH_BACKOFF_BASE", "2.0"))


def _headers() -> Dict[str, str]:
    ua = os.getenv("SEC_EDGAR_USER_AGENT", "").strip() or DEFAULT_USER_AGENT
    return {"User-Agent": ua, "Accept-Encoding": "gzip", "Accept": "*/*"}


def fetch_via_flaresolverr(url: str, timeout: int = 120) -> Optional[str]:
    """Fetch URL via FlareSolverr to bypass Cloudflare/403. Returns response body as text."""
    if not FLARESOLVERR_URL:
        return None
    try:
        endpoint = f"{FLARESOLVERR_URL.rstrip('/')}/v1"
        payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
        logger.debug("Requesting via FlareSolverr: %s", url[:80])
        r = requests.post(endpoint, json=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "ok":
            logger.warning("FlareSolverr error: %s", data.get("message", "Unknown"))
            return None
        solution = data.get("solution", {}) or {}
        body = solution.get("response")
        if body is None:
            return None
        if isinstance(body, bytes):
            return body.decode("utf-8", errors="replace")
        return str(body)
    except requests.exceptions.ConnectionError:
        logger.warning("FlareSolverr unavailable at %s", FLARESOLVERR_URL)
        return None
    except requests.exceptions.Timeout:
        logger.warning("FlareSolverr request timed out")
        return None
    except Exception as e:
        logger.warning("FlareSolverr request failed: %s", e)
        return None


def download_index(year: int, quarter: int, use_gzip: bool = True) -> Optional[str]:
    """Download form index for a quarter. Retries on 503/502/429; FlareSolverr on 403."""
    base = f"{SEC_ARCHIVES}/edgar/full-index/{year}/QTR{quarter}"
    url = f"{base}/form.gz" if use_gzip else f"{base}/form.idx"
    logger.info("Downloading index: %s", url)
    last_error: Optional[Exception] = None
    for attempt in range(SEC_FETCH_MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=_headers(), timeout=120)
            if r.status_code in RETRYABLE_STATUS and attempt < SEC_FETCH_MAX_RETRIES:
                backoff = min(SEC_FETCH_BACKOFF_BASE ** attempt, 60.0)
                logger.warning("SEC %s for index, retry %s/%s in %.1fs", r.status_code, attempt + 1, SEC_FETCH_MAX_RETRIES, backoff)
                time.sleep(backoff)
                continue
            r.raise_for_status()
            if use_gzip:
                return gzip.decompress(r.content).decode("utf-8", errors="replace")
            return r.text
        except requests.exceptions.HTTPError as e:
            last_error = e
            if e.response is not None and e.response.status_code == 403 and FLARESOLVERR_URL:
                logger.info("Index returned 403; trying FlareSolverr (%s)...", FLARESOLVERR_URL)
                body = fetch_via_flaresolverr(url, timeout=120)
                if body is not None:
                    return body
            if e.response is not None and e.response.status_code in RETRYABLE_STATUS and attempt < SEC_FETCH_MAX_RETRIES:
                backoff = min(SEC_FETCH_BACKOFF_BASE ** attempt, 60.0)
                logger.warning("SEC %s for index, retry %s/%s in %.1fs", e.response.status_code, attempt + 1, SEC_FETCH_MAX_RETRIES, backoff)
                time.sleep(backoff)
                continue
            logger.error("Failed to download index: %s", e)
            return None
        except Exception as e:
            last_error = e
            if attempt < SEC_FETCH_MAX_RETRIES:
                backoff = min(SEC_FETCH_BACKOFF_BASE ** attempt, 60.0)
                logger.warning("Index fetch error %s, retry %s/%s in %.1fs", e, attempt + 1, SEC_FETCH_MAX_RETRIES, backoff)
                time.sleep(backoff)
                continue
            logger.error("Failed to download index: %s", e)
            return None
    logger.error("Failed to download index after %s retries: %s", SEC_FETCH_MAX_RETRIES + 1, last_error)
    return None


def parse_form_idx(content: str) -> List[Tuple[str, str, str, str, str]]:
    """
    Parse form.idx. SEC full-index form.gz is fixed-width (not pipe-delimited):
    Form Type   Company Name...   CIK   Date Filed  File Name
    Skip header/description lines; then match: form_type + company, CIK, date, edgar/data/...
    """
    rows: List[Tuple[str, str, str, str, str]] = []
    # Fixed-width: line ends with "  CIK  YYYY-MM-DD  edgar/data/..."
    data_line_re = re.compile(
        r"^(.+?)\s+(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(edgar/data/\S+)\s*$"
    )
    for line in content.splitlines():
        line = line.rstrip()
        if not line or line.startswith("Description") or line.startswith("Last Data") or line.startswith("Comments") or line.startswith("Anonymous"):
            continue
        if "Form Type" in line and "CIK" in line and "File Name" in line:
            continue
        if line.startswith("---"):
            continue
        m = data_line_re.match(line)
        if not m:
            continue
        prefix, cik, date_filed, filename = m.group(1), m.group(2), m.group(3), m.group(4).strip()
        # Prefix is "Form Type   Company Name" — form type is first token, rest is company
        tokens = prefix.split()
        if not tokens:
            continue
        form_type = tokens[0]
        company = " ".join(tokens[1:]).strip() if len(tokens) > 1 else ""
        if form_type and filename:
            rows.append((cik, company, form_type, date_filed, filename))
    return rows


def filter_form4(rows: List[Tuple[str, str, str, str, str]]) -> List[Tuple[str, str, str, str, str]]:
    """Keep only Form 4 and 4/A."""
    return [r for r in rows if r[2] in ("4", "4/A")]


def fetch_filing(filename: str) -> Optional[str]:
    """Fetch one filing by path (e.g. edgar/data/123/000123-24-000001.txt). Retries on 503/502/429; FlareSolverr on 403. Rate-limited (~9 req/s)."""
    if not filename.startswith("edgar/"):
        filename = "edgar/data/" + filename.lstrip("/")
    url = f"{SEC_ARCHIVES}/{filename}"
    logger.debug("Fetching filing: %s", url[:80])
    last_error: Optional[Exception] = None
    for attempt in range(SEC_FETCH_MAX_RETRIES + 1):
        _rate_limit_wait()
        try:
            r = requests.get(url, headers=_headers(), timeout=60)
            if r.status_code in RETRYABLE_STATUS and attempt < SEC_FETCH_MAX_RETRIES:
                backoff = min(SEC_FETCH_BACKOFF_BASE ** attempt, 60.0)
                logger.warning("SEC %s for %s, retry %s/%s in %.1fs", r.status_code, url[:60], attempt + 1, SEC_FETCH_MAX_RETRIES, backoff)
                time.sleep(backoff)
                continue
            r.raise_for_status()
            return r.text
        except requests.exceptions.HTTPError as e:
            last_error = e
            if e.response is not None and e.response.status_code == 403 and FLARESOLVERR_URL:
                body = fetch_via_flaresolverr(url, timeout=90)
                if body:
                    return body
            if e.response is not None and e.response.status_code in RETRYABLE_STATUS and attempt < SEC_FETCH_MAX_RETRIES:
                backoff = min(SEC_FETCH_BACKOFF_BASE ** attempt, 60.0)
                logger.warning("SEC %s for %s, retry %s/%s in %.1fs", e.response.status_code, url[:60], attempt + 1, SEC_FETCH_MAX_RETRIES, backoff)
                time.sleep(backoff)
                continue
            logger.error("Failed to fetch filing: %s", e)
            return None
        except Exception as e:
            last_error = e
            if attempt < SEC_FETCH_MAX_RETRIES:
                backoff = min(SEC_FETCH_BACKOFF_BASE ** attempt, 60.0)
                logger.warning("Fetch error %s, retry %s/%s in %.1fs", e, attempt + 1, SEC_FETCH_MAX_RETRIES, backoff)
                time.sleep(backoff)
                continue
            logger.error("Failed to fetch filing: %s", e)
            return None
    logger.error("Failed to fetch filing after %s retries: %s", SEC_FETCH_MAX_RETRIES + 1, last_error)
    return None


def extract_xml_from_submission(content: str) -> Optional[str]:
    """
    SEC submission is SGML with <DOCUMENT>...</DOCUMENT> sections.
    One document is the Form 4 XML (type form4 or similar). Extract it.
    """
    if "<ownershipDocument" in content or "<ownershipDocument>" in content:
        start = content.find("<ownershipDocument")
        if start == -1:
            start = content.find("<ownershipDocument>")
        end = content.find("</ownershipDocument>")
        if end != -1:
            end += len("</ownershipDocument>")
            return content[start:end]
    doc_start = re.compile(r"<DOCUMENT>", re.IGNORECASE)
    doc_end = re.compile(r"</DOCUMENT>", re.IGNORECASE)
    start_pos = 0
    while True:
        m = doc_start.search(content, start_pos)
        if not m:
            break
        start_pos = m.end()
        m_end = doc_end.search(content, start_pos)
        if not m_end:
            break
        block = content[start_pos : m_end.start()]
        if "form4" in block.lower() or "FORM 4" in block or "<nonDerivativeTable" in block or "<issuerTradingSymbol>" in block:
            xml_match = re.search(r"<XML>\s*(.*?)</XML>", block, re.DOTALL | re.IGNORECASE)
            if xml_match:
                return xml_match.group(1).strip()
            if "<ownershipDocument" in block or "<nonDerivativeTable" in block:
                start = block.find("<ownershipDocument")
                if start == -1:
                    start = block.find("<")
                end = block.rfind("</ownershipDocument>")
                if end == -1:
                    end = block.rfind(">") + 1
                return block[start : end + len("</ownershipDocument>")] if "</ownershipDocument>" in block else block[start:]
        start_pos = m_end.end()
    return None


def _extract_title_from_remarks(content: str) -> str:
    """
    When officerTitle is "See remarks", try to get actual title from Remarks or
    Explanation of Responses section (e.g. "may be deemed director" -> "Director").
    """
    # Find Remarks or Explanation of Responses block
    remarks_start = re.search(
        r"(?:Remarks:\s*|Explanation of Responses:\s*)(.+?)(?=\n\s*\n|\n\s*[0-9]+\.|\Z)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if not remarks_start:
        return ""
    block = remarks_start.group(1).strip()[:800]  # first chunk
    # Common patterns: "may be deemed director(s)" -> Director; "Officer (CEO)" -> CEO
    m = re.search(r"may be deemed\s+([a-z]+)(?:\s+of|\s*\.|,|\s+by)", block, re.IGNORECASE)
    if m:
        t = m.group(1).strip()
        if t.endswith("s") and len(t) > 1:
            t = t[:-1]  # directors -> director
        return t.title() if t else ""
    m = re.search(r"Officer\s*\(([^)]+)\)", block, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b(director|officer|ceo|cfo|coo|evp|svp|vp|president|secretary|treasurer)\b", block, re.IGNORECASE)
    if m:
        return m.group(1).strip().title()
    # First sentence up to 60 chars, cleaned
    first = re.split(r"[.\n]", block)[0].strip()[:60].strip()
    if first and len(first) > 2:
        return first
    return ""


def parse_form4_sgml(content: str) -> List[Dict[str, Any]]:
    """
    Parse Form 4 submission when it is SGML/text (not XML).
    Extracts: issuer ticker, reporting owner, transaction date, code, shares, price, value.
    """
    out: List[Dict[str, Any]] = []
    # Ticker: prefer explicit ticker (PSTG, AAPL) or 2–5 letter symbol; skip common words
    # Skip common words that SGML fallback might wrongly pick as ticker (e.g. "of" in "number of shares")
    skip_tickers = {
        "SEC", "ACT", "FORM", "TYPE", "DE", "CA", "C/O", "IRS", "D", "P", "S", "A", "G", "F", "M", "X", "O", "W", "H",
        "OF", "OR", "ON", "BY", "AS", "IF", "NO", "SO", "UP", "DO", "GO", "WE", "HE", "ME", "MY", "IT", "US", "CO", "NA",
        "COUNT", "NAME", "DATA", "FILE", "FILED", "NONE", "DATE", "OWNER", "INDEX", "FILM", "MAIL", "ZIP", "STREET", "CITY", "STATE", "PHONE", "ORG", "INC", "LTD", "LLC",
    }
    ticker = ""
    # Prefer XML ticker when raw content has embedded Form 4 XML (e.g. <issuerTradingSymbol>FLWS</issuerTradingSymbol>)
    # Blank "NONE" — filers use it when issuer has no ticker (not publicly traded).
    xml_ticker_m = re.search(r"<issuerTradingSymbol[^>]*>([^<]+)</issuerTradingSymbol>", content, re.IGNORECASE)
    if xml_ticker_m:
        raw_ticker = xml_ticker_m.group(1).strip().upper()
        ticker = raw_ticker if raw_ticker and raw_ticker != "NONE" else ""
    if not ticker:
        ticker_m = re.search(r"(?:issuerTradingSymbol|ticker|symbol)[\s:>]*([A-Z]{2,5})", content, re.IGNORECASE)
        if ticker_m:
            ticker = ticker_m.group(1).strip().upper()
            if ticker == "NONE":
                ticker = ""  # filer placeholder for no ticker
    if not ticker:
        for s in ("PSTG", "AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "TSLA"):
            if s in content and re.search(r"\b" + s + r"\b", content):
                ticker = s
                break
    if not ticker:
        for m in re.finditer(r"\b([A-Z]{2,5})\b", content):
            s = m.group(1)
            if s in skip_tickers or not s.isalpha():
                continue
            if 2 <= len(s) <= 5:
                ticker = s
                break
    # Transaction date: YYYY-MM-DD
    date_m = re.search(r"(20\d{2}-\d{2}-\d{2})", content)
    trans_date = date_m.group(1) if date_m else ""
    # Transaction code: P, S, A, D, etc. (P=Purchase, S=Sale)
    code = ""
    if re.search(r"\bS\b", content) and "Sale" not in content:
        code_m = re.search(r"\s([PSADFG])\s", content)
        if code_m:
            code = code_m.group(1).upper()
    if not code and "S\n" in content or " S " in content:
        code = "S"
    if not code and "P\n" in content or " P " in content:
        code = "P"
    trans_type = "Sale" if code == "S" or "sold" in content.lower() else "Purchase"
    if code == "P" or code == "A" or code == "G":
        trans_type = "Purchase"
    # Shares, price, value: SGML often has blocks like "7500\n52.80\nD\n28896"
    shares, price, value = None, None, None
    # Pattern: integer (shares), then float (price), then A/D, then optional value
    block_m = re.search(r"\n\s*(\d{2,10})\s*\n\s*(\d+\.\d{2,4})\s*\n\s*[AD]\s*\n\s*(\d[\d,]*)", content)
    if block_m:
        try:
            shares = int(block_m.group(1).replace(",", ""))
            price = float(block_m.group(2).replace(",", ""))
            value = float(block_m.group(3).replace(",", ""))
        except ValueError:
            pass
    if shares is None:
        share_m = re.search(r"transactionShares[\s:]*(\d[\d,]*)", content, re.IGNORECASE)
        if share_m:
            try:
                shares = int(share_m.group(1).replace(",", ""))
            except ValueError:
                pass
    if price is None:
        price_m = re.search(r"(\d+\.\d{2,4})\s*\n\s*[AD]\s", content) or re.search(r"pricePerShare[\s:]*(\d+\.?\d*)", content, re.IGNORECASE)
        if price_m:
            try:
                price = float(price_m.group(1).replace(",", ""))
            except ValueError:
                pass
    if value is None and shares is not None and price is not None:
        value = round(shares * price, 2)
    if value is None:
        value_m = re.search(r"transactionValue[\s:]*(\d[\d,]*)", content, re.IGNORECASE)
        if value_m:
            try:
                value = float(value_m.group(1).replace(",", ""))
            except ValueError:
                pass
    # Reporting owner: rptOwnerName, /s/ Name, or ORGANIZATION NAME (strip leading >)
    owner_name = ""
    owner_m = re.search(r"rptOwnerName[\s:]*([^\n<]+)", content, re.IGNORECASE)
    if owner_m:
        owner_name = owner_m.group(1).strip().lstrip(">")
    if not owner_name:
        owner_m = re.search(r"/s/\s*([^,\n]+)", content)
        if owner_m:
            owner_name = owner_m.group(1).strip().lstrip(">")
    if not owner_name:
        owner_m = re.search(r"ORGANIZATION NAME:\s*([^\n]+)", content)
        if owner_m:
            owner_name = owner_m.group(1).strip().lstrip(">")
    owner_name = (owner_name or "Unknown").lstrip(">").strip()
    owner_title = ""
    title_m = re.search(r"officerTitle[\s:]*([^\n<]+)", content, re.IGNORECASE)
    if title_m:
        owner_title = title_m.group(1).strip().lstrip(">")
    # Resolve "See remarks" from Remarks / Explanation of Responses section
    if (owner_title or "").strip().lower() in ("see remarks", "see remark"):
        owner_title = _extract_title_from_remarks(content)
    out.append({
        "ticker": ticker.strip().upper() if ticker else "",
        "insider_name": owner_name or "Unknown",
        "insider_title": owner_title or "",
        "transaction_date": trans_date,
        "disclosure_date": trans_date,
        "type": trans_type,
        "shares": shares,
        "price_per_share": price,
        "value": value,
    })
    return out


def _text(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    # Prefer child <value> if present (Form 4 often wraps text in <value>)
    for child in list(el) if hasattr(el, "__iter__") else []:
        if (child.tag or "").endswith("value") and (child.text or "").strip():
            return (child.text or "").strip()
    return (el.text or "").strip() + "".join((ET.tostring(e, encoding="unicode", method="text") for e in el)).strip()


def _find(el: Optional[ET.Element], path: str) -> Optional[ET.Element]:
    if el is None:
        return None
    # Handle namespace: Form 4 XML often has ns like ns1, ns2
    for child in el.iter():
        if child.tag.endswith(path.split("/")[-1]) or path in child.tag:
            return child
    return el.find(path)


def parse_form4_xml(xml_str: str) -> List[Dict[str, Any]]:
    """
    Parse Form 4 XML and return list of transaction dicts aligned with insider_trades.
    Expects ownershipDocument with issuer, reportingOwner, nonDerivativeTable.
    """
    # Strip possible BOM and junk before root
    xml_str = xml_str.strip()
    if xml_str.startswith("\ufeff"):
        xml_str = xml_str[1:]
    # Handle namespaces: strip or register
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        logger.warning("XML parse error: %s", e)
        return []
    # Find root (ownershipDocument or similar)
    if root.tag.endswith("ownershipDocument") or "ownershipDocument" in root.tag:
        doc = root
    else:
        doc = root
    ns = {"ns": "http://www.sec.gov/edgar/document/thirteenf/informationtable"}  # may not be used
    # Issuer: issuerTradingSymbol, issuerName
    issuer_el = None
    for el in doc.iter():
        if "issuer" in el.tag.lower() and el.tag.endswith("issuer"):
            issuer_el = el
            break
    if issuer_el is None:
        for el in doc.iter():
            if "issuerTradingSymbol" in el.tag or (el.tag.endswith("issuerTradingSymbol")):
                issuer_el = el
                break
    ticker = ""
    if issuer_el is not None:
        for child in issuer_el.iter():
            if "issuerTradingSymbol" in child.tag or child.tag.endswith("issuerTradingSymbol"):
                ticker = _text(child)
                break
        if not ticker:
            for child in issuer_el.iter():
                if "rptOwnerSymbol" in child.tag or "tradingSymbol" in child.tag.lower():
                    ticker = _text(child)
                    break
    if not ticker:
        for el in doc.iter():
            if "issuerTradingSymbol" in el.tag or el.tag.endswith("issuerTradingSymbol"):
                ticker = _text(el)
                break
    ticker = (ticker or "").strip().upper()
    if ticker in ("FILED", "NONE", "-", "DATE", "OWNER", "INDEX"):
        ticker = ""  # KEY/FILM let through so backfill can save raw for inspection

    # Build footnote map: footnoteId -> footnoteText (for resolving "See remarks" on officerTitle)
    footnote_map: Dict[str, str] = {}
    for el in doc.iter():
        tag = (el.tag or "").lower()
        if "footnoteentry" in tag or tag == "footnote":
            fid, ftext = "", ""
            for child in list(el) if hasattr(el, "__iter__") else []:
                ct = (child.tag or "").lower()
                if "footnoteid" in ct:
                    fid = (_text(child) or "").strip()
                elif "footnotetext" in ct:
                    ftext = (_text(child) or "").strip()
            if fid and ftext:
                footnote_map[fid] = ftext
        if "footnotetext" in tag and not footnote_map:
            ftext = _text(el).strip()
            if ftext:
                footnote_map["1"] = ftext  # some filings only have footnoteText
    # Also collect by id attribute
    for el in doc.iter():
        if (el.tag or "").lower().endswith("footnote") and el.attrib.get("id"):
            fid = (el.attrib.get("id") or "").strip()
            if fid and _text(el).strip():
                footnote_map[fid] = _text(el).strip()

    # Reporting owner: name, relationship, and footnoteId for title (for "See remarks")
    report_owner_name = ""
    report_owner_title = ""
    title_footnote_id = ""
    for el in doc.iter():
        if "reportingOwner" in el.tag.lower() or el.tag.endswith("reportingOwner"):
            for c in el.iter():
                if "reportingOwnerId" in c.tag or "rptOwnerId" in c.tag.lower():
                    for cc in c.iter():
                        if "name" in cc.tag.lower() and "rptOwner" in cc.tag.lower():
                            report_owner_name = _text(cc)
                            break
                if "reportingOwnerRelationship" in c.tag.lower() or "rptOwnerRel" in c.tag.lower():
                    for cc in list(c) if hasattr(c, "__iter__") else []:
                        if "officerTitle" in (cc.tag or "") or (cc.tag or "").lower().endswith("title"):
                            report_owner_title = _text(cc)
                            # Sibling footnoteId in same relationship block
                            for sib in list(c) if hasattr(c, "__iter__") else []:
                                if "footnoteId" in (sib.tag or "") or (sib.tag or "").lower().endswith("footnoteid"):
                                    title_footnote_id = (_text(sib) or "").strip()
                                    break
                            break
            if report_owner_name:
                break
    if not report_owner_name:
        for el in doc.iter():
            if "rptOwnerName" in el.tag or el.tag.endswith("rptOwnerName"):
                report_owner_name = _text(el)
                break

    # Resolve "See remarks" from footnote map
    if (report_owner_title or "").strip().lower() in ("see remarks", "see remark"):
        if title_footnote_id and title_footnote_id in footnote_map:
            report_owner_title = footnote_map[title_footnote_id]
        elif footnote_map:
            report_owner_title = next(iter(footnote_map.values()))
        else:
            report_owner_title = ""

    # Non-derivative table: transaction date, code, shares, price, value
    # Form 4 XML uses <value> child for many fields (periodOfReport, transactionDate, etc.)
    transactions: List[Dict[str, Any]] = []
    for el in doc.iter():
        tag = (el.tag or "").lower()
        if "nonderivativetransaction" not in tag and "nonderivativetrans" not in tag:
            continue
        trans_date = ""
        trans_code = ""
        shares = None
        price = None
        value = None
        for cell in el.iter():
            ct = (cell.tag or "").lower()
            if "transactiondate" in ct or "transdate" in ct:
                trans_date = _text(cell) or trans_date
            elif "transactioncoding" in ct or "transcode" in ct:
                trans_code = _text(cell) or trans_code
            elif "transactionamounts" in ct or "transamounts" in ct:
                for sub in cell:
                    st = (sub.tag or "").lower()
                    if "transactionshares" in st or (st.endswith("shares") and "transaction" in st):
                        try:
                            shares = int(float(_text(sub).replace(",", "")))
                        except ValueError:
                            pass
                    elif "transactionpricepershare" in st or "pricepershare" in st:
                        try:
                            price = float(_text(sub).replace(",", ""))
                        except ValueError:
                            pass
                    elif "transactionvalue" in st or (st.endswith("value") and "transaction" in st):
                        try:
                            value = float(_text(sub).replace(",", ""))
                        except ValueError:
                            pass
            elif "transactionShares" in ct:
                try:
                    shares = int(float(_text(cell).replace(",", "")))
                except ValueError:
                    pass
            elif "transactionPricePerShare" in ct or "pricePerShare" in ct:
                try:
                    price = float(_text(cell).replace(",", ""))
                except ValueError:
                    pass
            elif "transactionValue" in ct:
                try:
                    value = float(_text(cell).replace(",", ""))
                except ValueError:
                    pass
        if trans_date or shares is not None:
            trans_type = "Purchase" if trans_code and trans_code.upper() in ("P", "A", "G") else "Sale"
            if trans_code and "S" in trans_code.upper():
                trans_type = "Sale"
            if not trans_date:
                # Fallback: periodOfReport
                for e in doc.iter():
                    if (e.tag or "").lower().endswith("periodofreport"):
                        trans_date = _text(e)
                        break
            if value is None and shares is not None and price is not None:
                value = round(shares * price, 2)
            transactions.append({
                "ticker": ticker,
                "insider_name": report_owner_name or "Unknown",
                "insider_title": report_owner_title or "",
                "transaction_date": trans_date,
                "disclosure_date": trans_date,
                "type": trans_type,
                "shares": shares,
                "price_per_share": price,
                "value": value,
            })
    if not transactions and (ticker or report_owner_name):
        transactions.append({
            "ticker": ticker,
            "insider_name": report_owner_name or "Unknown",
            "insider_title": report_owner_title or "",
            "transaction_date": "",
            "disclosure_date": "",
            "type": "Unknown",
            "shares": None,
            "price_per_share": None,
            "value": None,
        })
    return transactions


# Fallback: known Form 4 submission paths if index returns 403 (e.g. IP/UA block).
# Paths from SEC EDGAR (submission .txt contains SGML with embedded Form 4 XML).
SAMPLE_FORM4_FALLBACK = [
    ("1474432", "Pure Storage Inc", "4", "2024-03-11", "edgar/data/1474432/000147443224000043/0001474432-24-000043.txt"),
    ("320193", "Apple Inc", "4", "2024-01-18", "edgar/data/320193/000032019324000018/0000320193-24-000018.txt"),
]


def fetch_filing_by_path(path: str) -> Optional[str]:
    """Fetch filing by full path under Archives. Retries on 503/502/429; FlareSolverr on 403."""
    url = f"{SEC_ARCHIVES}/{path}" if not path.startswith("http") else path
    logger.info("Fetching: %s", url[:80])
    last_error: Optional[Exception] = None
    for attempt in range(SEC_FETCH_MAX_RETRIES + 1):
        _rate_limit_wait()
        try:
            r = requests.get(url, headers=_headers(), timeout=60)
            if r.status_code in RETRYABLE_STATUS and attempt < SEC_FETCH_MAX_RETRIES:
                backoff = min(SEC_FETCH_BACKOFF_BASE ** attempt, 60.0)
                logger.warning("SEC %s for %s, retry %s/%s in %.1fs", r.status_code, url[:60], attempt + 1, SEC_FETCH_MAX_RETRIES, backoff)
                time.sleep(backoff)
                continue
            r.raise_for_status()
            return r.text
        except requests.exceptions.HTTPError as e:
            last_error = e
            if e.response is not None and e.response.status_code == 403 and FLARESOLVERR_URL:
                body = fetch_via_flaresolverr(url, timeout=90)
                if body:
                    return body
            if e.response is not None and e.response.status_code in RETRYABLE_STATUS and attempt < SEC_FETCH_MAX_RETRIES:
                backoff = min(SEC_FETCH_BACKOFF_BASE ** attempt, 60.0)
                logger.warning("SEC %s for %s, retry %s/%s in %.1fs", e.response.status_code, url[:60], attempt + 1, SEC_FETCH_MAX_RETRIES, backoff)
                time.sleep(backoff)
                continue
            logger.error("Failed: %s", e)
            return None
        except Exception as e:
            last_error = e
            if attempt < SEC_FETCH_MAX_RETRIES:
                backoff = min(SEC_FETCH_BACKOFF_BASE ** attempt, 60.0)
                logger.warning("Fetch error %s, retry %s/%s in %.1fs", e, attempt + 1, SEC_FETCH_MAX_RETRIES, backoff)
                time.sleep(backoff)
                continue
            logger.error("Failed: %s", e)
            return None
    logger.error("Failed after %s retries: %s", SEC_FETCH_MAX_RETRIES + 1, last_error)
    return None


def main() -> None:
    year, quarter = 2024, 1
    index_text = download_index(year, quarter, use_gzip=True)
    form4_rows: List[Tuple[str, str, str, str, str]] = []
    if index_text:
        lines = index_text.splitlines()
        logger.info("Index lines: %s", len(lines))
        rows = parse_form_idx(index_text)
        form4_rows = filter_form4(rows)
        logger.info("Form 4 (and 4/A) rows in index: %s", len(form4_rows))
        if len(rows) == 0 and len(lines) > 0 and ("<html" in index_text.lower()[:1000] or "<!doctype" in index_text.lower()[:500]):
            logger.warning("Response looks like HTML (e.g. SEC block page), not index. FlareSolverr may need different setup.")
    if not form4_rows:
        logger.warning("No index or no Form 4 rows; using fallback sample URLs to test parser.")
        form4_rows = SAMPLE_FORM4_FALLBACK
    # Sample first 5 Form 4 filings
    sample = [r for r in form4_rows if r[2] == "4"][:5]
    if len(sample) < 5:
        sample = form4_rows[:5]
    all_trans: List[Dict[str, Any]] = []
    for cik, company, form_type, date_filed, filename in sample:
        logger.info("Sample: CIK=%s Form=%s File=%s", cik, form_type, filename[:60])
        raw = fetch_filing(filename) if index_text else fetch_filing_by_path(filename)
        if not raw:
            continue
        xml_str = extract_xml_from_submission(raw)
        if not xml_str and ("<ownershipDocument" in raw or "<nonDerivativeTable" in raw):
            xml_str = raw
        if xml_str:
            trans = parse_form4_xml(xml_str)
        else:
            trans = []
        if not trans or all(not t.get("transaction_date") for t in trans):
            sgml_trans = parse_form4_sgml(raw)
            if sgml_trans:
                trans = sgml_trans
                logger.info("Parsed via SGML fallback.")
        if not trans:
            logger.warning("No XML extracted (len=%s). First 400 chars: %s", len(raw), raw[:400])
            continue
        logger.info("Parsed %s transaction(s) from filing.", len(trans))
        for t in trans:
            t["_source_file"] = filename
            t["_date_filed"] = date_filed
        all_trans.extend(trans)
    # Report data quality
    logger.info("Total parsed transactions (sample): %s", len(all_trans))
    for i, t in enumerate(all_trans[:15]):
        logger.info(
            "  [%s] ticker=%s insider=%s title=%s date=%s type=%s shares=%s price=%s value=%s",
            i + 1, t.get("ticker"), t.get("insider_name"), t.get("insider_title"),
            t.get("transaction_date"), t.get("type"), t.get("shares"), t.get("price_per_share"), t.get("value"),
        )
    # Quality summary
    with_ticker = sum(1 for t in all_trans if t.get("ticker"))
    with_name = sum(1 for t in all_trans if t.get("insider_name") and t.get("insider_name") != "Unknown")
    with_date = sum(1 for t in all_trans if t.get("transaction_date"))
    with_shares = sum(1 for t in all_trans if t.get("shares") is not None)
    with_price = sum(1 for t in all_trans if t.get("price_per_share") is not None)
    with_value = sum(1 for t in all_trans if t.get("value") is not None)
    n = len(all_trans) or 1
    logger.info(
        "Quality: ticker=%s/%s name=%s/%s date=%s/%s shares=%s/%s price=%s/%s value=%s/%s",
        with_ticker, n, with_name, n, with_date, n, with_shares, n, with_price, n, with_value, n,
    )


if __name__ == "__main__":
    main()
