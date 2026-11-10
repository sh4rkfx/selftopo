"""Push notifications

The Today card as a Web Push message: keys, the text in German and English, which subscriptions
count, what happens with expired ones, and that nothing is sent without the secret or without a
Today card for today. Sending itself is replaced by a stand-in; no message leaves the test.
"""

# ruff: noqa: E501

import base64
import json
import os
from datetime import date
from types import SimpleNamespace

import pytest
from jsdashboard import run as run_js

from selftopo import config, push

TODAY = date(2026, 11, 10)
WORDS = push.dictionary()
SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "BPk", "auth": "xyz"}, "lang": "en"}

RECO = {
    "as_of": "2026-11-10",
    "today": {
        "title": {"text": "Heute locker statt schwer"},
        "reasons": [{"text": "Readiness {0}", "vars": [{"n": 31, "d": 0}]}],
        "why": {"text": "Schlechte Erholung plus harte Einheit erhöht das Risiko für Übertraining und Infekte."},
    },
}


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def test_keys_have_the_formats_the_browser_and_pywebpush_need(given):
    """Public key: 65-byte uncompressed P-256 point; private key: 32 raw bytes. Both base64url without padding."""
    pytest.importorskip("py_vapid")
    public, private = push.generate_keys()
    given(public=public[:12] + "…", private="(32 bytes)")
    assert len(_unb64(public)) == 65 and _unb64(public)[0] == 4
    assert len(_unb64(private)) == 32
    assert "=" not in public + private
    from py_vapid import Vapid02
    assert Vapid02.from_raw(private.encode()).public_key is not None


def test_message_texts_in_german_and_english(given):
    """The texts of recommendations.json filled in; English from the dashboard dictionary."""
    given(card="Today card: readiness 31")
    de = push.message(RECO, TODAY, "de", WORDS)
    en = push.message(RECO, TODAY, "en", WORDS)
    assert de["title"] == "Heute locker statt schwer" and de["body"].startswith("Readiness 31\n")
    assert en["title"] != de["title"] and "Readiness 31" in en["body"]
    assert de["tag"] == "selftopo-today-2026-11-10" and de["url"] == "./#top"


def test_numbers_dates_and_lists_are_formatted_per_language(given):
    """1234,5 / 1,234.5, 31.03. / 31/03, minus sign, list of muscles."""
    template = {"text": "{0} {1} {2} {3}", "vars": [{"n": 1234.5, "d": 1}, {"date": "2027-03-31"}, {"n": -0.23, "d": 2}, {"list": [{"muscle": "upper_back"}, {"muscle": "chest"}]}]}
    given(template=template["text"])
    assert push.render(template, "de", {}) == "1.234,5 31.03. −0,23 upper back, chest"
    assert push.render(template, "en", {}) == "1,234.5 31/03 −0.23 upper back, chest"


def test_no_message_without_a_today_card_for_today(given):
    """A Today card from yesterday or no card at all: nothing to send."""
    given(as_of="2026-11-09 vs today 2026-11-10")
    assert push.message({**RECO, "as_of": "2026-11-09"}, TODAY, "de", WORDS) is None
    assert push.message({"as_of": "2026-11-10", "today": None}, TODAY, "de", WORDS) is None


def test_incomplete_subscriptions_are_skipped(given):
    """Only entries with an https endpoint and both keys count."""
    settings = {"push": {"subscriptions": [SUB, {"endpoint": "http://x", "keys": SUB["keys"]}, {"endpoint": "https://y"}, "junk"]}}
    given(subscriptions=4)
    assert push.subscriptions(settings) == [SUB]
    assert push.subscriptions({}) == [] and push.subscriptions({"push": "x"}) == []


@pytest.fixture
def fake_webpush(monkeypatch):
    """Replace pywebpush.webpush; endpoints containing 'gone' answer 410, 'bad' 500."""
    pywebpush = pytest.importorskip("pywebpush")
    sent = []

    def webpush(info, data, **kwargs):
        if "gone" in info["endpoint"]:
            raise pywebpush.WebPushException("gone", response=SimpleNamespace(status_code=410))
        if "bad" in info["endpoint"]:
            raise pywebpush.WebPushException("bad", response=SimpleNamespace(status_code=500))
        sent.append({"endpoint": info["endpoint"], "payload": json.loads(data), **kwargs})

    monkeypatch.setattr(pywebpush, "webpush", webpush)
    return sent


def test_expired_subscriptions_are_counted_not_fatal(fake_webpush, given):
    """HTTP 410 counts as expired, 500 as failed; the others still get their message."""
    entries = [SUB, {**SUB, "endpoint": "https://push.example/gone"}, {**SUB, "endpoint": "https://push.example/bad", "lang": "de"}]
    given(endpoints="ok, gone (410), bad (500)")
    counts = push.send(entries, push.test_message, "private")
    assert counts == {"sent": 1, "gone": 1, "failed": 1}
    assert fake_webpush[0]["payload"]["title"] == "selftopo: test" and fake_webpush[0]["ttl"] == push.TTL_S


