"""Rotate the egress VPN exit when YouTube blocks the current IP.

YouTube rate-limits caption fetches per egress IP (~90/day was the figure §14
inferred from one IP, and that number is an estimate we have never re-measured).
The fix is not to ration fetches — it is to notice a block and move to a new exit.

The VPN is Gluetun (``qmcgaw/gluetun``) on ts-ubuntu-server, PureVPN over OpenVPN,
pinned to ``SERVER_COUNTRIES=Netherlands``. Gluetun picks a server from that
country's pool on each connect, so **restarting the tunnel is the rotation** — no
server list to manage here.

Two backends, chosen by ``YOUTUBE_PROXY_ROTATE_MODE``:

``control`` (default, preferred)
    Gluetun's HTTP control server. Needs ``YOUTUBE_PROXY_CONTROL_URL`` and a role
    with the ``vpn`` and ``publicip`` routes in ``/gluetun/auth/config.toml``,
    supplied as ``YOUTUBE_PROXY_CONTROL_APIKEY``. Works from anywhere that can
    reach the control port, including inside a container.

``ssh``
    ``docker restart gluetun`` over SSH. Verified safe: ``gluetun`` sits alone on
    the ``gluetun_default`` network, so no other container loses its network when
    it bounces. Useful from a workstation that has an agent key but no API key.

``off``
    Never rotate. Blocks stay blocks.

Every rotation is logged with before/after exit IP so the real per-IP ceiling can
be measured from history instead of guessed once.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_MODE_ENV = "YOUTUBE_PROXY_ROTATE_MODE"
_CONTROL_URL_ENV = "YOUTUBE_PROXY_CONTROL_URL"
_CONTROL_KEY_ENV = "YOUTUBE_PROXY_CONTROL_APIKEY"
_SSH_HOST_ENV = "YOUTUBE_PROXY_SSH_HOST"
_CONTAINER_ENV = "YOUTUBE_PROXY_CONTAINER"
_MAX_ROTATIONS_ENV = "YOUTUBE_PROXY_MAX_ROTATIONS"

_DEFAULT_CONTAINER = "gluetun"
_DEFAULT_MAX_ROTATIONS = 3

# Gluetun needs time to tear down and re-establish the tunnel. These bound the
# wait; a rotation that has not produced a new IP by then is reported failed
# rather than silently reusing the blocked exit.
_SETTLE_POLL_S = 3.0
_SETTLE_TIMEOUT_S = 90.0


class RotationError(RuntimeError):
    """Rotation was attempted and did not produce a working new exit."""


@dataclass(frozen=True)
class RotationResult:
    old_ip: Optional[str]
    new_ip: Optional[str]
    mode: str
    seconds: float

    @property
    def changed(self) -> bool:
        return bool(self.new_ip) and self.new_ip != self.old_ip


def rotation_mode() -> str:
    """Configured backend; ``off`` disables rotation entirely."""
    return (os.environ.get(_MODE_ENV) or "off").strip().lower()


def max_rotations() -> int:
    """How many exits to try before giving up on a single fetch."""
    raw = (os.environ.get(_MAX_ROTATIONS_ENV) or "").strip()
    try:
        return max(int(raw), 0) if raw else _DEFAULT_MAX_ROTATIONS
    except ValueError:
        return _DEFAULT_MAX_ROTATIONS


def rotation_enabled() -> bool:
    return rotation_mode() not in ("", "off", "none", "0", "false")


def current_exit_ip(timeout: float = 15.0) -> Optional[str]:
    """Public IP as seen through the proxy, or None if it cannot be determined."""
    from yt_captions import caption_proxy_url

    proxy = caption_proxy_url()
    if not proxy:
        return None
    try:
        import requests

        resp = requests.get(
            "https://api.ipify.org",
            proxies={"http": proxy, "https": proxy},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.text.strip() or None
    except Exception as exc:
        logger.debug("Could not read exit IP: %s", exc)
        return None


def _control_request(path: str, method: str = "GET", payload: dict | None = None):
    import requests

    base = (os.environ.get(_CONTROL_URL_ENV) or "").strip().rstrip("/")
    if not base:
        raise RotationError(f"{_CONTROL_URL_ENV} is not set")
    key = (os.environ.get(_CONTROL_KEY_ENV) or "").strip()
    headers = {"X-API-Key": key} if key else {}
    resp = requests.request(
        method, f"{base}{path}", headers=headers, json=payload, timeout=30
    )
    if resp.status_code in (401, 403):
        raise RotationError(
            f"control server rejected the API key ({resp.status_code}); check the "
            f"role for {path} in /gluetun/auth/config.toml"
        )
    resp.raise_for_status()
    return resp


def _rotate_via_control() -> None:
    """Stop and restart the tunnel; Gluetun reconnects to a new server."""
    _control_request("/v1/vpn/status", "PUT", {"status": "stopped"})
    time.sleep(2)
    _control_request("/v1/vpn/status", "PUT", {"status": "running"})


def _rotate_via_ssh() -> None:
    """``docker restart`` the VPN container over SSH."""
    host = (os.environ.get(_SSH_HOST_ENV) or "").strip()
    if not host:
        raise RotationError(f"{_SSH_HOST_ENV} is not set")
    container = (os.environ.get(_CONTAINER_ENV) or _DEFAULT_CONTAINER).strip()
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            host,
            f"docker restart {container}",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RotationError(
            f"docker restart {container} failed on {host}: "
            f"{(proc.stderr or proc.stdout).strip()[:200]}"
        )


def rotate_exit(*, wait: bool = True) -> RotationResult:
    """Move to a new VPN exit. Raises :class:`RotationError` if it does not change.

    Callers should treat a raised error as "still blocked" and stop retrying, not
    as a reason to hammer the same exit.
    """
    mode = rotation_mode()
    if not rotation_enabled():
        raise RotationError(f"{_MODE_ENV} is '{mode}'; rotation is disabled")

    started = time.monotonic()
    old_ip = current_exit_ip()

    if mode == "control":
        _rotate_via_control()
    elif mode == "ssh":
        _rotate_via_ssh()
    else:
        raise RotationError(f"unknown {_MODE_ENV}={mode!r} (use control, ssh, or off)")

    new_ip: Optional[str] = None
    if wait:
        deadline = time.monotonic() + _SETTLE_TIMEOUT_S
        while time.monotonic() < deadline:
            time.sleep(_SETTLE_POLL_S)
            new_ip = current_exit_ip(timeout=10.0)
            if new_ip and new_ip != old_ip:
                break
        else:
            raise RotationError(
                f"exit IP did not change within {_SETTLE_TIMEOUT_S:.0f}s (still {old_ip})"
            )
        if not new_ip or new_ip == old_ip:
            raise RotationError(f"exit IP did not change (still {old_ip})")

    elapsed = time.monotonic() - started
    result = RotationResult(old_ip=old_ip, new_ip=new_ip, mode=mode, seconds=elapsed)
    # Logged at INFO on purpose: rotation history is the only way to learn the
    # real per-IP fetch ceiling, which §14 only ever estimated.
    logger.info(
        "Rotated YouTube egress via %s: %s -> %s in %.1fs",
        mode,
        old_ip or "unknown",
        new_ip or "unknown",
        elapsed,
    )
    return result
