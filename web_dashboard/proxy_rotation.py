"""Gluetun exit-IP rotation for Phase K caption fetching.

YouTube enforces a **per-IP quota** on the timedtext endpoint — roughly 90-110
caption fetches before a multi-hour block, largely independent of pacing (see
docs/PHASE_K_SOURCE_LIST.md §14). Slowing down does not buy meaningful headroom;
changing egress IP does.

Steady-state ingest (15 sources x 3-5 videos/day) fits inside one IP's budget, so
rotation matters for **backfill**, not for the nightly job.

Prefer rotating *before* the quota trips: a blocked IP stays blocked for hours,
while an IP retired early stays clean for its next turn.

**Pool size matters more than rotation frequency.** A restart re-picks a server
from whatever ``SERVER_COUNTRIES`` allows, and a single country may hold only a
handful of servers — so rotating within one country can hand back an IP whose
quota is already spent. Widen the filter in the Gluetun compose file instead of
rotating harder::

    SERVER_COUNTRIES=Netherlands,Germany,France,Belgium,Sweden,Switzerland

That needs no control-API support (it is container config), and every rotation
then draws from a much larger pool. ``RotatingBudget`` tracks which exit IPs it
has already burned and reports ``exhausted`` when the pool is too small, so a
narrow filter surfaces as a clear message rather than as mystery blocks.

Configuration (all optional; absent config disables rotation cleanly):
    GLUETUN_CONTROL_URL   e.g. http://100.64.188.1:8001
    GLUETUN_API_KEY       API key from the Gluetun auth config
    GLUETUN_ROTATE_EVERY  fetches per IP before proactive rotation (default 80)

Server side, Gluetun >= 3.40 needs /gluetun/auth/config.toml:

    [[roles]]
    name = "phasek"
    routes = [
      "GET /v1/publicip/ip",
      "GET /v1/openvpn/status",
      "PUT /v1/openvpn/status",
    ]
    auth = "apikey"
    apikey = "<generate a long random string>"
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_ROTATE_EVERY = 80
_SETTLE_TIMEOUT_S = 90
_POLL_INTERVAL_S = 3
_MAX_ROTATE_ATTEMPTS = 3


class RotationUnavailable(RuntimeError):
    """Rotation was requested but is not configured or not reachable."""


class GluetunController:
    """Minimal client for the Gluetun control server.

    Only the three routes needed for rotation are used, so the API key can be
    scoped narrowly rather than granting full control of the VPN container.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("GLUETUN_CONTROL_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("GLUETUN_API_KEY") or ""
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict:
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def _request(self, method: str, path: str, **kwargs):
        import requests

        if not self.configured:
            raise RotationUnavailable("GLUETUN_CONTROL_URL is not set")
        resp = requests.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(),
            timeout=self.timeout,
            **kwargs,
        )
        if resp.status_code == 401:
            raise RotationUnavailable(
                "Gluetun control API returned 401 — check GLUETUN_API_KEY and that "
                "/gluetun/auth/config.toml grants this route (see module docstring)"
            )
        resp.raise_for_status()
        return resp

    def public_ip(self) -> Optional[str]:
        """Current VPN exit IP, or None if it cannot be determined."""
        try:
            data = self._request("GET", "/v1/publicip/ip").json()
        except RotationUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gluetun public_ip failed: %s", exc)
            return None
        if isinstance(data, dict):
            return data.get("public_ip") or data.get("ip")
        return None

    def _set_status(self, status: str) -> None:
        """Set tunnel status, tolerating the openvpn/vpn route split across versions."""
        last: Exception | None = None
        for path in ("/v1/openvpn/status", "/v1/vpn/status"):
            try:
                self._request("PUT", path, json={"status": status})
                return
            except RotationUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise RuntimeError(f"could not set tunnel status to {status!r}: {last}")

    def _restart_tunnel(self) -> None:
        self._set_status("stopped")
        time.sleep(2)
        self._set_status("running")

    def _wait_for_change(self, before: Optional[str]) -> Optional[str]:
        deadline = time.time() + _SETTLE_TIMEOUT_S
        while time.time() < deadline:
            time.sleep(_POLL_INTERVAL_S)
            try:
                now = self.public_ip()
            except Exception:  # noqa: BLE001
                continue
            if now and now != before:
                return now
        return None

    def rotate(self, wait: bool = True, avoid: Optional[set] = None) -> Optional[str]:
        """Restart the tunnel so Gluetun picks a different server.

        ``avoid`` is a set of recently-used IPs. A provider may hold only a few
        servers per country, so a restart can hand back an address whose quota is
        already spent; when that happens this retries a couple of times. If it
        keeps landing on used IPs the pool is too small — widen
        ``SERVER_COUNTRIES`` in the Gluetun compose file rather than retrying
        harder, since a restart draws from whatever that filter allows.

        Returns the new exit IP, or None if it could not be confirmed. Raises
        ``RotationUnavailable`` when rotation is not configured — callers should
        treat that as "carry on without rotating", not as a fatal error.
        """
        avoid = avoid or set()
        before = self.public_ip()
        logger.info("Rotating Gluetun exit (current IP %s)", before or "unknown")

        for attempt in range(1, _MAX_ROTATE_ATTEMPTS + 1):
            self._restart_tunnel()
            if not wait:
                return None
            now = self._wait_for_change(before)
            if not now:
                logger.warning(
                    "Gluetun did not report a new IP within %ss (still %s); it may have "
                    "reconnected to the same server.", _SETTLE_TIMEOUT_S, before or "?"
                )
                return None
            if now not in avoid:
                logger.info("Gluetun rotated: %s -> %s", before or "?", now)
                return now
            logger.info(
                "Rotation %d/%d landed on recently-used IP %s; retrying",
                attempt, _MAX_ROTATE_ATTEMPTS, now,
            )
            before = now

        logger.warning(
            "Exhausted %d rotations still landing on used IPs — the server pool is "
            "too small. Add countries to SERVER_COUNTRIES in the Gluetun compose file.",
            _MAX_ROTATE_ATTEMPTS,
        )
        return before