def _setup(tmp_path, monkeypatch, settings, reco=RECO, key="private"):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SETTINGS", settings)
    if reco is not None:
        (tmp_path / "recommendations.json").write_text(json.dumps(reco), encoding="utf-8")
    if key:
        monkeypatch.setenv("VAPID_PRIVATE_KEY", key)
    else:
        monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)


def test_run_sends_the_today_card_in_each_devices_language(tmp_path, monkeypatch, fake_webpush, given):
    """Two devices, German and English: each gets the card in its language."""
    _setup(tmp_path, monkeypatch, {"push": {"subscriptions": [SUB, {**SUB, "endpoint": "https://push.example/de", "lang": "de"}]}})
    given(devices="en, de")
    assert push.run(today=TODAY) == {"sent": 2, "gone": 0, "failed": 0}
    titles = {s["endpoint"]: s["payload"]["title"] for s in fake_webpush}
    assert titles["https://push.example/de"] == "Heute locker statt schwer"
    assert titles["https://push.example/abc"] == WORDS.get("Heute locker statt schwer")


def test_run_sends_nothing_without_secret_card_or_device(tmp_path, monkeypatch, fake_webpush, given):
    """No VAPID_PRIVATE_KEY, no Today card for today, or no subscription: None and no message."""
    given(cases="no secret, no card today, no device")
    _setup(tmp_path, monkeypatch, {"push": {"subscriptions": [SUB]}}, key=None)
    assert push.run(today=TODAY) is None
    _setup(tmp_path, monkeypatch, {"push": {"subscriptions": [SUB]}}, reco={**RECO, "today": None})
    assert push.run(today=TODAY) is None
    _setup(tmp_path, monkeypatch, {})
    assert push.run(today=TODAY) is None
    assert fake_webpush == []


def test_run_test_sends_a_test_message_even_without_a_card(tmp_path, monkeypatch, fake_webpush, given):
    """push --test: checks the setup on days without a Today card."""
    _setup(tmp_path, monkeypatch, {"push": {"subscriptions": [SUB]}}, reco=None)
    given(flag="--test")
    assert push.run(test=True, today=TODAY)["sent"] == 1
    assert fake_webpush[0]["payload"]["tag"] == "selftopo-test"


def test_dashboard_keeps_other_devices_when_saving(given):
    """Saving settings adds this device and removes only the one turned off; the public key is kept."""
    given(saved="device A, device B", change="add C, remove A")
    out = run_js(
        ["applyPush"],
        """(() => {
          globalThis.pushDraft = { add: [{ endpoint: "C" }], remove: ["A"] };
          globalThis.$ = () => ({ value: " BKEY " });
          return applyPush({ push: { subscriptions: [{ endpoint: "A" }, { endpoint: "B" }] } });
        })()""",
    )
    assert out == {"push": {"public_key": "BKEY", "subscriptions": [{"endpoint": "B"}, {"endpoint": "C"}]}}


def test_every_push_text_has_an_english_translation(given):
    """The texts the push UI writes with T(...) are in the dictionary."""
    import re

    html = (push.DASHBOARD).read_text(encoding="utf-8")
    block = html[html.index("function applyPush"):html.index("function setupPush")]
    texts = re.findall(r'T\("((?:[^"\\]|\\.)*)"\)', block)
    given(texts=len(texts))
    assert texts and [t for t in texts if t not in WORDS] == []


def test_real_signing_and_encryption_reach_the_push_service(monkeypatch, given):
    """pywebpush for real, only the HTTP post replaced: VAPID header with our key and subject, aes128gcm body."""
    pywebpush = pytest.importorskip("pywebpush")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    public, private = push.generate_keys()
    device = ec.generate_private_key(ec.SECP256R1())
    p256dh = base64.urlsafe_b64encode(device.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).rstrip(b"=").decode()
    auth = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()
    posted = []

    def post(url, data=None, headers=None, timeout=None, **kwargs):
        posted.append({"url": url, "data": data, "headers": headers})
        return SimpleNamespace(status_code=201, text="", headers={})

    monkeypatch.setattr(pywebpush.requests, "post", post)
    monkeypatch.setenv("GITHUB_REPOSITORY", "Some-User/selftopo-data")
    monkeypatch.delenv("GITHUB_REPOSITORY_OWNER", raising=False)
    given(endpoint="https://web.push.apple.com/…", subject=push.subject())
    counts = push.send([{"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": p256dh, "auth": auth}}], push.test_message, private)
    assert counts == {"sent": 1, "gone": 0, "failed": 0}
    assert push.subject() == "https://some-user.github.io"
    headers = posted[0]["headers"]
    assert headers["content-encoding"] == "aes128gcm" and int(headers["ttl"]) == push.TTL_S
    assert f"k={public}" in headers["authorization"].replace(" ", "")
    assert b"selftopo" not in posted[0]["data"]
