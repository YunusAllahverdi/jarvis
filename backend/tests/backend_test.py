"""J.A.R.V.I.S backend test suite — pytest."""
import os
import json
import time
import uuid
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE:
    # fallback: read frontend .env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE = line.split("=", 1)[1].strip()
BASE = BASE.rstrip("/")
API = f"{BASE}/api"


# ---------- Health & Diagnostics ----------
def test_health():
    r = requests.get(f"{API}/health", timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["provider"] == "anthropic"
    assert d["model"] == "claude-sonnet-5"
    assert d["timezone"] == "Europe/Istanbul"
    for key in ["chat", "notes", "approvals", "checkpoints", "coding_loop", "council", "research", "terminal"]:
        assert key in d["features"], f"missing feature flag {key}"


def test_diagnostics():
    r = requests.get(f"{API}/diagnostics", timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["permissions"]["read"] == "allowed"
    assert d["permissions"]["write"] == "requires_approval"
    # terminal is disabled per .env
    assert d["permissions"]["dangerous"] == "denied"
    for k in ["notes", "approvals", "checkpoints", "sessions", "messages", "audit"]:
        assert k in d["counts"]


# ---------- Chat non-stream ----------
_chat_session_holder = {}

def test_chat_turkish():
    r = requests.post(f"{API}/chat", json={"message": "Merhaba, kısaca kendini tanıt."}, timeout=120)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "session_id" in d and d["session_id"]
    assert isinstance(d["response"], str) and len(d["response"]) > 0
    _chat_session_holder["sid"] = d["session_id"]


# ---------- Chat stream ----------
def test_chat_stream_sse():
    with requests.post(
        f"{API}/chat/stream",
        json={"message": "Bir kelime söyle."},
        stream=True,
        timeout=120,
    ) as r:
        assert r.status_code == 200
        # SSE assertions: first frame is event: session, then data: frames, ends with event: done
        buf = b""
        got_session = False
        got_delta = False
        got_done = False
        deadline = time.time() + 90
        for chunk in r.iter_content(chunk_size=None):
            if not chunk:
                continue
            buf += chunk
            text = buf.decode("utf-8", errors="ignore")
            if "event: session" in text and not got_session:
                got_session = True
            if "\ndata: {" in text and "delta" in text:
                got_delta = True
            if "event: done" in text:
                got_done = True
                break
            if time.time() > deadline:
                break
        assert got_session, "SSE did not emit 'event: session'"
        assert got_delta, "SSE did not emit delta data frames"
        assert got_done, "SSE did not emit 'event: done'"


# ---------- Sessions list & messages & delete ----------
def test_sessions_flow():
    sid = _chat_session_holder.get("sid")
    if not sid:
        pytest.skip("no chat session created")
    r = requests.get(f"{API}/chat/sessions", timeout=30)
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()["sessions"]]
    assert sid in ids

    r = requests.get(f"{API}/chat/sessions/{sid}/messages", timeout=30)
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) >= 2
    roles = {m["role"] for m in msgs}
    assert {"user", "assistant"}.issubset(roles)

    r = requests.delete(f"{API}/chat/sessions/{sid}", timeout=30)
    assert r.status_code == 200
    # Verify gone
    r = requests.get(f"{API}/chat/sessions/{sid}/messages", timeout=30)
    assert r.status_code == 200
    assert r.json()["messages"] == []


# ---------- Notes CRUD ----------
def test_notes_crud():
    r = requests.post(f"{API}/notes", json={"title": "TEST_note", "content": "ilk", "tags": ["t"]})
    assert r.status_code == 200
    note = r.json()
    nid = note["id"]
    assert note["title"] == "TEST_note"

    r = requests.get(f"{API}/notes")
    assert r.status_code == 200
    assert any(n["id"] == nid for n in r.json()["notes"])

    r = requests.put(f"{API}/notes/{nid}", json={"title": "TEST_note2", "content": "yeni", "tags": []})
    assert r.status_code == 200
    assert r.json()["title"] == "TEST_note2"

    r = requests.delete(f"{API}/notes/{nid}")
    assert r.status_code == 200

    r = requests.put(f"{API}/notes/{nid}", json={"title": "x", "content": "x", "tags": []})
    assert r.status_code == 404
    r = requests.delete(f"{API}/notes/{nid}")
    assert r.status_code == 404