class RotatingBudget:
    """Tracks fetches against a per-IP quota and rotates before it is reached.

    Proactive by design: tripping the quota costs hours, while rotating early
    costs a few seconds of reconnect.
    """

    def __init__(
        self,
        controller: Optional[GluetunController] = None,
        rotate_every: Optional[int] = None,
    ) -> None:
        self.controller = controller or GluetunController()
        env_every = os.environ.get("GLUETUN_ROTATE_EVERY")
        self.rotate_every = int(rotate_every or env_every or DEFAULT_ROTATE_EVERY)
        self.used = 0
        self.rotations = 0
        self.enabled = self.controller.configured
        # IPs whose quota this run has already spent — rotation must not reuse them.
        self.burned: set[str] = set()
        self.exhausted = False

    def record_fetch(self) -> None:
        """Count one live fetch, rotating if the budget for this IP is spent."""
        self.used += 1
        if not self.enabled or self.used < self.rotate_every:
            return
        self._try_rotate("budget reached")

    def on_blocked(self) -> bool:
        """Rotate in response to a block. Returns True if rotation happened."""
        if not self.enabled:
            return False
        return self._try_rotate("blocked")

    def _try_rotate(self, why: str) -> bool:
        try:
            current = self.controller.public_ip()
            if current:
                self.burned.add(current)
            new_ip = self.controller.rotate(avoid=self.burned)
        except RotationUnavailable as exc:
            logger.info("Rotation unavailable (%s); continuing without it", exc)
            self.enabled = False
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("Rotation failed (%s): %s", why, exc)
            return False

        if new_ip and new_ip in self.burned:
            # Every server the filter allows has now been used. Rotating again
            # cannot help; the caller should stop rather than burn IPs harder.
            self.exhausted = True
            print(f"    [rotation exhausted: only {len(self.burned)} distinct exit "
                  f"IP(s) available — widen SERVER_COUNTRIES]")
            return False

        if new_ip:
            self.burned.add(new_ip)
        self.used = 0
        self.rotations += 1
        print(f"    [rotated: {why} -> {new_ip or 'IP unconfirmed'} "
              f"({len(self.burned)} used this run)]")
        return True


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Gluetun rotation helper")
    ap.add_argument("action", choices=["ip", "rotate"])
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        from dotenv import load_dotenv
        from pathlib import Path

        env = Path(__file__).resolve().parent.parent / ".env"
        load_dotenv(env) if env.exists() else load_dotenv()
    except ImportError:
        pass

    c = GluetunController()
    if not c.configured:
        print("GLUETUN_CONTROL_URL is not set.")
        raise SystemExit(1)
    try:
        if args.action == "ip":
            print(c.public_ip() or "unknown")
        else:
            print(c.rotate() or "rotation completed, new IP unconfirmed")
    except RotationUnavailable as exc:
        print(f"unavailable: {exc}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
