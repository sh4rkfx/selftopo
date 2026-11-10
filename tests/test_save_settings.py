"""Saving settings from the dashboard

With a token that may write ("Contents: Read and write"), "Save" commits settings.json to the data
repository through the GitHub API. The page's own writeSettings runs in Node against a stand-in
for GitHub; without Node these tests are skipped.
"""

# ruff: noqa: E501

import json

from jsdashboard import run_async as run

NAMES = ["b64Encode", "b64Decode", "changedKeys", "writeProblem", "writeSettings"]


def save(files: dict, responses: list, form: dict | None = None, source: str = "github"):
    """files: settings.json on 'GitHub' (None = missing); responses: status codes for the PUTs in order."""
    setup = f"""
    globalThis.state = {{ source: {json.dumps(source)}, dataRepo: "me/data", dataBranch: "main" }};
    globalThis.calls = [];
    let current = {json.dumps(files)};
    const puts = {json.dumps(responses)};
    const encode = (t) => Buffer.from(t, "utf8").toString("base64");
    globalThis.githubRequest = async (cred, path) => {{
      calls.push(["GET", path]);
      if (current === null) return {{ ok: false, status: 404 }};
      return {{ ok: true, status: 200, json: async () => ({{ sha: current.sha, content: encode(current.text).replace(/(.{{60}})/g, "$1\\n") }}) }};
    }};
    globalThis.fetch = async (url, init) => {{
      const body = JSON.parse(init.body);
      const status = puts.shift();
      calls.push(["PUT", url, body.message, body.sha || null, body.branch, Buffer.from(body.content, "base64").toString("utf8"), init.headers.Authorization]);
      if (status === 409 && current) current = {{ sha: "sha-2", text: JSON.stringify({{ ...JSON.parse(current.text), timezone: "Europe/Berlin" }}) }};
      return {{ ok: status < 300, status }};
    }};
    const FORM = {json.dumps(form or {})};
    globalThis.settingsFromForm = (base) => ({{ ...base, ...FORM }});
    globalThis.loadCredentials = () => ({{ repo: "me/data", token: "github_pat_x" }});
    """
    return run(NAMES, f"(async () => {{ {setup} const result = await writeSettings(); return {{ result, calls }}; }})()")


def test_save_commits_settings_with_the_form_on_top(given):
    """The current file is read first; the form's keys go on top, unknown keys stay, the commit names what changed."""
    given(file='{"timezone": "Europe/Vienna", "custom": 1}', form="goals")
    out = save({"sha": "sha-1", "text": '{"timezone": "Europe/Vienna", "custom": 1}'}, [200], {"goals": {"koerper": {"metric": "weight", "target": 75}}})
    assert out["result"] == {"ok": True, "keys": ["goals"]}
    put = out["calls"][1]
    assert put[0] == "PUT" and put[1] == "https://api.github.com/repos/me/data/contents/settings.json"
    assert put[2] == "Dashboard: update settings (goals)" and put[3] == "sha-1" and put[4] == "main"
    saved = json.loads(put[5])
    assert saved == {"timezone": "Europe/Vienna", "custom": 1, "goals": {"koerper": {"metric": "weight", "target": 75}}}
    assert put[5].endswith("}\n") and put[6] == "Bearer github_pat_x"


def test_missing_file_is_created(given):
    """No settings.json yet: created without sha."""
    given(file="(missing)")
    out = save(None, [201], {"timezone": "Europe/Berlin"})
    assert out["result"]["ok"] and out["calls"][1][3] is None
    assert json.loads(out["calls"][1][5]) == {"timezone": "Europe/Berlin"}


def test_nothing_changed_writes_nothing(given):
    """Same content as on GitHub: no commit."""
    given(file='{"step_goal": 9000}', form='{"step_goal": 9000}')
    out = save({"sha": "s", "text": '{"step_goal": 9000}'}, [], {"step_goal": 9000})
    assert out["result"] == {"ok": True, "keys": []}
    assert [c[0] for c in out["calls"]] == ["GET"]


def test_change_from_another_device_is_kept(given):
    """The file changed between reading and writing (409): read again, put the form on top, write once more."""
    given(conflict="another device set the time zone meanwhile")
    out = save({"sha": "sha-1", "text": '{"step_goal": 8000}'}, [409, 200], {"step_goal": 10000})
    assert out["result"]["ok"]
    assert [c[0] for c in out["calls"]] == ["GET", "PUT", "GET", "PUT"]
    last = out["calls"][3]
    assert last[3] == "sha-2" and json.loads(last[5]) == {"step_goal": 10000, "timezone": "Europe/Berlin"}


def test_read_only_token_falls_back(given):
    """403 on writing: reported as read-only, with how to grant write access."""
    given(token="Contents: Read-only")
    out = save({"sha": "s", "text": "{}"}, [403], {"step_goal": 9000})
    assert out["result"]["readOnly"] is True and "Read and write" in out["result"]["error"]


def test_unreadable_file_is_replaced_and_umlauts_survive(given):
    """A broken settings.json is replaced; non-ASCII text round-trips through base64."""
    given(file="not JSON", form="label with umlaut")
    out = save({"sha": "s", "text": "{nope"}, [200], {"main_lifts": [{"exercise": "Kniebeuge", "label": "Kniebeuge (Langhantel) – schwer"}]})
    assert out["result"]["ok"]
    assert json.loads(out["calls"][1][5])["main_lifts"][0]["label"] == "Kniebeuge (Langhantel) – schwer"


def test_only_with_a_connected_repository(given):
    """Sample data or local files: nothing is sent."""
    given(source="demo")
    out = save({"sha": "s", "text": "{}"}, [], {"step_goal": 9000}, source="demo")
    assert "error" in out["result"] and out["calls"] == []
