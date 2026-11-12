"""Monthly re-run of the Phase L precursor study (roadmap Phase L, zero-review §2.8).

Every result in Phase L rests on a few months of data. This job re-runs the whole
pipeline once a month so the holdout grows by one window each time and signals get
re-judged without anyone remembering to do it:

    winners_study.py prices          refresh the price panel (yfinance, ~3k tickers)
    winners_study.py prices --fill   retry rate-limited gaps
    winners_study.py label           peer-relative winners/losers per 63-day window
    winners_study.py rescore-ideas   alpha_idea outcomes vs peers
    precursor_study.py               discovery (frozen) vs growing holdout
                                     -> logs/study/precursor_latest.json

The weekly retro digest reads precursor_latest.json. Each step runs in its own
process so a slow download or a pandas memory spike cannot hurt the scheduler.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

current_dir = Path(__file__).resolve().parent
if str(current_dir.parent) not in sys.path:
    sys.path.insert(0, str(current_dir.parent))

from scheduler.scheduler_core import log_job_execution  # noqa: E402

logger = logging.getLogger(__name__)

JOB_ID = "phase_l_restudy"
_SCRIPTS = current_dir.parent / "scripts"
_REPO_ROOT = current_dir.parent.parent
STEP_TIMEOUT_S = 2 * 60 * 60

STEPS: tuple[tuple[str, list[str]], ...] = (
    ("prices", [str(_SCRIPTS / "winners_study.py"), "prices"]),
    ("prices_fill", [str(_SCRIPTS / "winners_study.py"), "prices", "--fill"]),
    ("label", [str(_SCRIPTS / "winners_study.py"), "label"]),
    ("rescore_ideas", [str(_SCRIPTS / "winners_study.py"), "rescore-ideas"]),
    ("precursor", [str(_SCRIPTS / "precursor_study.py")]),
)
# A failed fill or rescore should not stop the study itself.
_OPTIONAL = {"prices_fill", "rescore_ideas"}


def _run_step(name: str, args: list[str]) -> tuple[bool, str]:
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, *args],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=STEP_TIMEOUT_S,
    )
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    secs = int(time.time() - t0)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-5:]
        logger.error("phase_l_restudy step %s failed (%ss): %s", name, secs, " | ".join(err))
        return False, f"{name}: exit {proc.returncode}"
    logger.info("phase_l_restudy step %s ok (%ss): %s", name, secs, " | ".join(tail))
    return True, f"{name}: ok {secs}s"


def phase_l_restudy_job() -> None:
    start = time.time()
    target_date = datetime.now(UTC).date()
    try:
        from utils.job_tracking import mark_job_completed, mark_job_started

        mark_job_started(JOB_ID, target_date)
        notes: list[str] = []
        for name, args in STEPS:
            ok, note = _run_step(name, args)
            notes.append(note)
            if not ok and name not in _OPTIONAL:
                raise RuntimeError("; ".join(notes))

        duration_ms = int((time.time() - start) * 1000)
        msg = "; ".join(notes)
        log_job_execution(JOB_ID, True, msg, duration_ms)
        mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
        logger.info("phase_l_restudy_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("phase_l_restudy_job failed: %s", exc, exc_info=True)