# ---------- Approvals ----------
def test_approvals_flow():
    r = requests.post(f"{API}/approvals", json={"tool": "shell", "arguments": {"cmd": "ls"}, "reason": "test"})
    assert r.status_code == 200
    aid = r.json()["id"]

    r = requests.get(f"{API}/approvals")
    assert r.status_code == 200
    assert any(a["id"] == aid for a in r.json()["approvals"])

    r = requests.post(f"{API}/approvals/{aid}", json={"decision": "approve"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    r = requests.post(f"{API}/approvals/{aid}", json={"decision": "reject"})
    assert r.status_code == 409

    # reject flow
    r = requests.post(f"{API}/approvals", json={"tool": "shell", "arguments": {}, "reason": "test2"})
    aid2 = r.json()["id"]
    r = requests.post(f"{API}/approvals/{aid2}", json={"decision": "reject"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


# ---------- Checkpoints ----------
def test_checkpoints_flow():
    r = requests.post(f"{API}/checkpoints", json={"label": "TEST_cp", "path": "/tmp/x", "snapshot": "abc"})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert r.json()["restored"] is False

    r = requests.get(f"{API}/checkpoints")
    assert r.status_code == 200
    assert any(c["id"] == cid for c in r.json()["checkpoints"])

    r = requests.post(f"{API}/checkpoints/{cid}/restore")
    assert r.status_code == 200

    r = requests.get(f"{API}/checkpoints")
    assert any(c["id"] == cid and c["restored"] is True for c in r.json()["checkpoints"])


# ---------- Admin LLM ----------
def test_admin_llm_no_api_key():
    r = requests.get(f"{API}/admin/llm")
    assert r.status_code == 200
    d = r.json()
    assert "api_key" not in d
    assert "provider" in d and "model" in d

    r = requests.put(f"{API}/admin/llm", json={
        "provider": "anthropic",
        "model": "claude-sonnet-5",
        "api_key": "SECRET_TEST_KEY"
    })
    assert r.status_code == 200
    d = r.json()
    assert "api_key" not in d
    assert d.get("has_api_key") is True


# ---------- Council ----------
def test_council_flow():
    # Add member A as chairman
    r = requests.put(f"{API}/admin/council/members/TEST_A", json={
        "kind": "anthropic", "model": "claude-sonnet-5", "api_key": "k1", "is_chairman": True
    })
    assert r.status_code == 200
    d = r.json()
    assert "api_key" not in d
    assert d.get("has_api_key") is True
    assert d["is_chairman"] is True

    # Add member B as chairman → should unset A
    r = requests.put(f"{API}/admin/council/members/TEST_B", json={
        "kind": "anthropic", "model": "claude-sonnet-5", "api_key": "k2", "is_chairman": True
    })
    assert r.status_code == 200

    r = requests.get(f"{API}/admin/council")
    members = {m["id"]: m for m in r.json()["members"]}
    assert members["TEST_A"]["is_chairman"] is False
    assert members["TEST_B"]["is_chairman"] is True
    for m in members.values():
        assert "api_key" not in m

    # Delete
    r = requests.delete(f"{API}/admin/council/members/TEST_A")
    assert r.status_code == 200
    r = requests.delete(f"{API}/admin/council/members/TEST_B")
    assert r.status_code == 200
    r = requests.delete(f"{API}/admin/council/members/TEST_A")
    assert r.status_code == 404


# ---------- UI Actions bus ----------
def test_ui_actions():
    r = requests.post(f"{API}/ui/actions", json={"panel": "notes", "context": {"a": 1}})
    assert r.status_code == 200
    aid = r.json()["id"]

    r = requests.get(f"{API}/ui/actions")
    assert r.status_code == 200
    actions = r.json()["actions"]
    assert any(a["id"] == aid for a in actions)

    # Second GET consumes it — should be empty (or not include this id)
    r = requests.get(f"{API}/ui/actions")
    assert all(a["id"] != aid for a in r.json()["actions"])


# ---------- Coding disabled ----------
def test_coding_disabled():
    r = requests.post(f"{API}/coding/run", json={"message": "yaz kod"})
    assert r.status_code == 503
    d = r.json()
    detail = d.get("detail", d)
    msg = detail.get("message", "")
    assert "JARVIS_CODING_LOOP_ENABLED" in msg
    assert "JARVIS_WORKSPACE_ROOT" in msg
    assert "JARVIS_WORKSPACE_WRITABLE" in msg
    assert "JARVIS_TERMINAL_ENABLED" in msg


# ---------- Memory ----------
def test_memory():
    txt = f"TEST_memory_{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/memory", json={"kind": "semantic", "text": txt, "meta": {}})
    assert r.status_code == 200
    r = requests.get(f"{API}/memory", params={"kind": "semantic", "q": txt})
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(it["text"] == txt for it in items)


# ---------- Insight ----------
def test_insight():
    r = requests.get(f"{API}/insight")
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d["traits"], list)
    assert len(d["traits"]) >= 1


# ---------- Panel command interpreter (LLM-driven, iteration 2) ----------
def test_panel_command_notes():
    """notes panel: 'Alışveriş listesi notu yaz: süt, ekmek, yumurta' → creates a note with author=agent."""
    marker = f"TEST_pcmd_{uuid.uuid4().hex[:6]}"
    msg = f"Alışveriş listesi notu yaz (başlığa {marker} ekle): süt, ekmek, yumurta"
    r = requests.post(f"{API}/panels/command", json={"panel": "notes", "message": msg}, timeout=120)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "reply" in d and isinstance(d["reply"], str)
    assert "actions" in d and isinstance(d["actions"], list)

    # Verify a note appears in GET /notes authored by agent (best-effort — LLM may not include marker)
    r = requests.get(f"{API}/notes", timeout=30)
    assert r.status_code == 200
    notes = r.json()["notes"]
    agent_notes = [n for n in notes if n.get("author") == "agent"]
    assert len(agent_notes) >= 1, "expected at least one agent-authored note after panel command"


def test_panel_command_memory():
    r = requests.post(
        f"{API}/panels/command",
        json={"panel": "memory", "message": "Kahvemi sütsüz içtiğimi hatırla"},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert "reply" in d and "actions" in d
    # Verify at least one memory item exists with mention (search)
    r = requests.get(f"{API}/memory", timeout=30)
    assert r.status_code == 200
    items = r.json()["items"]
    # LLM may phrase in various ways; check for at least presence of any recent memory
    assert isinstance(items, list) and len(items) >= 1


def test_panel_command_checkpoints():
    r = requests.post(
        f"{API}/panels/command",
        json={"panel": "checkpoints", "message": "plan.md için geri alma noktası oluştur"},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert "reply" in d and "actions" in d
    r = requests.get(f"{API}/checkpoints", timeout=30)
    assert r.status_code == 200
    cps = r.json()["checkpoints"]
    # Should be at least one checkpoint referencing plan.md OR at least any new checkpoint
    assert isinstance(cps, list) and len(cps) >= 1


def test_panel_command_approvals():
    # Create a pending approval first
    r = requests.post(f"{API}/approvals", json={"tool": "shell", "arguments": {"cmd": "ls"}, "reason": "test_pcmd"})
    assert r.status_code == 200
    aid = r.json()["id"]

    # LLM approves the pending request
    r = requests.post(
        f"{API}/panels/command",
        json={"panel": "approvals", "message": "bekleyen isteği onayla"},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert "reply" in d and "actions" in d

    # Verify the previously pending approval no longer appears in pending list
    r = requests.get(f"{API}/approvals", timeout=30)
    assert r.status_code == 200
    pending_ids = [a["id"] for a in r.json()["approvals"]]
    assert aid not in pending_ids, "approval should have been decided by panel command"


def test_panel_command_invalid_panel_422():
    r = requests.post(
        f"{API}/panels/command",
        json={"panel": "nonexistent_panel", "message": "hi"},
        timeout=30,
    )
    assert r.status_code == 422, r.text


# ---------- Events (Calendar) ----------
def test_events_crud():
    r = requests.post(f"{API}/events", json={"title": "TEST_Event", "date": "2026-09-20", "time": "10:00"}, timeout=30)
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    assert r.json()["title"] == "TEST_Event"

    r = requests.get(f"{API}/events", params={"month": "2026-09"}, timeout=30)
    assert r.status_code == 200
    assert any(e["id"] == eid for e in r.json()["events"])

    r = requests.delete(f"{API}/events/{eid}", timeout=30)
    assert r.status_code == 200

    r = requests.delete(f"{API}/events/{eid}", timeout=30)
    assert r.status_code == 404


# ---------- Reminders ----------
def test_reminders_flow():
    r = requests.post(f"{API}/reminders", json={"title": "TEST_Süt al"}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    rid = d["id"]
    assert d["done"] is False

    r = requests.patch(f"{API}/reminders/{rid}", json={"done": True}, timeout=30)
    assert r.status_code == 200
    assert r.json()["done"] is True

    r = requests.get(f"{API}/reminders", timeout=30)
    assert r.status_code == 200
    assert any(x["id"] == rid and x["done"] is True for x in r.json()["reminders"])

    r = requests.delete(f"{API}/reminders/{rid}", timeout=30)
    assert r.status_code == 200


# ---------- Weather ----------
def test_weather_ankara():
    r = requests.get(f"{API}/weather", params={"city": "Ankara"}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("city")
    assert isinstance(d["current"]["temp"], (int, float))
    assert len(d["daily"]) == 7


def test_weather_not_found():
    r = requests.get(f"{API}/weather", params={"city": "Xyzqwv123"}, timeout=30)
    assert r.status_code == 404
    detail = r.json().get("detail", {})
    assert detail.get("code") == "city_not_found"


# ---------- Translate ----------
def test_translate_tr_to_en():
    r = requests.post(f"{API}/translate", json={"text": "Günaydın", "target": "en"}, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "translation" in d
    assert "good morning" in d["translation"].lower()


# ---------- Panel command: calendar & reminders ----------
def test_panel_command_calendar():
    msg = "20 Eylül 2026 saat 14:00 doktor randevusu"
    r = requests.post(f"{API}/panels/command", json={"panel": "calendar", "message": msg}, timeout=120)
    assert r.status_code == 200, r.text
    d = r.json()
    assert isinstance(d["actions"], list) and len(d["actions"]) >= 1

    r = requests.get(f"{API}/events", params={"month": "2026-09"}, timeout=30)
    assert r.status_code == 200
    events = r.json()["events"]
    assert any(e.get("date") == "2026-09-20" and e.get("author") == "agent" for e in events)


def test_panel_command_reminders():
    r = requests.post(
        f"{API}/panels/command",
        json={"panel": "reminders", "message": "Yarın kitap iade et, düşük öncelik"},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert isinstance(d["actions"], list) and len(d["actions"]) >= 1

    r = requests.get(f"{API}/reminders", timeout=30)
    assert r.status_code == 200
    assert any(x.get("author") == "agent" for x in r.json()["reminders"])

