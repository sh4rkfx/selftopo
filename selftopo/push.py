"""Push notifications: the Today card as a message to the installed dashboard.

Web Push with VAPID keys, no server of selftopo involved. `python -m selftopo push-keys` makes
the key pair once: the private key goes into the GitHub secret VAPID_PRIVATE_KEY of the data
repository, the public key into settings.json ("push": {"public_key": ...}) through the
dashboard. Each device that turns notifications on adds its subscription to settings.json
("push": {"subscriptions": [...]}). After the daily analysis, `python -m selftopo push` sends the
Today card of recommendations.json to every subscription, in the language the device chose.
Without the secret, a subscription or a Today card, it sends nothing.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger(__name__)

DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"
TTL_S = 12 * 3600  # a Today card older than half a day is not worth delivering


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate_keys() -> tuple[str, str]:
    """(public, private) VAPID key pair, both base64url: public as the browser needs it, private raw."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02

    vapid = Vapid02()
    vapid.generate_keys()
    public = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    return _b64(public), _b64(private)


# --------------------------------------------------------------------------- message


def dictionary(path: Path = DASHBOARD) -> dict[str, str]:
    """The dashboard's English dictionary, so a message reads like the page in that language."""
    try:
        html = path.read_text(encoding="utf-8")
        block = re.search(r'<script type="application/json" id="i18n-en">(.*?)</script>', html, re.S)
        return json.loads(block.group(1)) if block else {}
    except (OSError, ValueError):
        return {}


def _number(value: float, decimals: int, lang: str) -> str:
    text = f"{abs(value):,.{decimals}f}"
    if lang == "de":
        text = text.replace(",", " ").replace(".", ",").replace(" ", ".")
    return ("−" if value < 0 and round(abs(value), decimals) > 0 else "") + text


def render(template: dict[str, Any] | None, lang: str, words: dict[str, str]) -> str:
    """A text of recommendations.json in the given language ("de" or "en"), values filled in."""
    if not template or not template.get("text"):
        return ""
    translate = (lambda s: words.get(s, s)) if lang == "en" else (lambda s: s)

    def value(v: Any) -> str:
        if not isinstance(v, dict):
            return str(v)
        if "n" in v:
            return _number(float(v["n"]), int(v.get("d") or 0), lang)
        if "date" in v:
            d = date.fromisoformat(v["date"])
            return f"{d.day:02d}.{d.month:02d}." if lang == "de" else f"{d.day:02d}/{d.month:02d}"
        if "clock" in v:
            return str(v["clock"])
        if "t" in v:
            return translate(str(v["t"]))
        if "muscle" in v:
            return str(v["muscle"]).replace("_", " ")
        if "list" in v:
            return ", ".join(value(x) for x in v["list"])
        if "text" in v:
            return render(v, lang, words)
        return ""

    out = translate(template["text"])
    values = [value(v) for v in template.get("vars") or []]
    return re.sub(r"\{(\d+)\}", lambda m: values[int(m.group(1))] if int(m.group(1)) < len(values) else m.group(0), out)


def message(recommendations: dict[str, Any], today: date, lang: str, words: dict[str, str]) -> dict[str, Any] | None:
    """The notification for today's Today card, or None when there is none for today."""
    card = recommendations.get("today")
    if not card or recommendations.get("as_of") != today.isoformat():
        return None
    reasons = " · ".join(render(r, lang, words) for r in card.get("reasons") or [])
    return {
        "title": render(card["title"], lang, words),
        "body": "\n".join(x for x in (reasons, render(card.get("why"), lang, words)) if x),
        "url": "./#top",
        "tag": f"selftopo-today-{today.isoformat()}",
    }


def test_message(lang: str) -> dict[str, Any]:
    if lang == "en":
        title, body = "selftopo: test", "Push notifications work on this device."
    else:
        title, body = "selftopo: Test", "Push-Benachrichtigungen kommen auf diesem Gerät an."
    return {"title": title, "body": body, "url": "./", "tag": "selftopo-test"}


# --------------------------------------------------------------------------- sending


def subscriptions(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Valid subscriptions from settings.json; incomplete entries are skipped with a warning."""
    push = settings.get("push") if isinstance(settings.get("push"), dict) else {}
    out = []
    for entry in push.get("subscriptions") or []:
        keys = entry.get("keys") if isinstance(entry, dict) else None
        if not (isinstance(entry, dict) and str(entry.get("endpoint", "")).startswith("https://")
                and isinstance(keys, dict) and keys.get("p256dh") and keys.get("auth")):
            log.warning("push: a subscription in settings.json is incomplete and skipped")
            continue
        out.append(entry)
    return out


def subject() -> str:
    """Contact the push services may use, required by VAPID: the owner's GitHub Pages host, no e-mail.

    py_vapid (and Apple) accept only mailto: or a bare https origin, no path.
    """
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or os.environ.get("GITHUB_REPOSITORY", "").split("/")[0]
    owner = re.sub(r"[^a-z0-9-]", "", owner.lower())
    return f"https://{owner or 'sh4rkfx'}.github.io"


def send(entries: list[dict[str, Any]], build, private_key: str) -> dict[str, int]:
    """Send build(lang) to every subscription. Returns counts of sent, gone (expired) and failed."""
    from pywebpush import WebPushException, webpush

    counts = {"sent": 0, "gone": 0, "failed": 0}
    for entry in entries:
        payload = build(entry.get("lang") if entry.get("lang") in ("de", "en") else "de")
        info = {"endpoint": entry["endpoint"], "keys": entry["keys"]}
        try:
            webpush(info, json.dumps(payload, ensure_ascii=False), vapid_private_key=private_key,
                    vapid_claims={"sub": subject()}, ttl=TTL_S, timeout=20)
            counts["sent"] += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                counts["gone"] += 1
                log.warning("push: a subscription has expired (HTTP %s); turn notifications on again on that device",
                            status)
            else:
                counts["failed"] += 1
                log.warning("push: sending failed (HTTP %s)", status)
        except Exception as exc:  # bad key, network: one device must not stop the others
            counts["failed"] += 1
            log.warning("push: sending failed (%s)", type(exc).__name__)
    return counts


def run(test: bool = False, today: date | None = None) -> dict[str, int] | None:
    """Send today's Today card (or a test message). None when there was nothing to do."""
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    entries = subscriptions(config.SETTINGS)
    if not private_key:
        if entries:
            log.warning("push: subscriptions exist, but the secret VAPID_PRIVATE_KEY is not set")
        return None
    if not entries:
        log.info("push: no device has turned notifications on")
        return None
    words = dictionary()
    if test:
        return send(entries, test_message, private_key)
    try:
        recommendations = json.loads((config.DATA_DIR / "recommendations.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.info("push: no recommendations.json")
        return None
    today = today or config.today()
    if message(recommendations, today, "de", words) is None:
        log.info("push: no Today card for %s, nothing sent", today)
        return None
    counts = send(entries, lambda lang: message(recommendations, today, lang, words), private_key)
    log.info("push: %d sent, %d expired, %d failed", counts["sent"], counts["gone"], counts["failed"])
    return counts
