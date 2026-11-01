"""The dashboard's English dictionary covers every text the script translates."""

import json
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "dashboard" / "index.html").read_text(encoding="utf-8")


def dictionary() -> dict[str, str]:
    block = re.search(r'<script type="application/json" id="i18n-en">(.*?)</script>', HTML, re.S)
    assert block, "i18n-en block missing"
    return json.loads(block.group(1))


def script() -> str:
    return HTML[HTML.rindex("<script>"):]


def test_dictionary_is_valid_and_has_no_empty_entries():
    d = dictionary()
    assert len(d) > 1000
    assert not [k for k, v in d.items() if not v.strip()]


def test_every_translated_literal_has_an_english_entry():
    d = dictionary()
    keys = {json.loads(f'"{m}"') for m in re.findall(r'\bT\("((?:[^"\\]|\\.)*)"', script())}
    missing = sorted(k for k in keys if k not in d)
    assert not missing, f"add these to the i18n-en block: {missing[:10]}"


def test_placeholders_match():
    d = dictionary()
    wrong = [k for k, v in d.items() if sorted(re.findall(r"\{\d+\}", k)) != sorted(re.findall(r"\{\d+\}", v))]
    assert not wrong, wrong[:5]


def test_service_worker_has_a_version():
    sw = (Path(__file__).resolve().parent.parent / "dashboard" / "sw.js").read_text(encoding="utf-8")
    assert re.search(r'const VERSION = "\d+";', sw)
