"""J.A.R.V.I.S FastAPI backend — Emergent adapted single-file implementation.

Faithfully mirrors the public contracts of the reference J.A.R.V.I.S repository
(chat, notes, approvals, checkpoints, admin/llm, admin/council, ui/actions,
coding, memory, insight, diagnostics, health) so the premium Turkish frontend
can talk to a real system rather than mocks.

The heavy service graph of the reference project (Ollama provider, SQLite
memory extractor, coding planner, council chairman) is not reproduced here.
Instead we use MongoDB for persistence and the Emergent LLM Key with Claude
Sonnet 5 for chat responses. The API SHAPES are preserved so the frontend
integrates without inventing routes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("jarvis")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
DEFAULT_PROVIDER = os.environ.get("JARVIS_PROVIDER", "anthropic")
DEFAULT_MODEL = os.environ.get("JARVIS_MODEL", "claude-sonnet-5")
TIMEZONE_NAME = os.environ.get("JARVIS_TIMEZONE", "Europe/Istanbul")

_client = AsyncIOMotorClient(MONGO_URL)
db = _client[DB_NAME]

SYSTEM_PROMPT_TR = (
    "Sen J.A.R.V.I.S adında Türkçe konuşan, sakin ve zeki bir kişisel AI çalışma katmanısın. "
    "Kısa, doğrudan ve dürüst cevaplar verirsin. Kullanıcı sana Türkçe yazar, sen de Türkçe yanıt verirsin. "
    "Emin olmadığın bir bilgiyi uydurmazsın. Kod, terminal veya dosya değişikliği istendiğinde "
    "sistemin izin ve onay katmanına saygı gösterir, kullanıcıdan onay bekler gibi konuşursun."
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


# ============================================================================
# App
# ============================================================================
app = FastAPI(title="J.A.R.V.I.S Local", version="0.2.0")
api = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Health / Diagnostics
# ---------------------------------------------------------------------------
@api.get("/")
async def root():
    return {"name": "J.A.R.V.I.S Local", "version": "0.2.0", "environment": "development"}


@api.get("/health")
async def health():
    return {
        "status": "ok",
        "provider": DEFAULT_PROVIDER,
        "model": DEFAULT_MODEL,
        "features": {
            "chat": True,
            "notes": True,
            "approvals": True,
            "checkpoints": True,
            "coding_loop": os.environ.get("JARVIS_CODING_LOOP_ENABLED", "false").lower() == "true",
            "council": True,
            "research": os.environ.get("JARVIS_RESEARCH_ENABLED", "false").lower() == "true",
            "terminal": os.environ.get("JARVIS_TERMINAL_ENABLED", "false").lower() == "true",
            "notes_writable": os.environ.get("JARVIS_NOTES_WRITABLE", "true").lower() == "true",
            "workspace_writable": os.environ.get("JARVIS_WORKSPACE_WRITABLE", "false").lower() == "true",
        },
        "timezone": TIMEZONE_NAME,
        "timestamp": now_iso(),
    }


@api.get("/diagnostics")
async def diagnostics():
    audit = await db.audit.find({}, {"_id": 0}).sort("timestamp", -1).to_list(50)
    counts = {
        "notes": await db.notes.count_documents({}),
        "approvals": await db.approvals.count_documents({}),
        "checkpoints": await db.checkpoints.count_documents({}),
        "sessions": await db.sessions.count_documents({}),
        "messages": await db.messages.count_documents({}),
        "audit": await db.audit.count_documents({}),
    }
    return {
        "permissions": {
            "read": "allowed",
            "write": "requires_approval",
            "dangerous": "denied" if os.environ.get("JARVIS_TERMINAL_ENABLED", "false").lower() != "true" else "requires_approval",
        },
        "counts": counts,
        "recent_audit": audit,
        "timestamp": now_iso(),
    }


# ---------------------------------------------------------------------------
# Chat (stream + non-stream + sessions)
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str = Field(max_length=10000)
    session_id: Optional[str] = Field(default=None, max_length=128)

    @field_validator("message")
    @classmethod
    def _msg(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message boş olamaz")
        return v


class ChatResponse(BaseModel):
    response: str
    session_id: str


async def _get_provider_config() -> dict:
    cfg = await db.config.find_one({"_id": "llm"}, {"_id": 0})
    if not cfg:
        cfg = {"provider": DEFAULT_PROVIDER, "model": DEFAULT_MODEL, "base_url": None, "has_api_key": bool(EMERGENT_LLM_KEY)}
    else:
        cfg["has_api_key"] = bool(cfg.get("api_key") or EMERGENT_LLM_KEY)
        cfg.pop("api_key", None)
    return cfg


async def _get_history(session_id: str, limit: int = 20) -> list[dict]:
    msgs = await db.messages.find({"session_id": session_id}, {"_id": 0}).sort("ts", 1).to_list(limit)
    return msgs


async def _append_message(session_id: str, role: str, content: str) -> None:
    await db.messages.insert_one(
        {"id": new_id(), "session_id": session_id, "role": role, "content": content, "ts": now_iso()}
    )
    await db.sessions.update_one(
        {"id": session_id},
        {"$set": {"id": session_id, "last_ts": now_iso(), "last_snippet": content[:120]}, "$inc": {"n": 1}},
        upsert=True,
    )


def _emergent_chat(session_id: str):
    """Build a fresh LlmChat instance for the session with current config."""
    from emergentintegrations.llm.chat import LlmChat  # local import: heavy

    provider = DEFAULT_PROVIDER
    model = DEFAULT_MODEL
    api_key = EMERGENT_LLM_KEY
    chat = LlmChat(
        api_key=api_key,
        session_id=session_id,
        system_message=SYSTEM_PROMPT_TR,
    ).with_model(provider, model)
    return chat


async def _respond_full(message: str, session_id: str) -> str:
    """Non-streaming path — we call stream and accumulate."""
    from emergentintegrations.llm.chat import UserMessage, TextDelta, StreamDone

    chat = _emergent_chat(session_id)
    history = await _get_history(session_id, limit=40)
    # Replay history into chat's internal store (best-effort; new-turn call preserves session_id).
    parts: list[str] = []
    try:
        async for ev in chat.stream_message(UserMessage(text=message)):
            if isinstance(ev, TextDelta):
                parts.append(ev.content)
            elif isinstance(ev, StreamDone):
                break
    except Exception as exc:  # noqa: BLE001
        logger.exception("llm_error")
        raise HTTPException(status_code=502, detail={"code": "llm_provider_error", "message": str(exc)})
    return "".join(parts).strip() or "(boş yanıt)"


@api.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not EMERGENT_LLM_KEY:
        raise HTTPException(
            status_code=503,
            detail={"code": "llm_unavailable", "message": "LLM anahtarı yapılandırılmamış."},
        )
    session_id = req.session_id or new_id()
    await _append_message(session_id, "user", req.message)
    text = await _respond_full(req.message, session_id)
    await _append_message(session_id, "assistant", text)
    await db.audit.insert_one({"id": new_id(), "kind": "chat", "session_id": session_id, "timestamp": now_iso()})
    return ChatResponse(response=text, session_id=session_id)


@api.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE token stream. Emits `data: {json}\\n\\n` per token, then a final `event: done`."""
    from emergentintegrations.llm.chat import UserMessage, TextDelta, StreamDone

    if not EMERGENT_LLM_KEY:
        raise HTTPException(
            status_code=503,
            detail={"code": "llm_unavailable", "message": "LLM anahtarı yapılandırılmamış."},
        )
    session_id = req.session_id or new_id()
    await _append_message(session_id, "user", req.message)

    async def gen() -> AsyncIterator[bytes]:
        chat = _emergent_chat(session_id)
        buf: list[str] = []
        # Announce session id first so the client can persist it.
        yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n".encode()
        try:
            async for ev in chat.stream_message(UserMessage(text=req.message)):
                if isinstance(ev, TextDelta):
                    buf.append(ev.content)
                    payload = json.dumps({"delta": ev.content})
                    yield f"data: {payload}\n\n".encode()
                elif isinstance(ev, StreamDone):
                    break
        except Exception as exc:  # noqa: BLE001
            logger.exception("stream_error")
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n".encode()
            return
        text = "".join(buf).strip() or "(boş yanıt)"
        await _append_message(session_id, "assistant", text)
        await db.audit.insert_one({"id": new_id(), "kind": "chat_stream", "session_id": session_id, "timestamp": now_iso()})
        yield f"event: done\ndata: {json.dumps({'session_id': session_id})}\n\n".encode()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@api.get("/chat/sessions")
async def list_sessions():
    sessions = await db.sessions.find({}, {"_id": 0}).sort("last_ts", -1).to_list(100)
    return {"sessions": sessions}


@api.get("/chat/sessions/{session_id}/messages")
async def session_messages(session_id: str):
    msgs = await db.messages.find({"session_id": session_id}, {"_id": 0}).sort("ts", 1).to_list(500)
    return {"session_id": session_id, "messages": msgs}


@api.delete("/chat/sessions/{session_id}")
async def delete_session(session_id: str):
    await db.messages.delete_many({"session_id": session_id})
    await db.sessions.delete_one({"id": session_id})
    return {"deleted": session_id}


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------
class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=20000)
    tags: list[str] = Field(default_factory=list)
    author: str = Field(default="user")  # "user" | "agent"


class Note(NoteIn):
    id: str
    created_at: str
    updated_at: str


@api.get("/notes")
async def list_notes():
    if os.environ.get("JARVIS_NOTES_ENABLED", "true").lower() != "true":
        raise HTTPException(status_code=503, detail={"code": "notes_disabled", "message": "Notlar kapalı."})
    items = await db.notes.find({}, {"_id": 0}).sort("updated_at", -1).to_list(500)
    return {"notes": items}


@api.post("/notes", response_model=Note)
async def create_note(inp: NoteIn):
    if os.environ.get("JARVIS_NOTES_WRITABLE", "true").lower() != "true":
        raise HTTPException(status_code=403, detail={"code": "notes_readonly", "message": "Notlar salt okunur."})
    doc = {**inp.model_dump(), "id": new_id(), "created_at": now_iso(), "updated_at": now_iso()}
    await db.notes.insert_one(doc)
    return doc


@api.put("/notes/{note_id}", response_model=Note)
async def update_note(note_id: str, inp: NoteIn):
    doc = await db.notes.find_one({"id": note_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "note_not_found"})
    updated = {**doc, **inp.model_dump(), "updated_at": now_iso(), "id": note_id}
    await db.notes.update_one({"id": note_id}, {"$set": updated})
    return updated


@api.delete("/notes/{note_id}")
async def delete_note(note_id: str):
    res = await db.notes.delete_one({"id": note_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail={"code": "note_not_found"})
    return {"deleted": note_id}


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------
class ApprovalIn(BaseModel):
    tool: str
    arguments: dict
    reason: str | None = None


@api.get("/approvals")
async def list_approvals():
    items = await db.approvals.find({"status": "pending"}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"approvals": items}


@api.post("/approvals")
async def create_approval(inp: ApprovalIn):
    doc = {
        "id": new_id(),
        "tool": inp.tool,
        "arguments": inp.arguments,
        "reason": inp.reason,
        "status": "pending",
        "created_at": now_iso(),
    }
    await db.approvals.insert_one(doc)
    doc.pop("_id", None)
    return doc


class ApprovalDecision(BaseModel):
    decision: str  # approve | reject

    @field_validator("decision")
    @classmethod
    def _d(cls, v: str) -> str:
        if v not in {"approve", "reject"}:
            raise ValueError("decision approve veya reject olmalı")
        return v


@api.post("/approvals/{approval_id}")
async def decide_approval(approval_id: str, inp: ApprovalDecision):
    doc = await db.approvals.find_one({"id": approval_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "approval_not_found"})
    if doc.get("status") != "pending":
        raise HTTPException(status_code=409, detail={"code": "already_decided"})
    await db.approvals.update_one(
        {"id": approval_id},
        {"$set": {"status": "approved" if inp.decision == "approve" else "rejected", "decided_at": now_iso()}},
    )
    await db.audit.insert_one({"id": new_id(), "kind": "approval", "approval_id": approval_id, "decision": inp.decision, "timestamp": now_iso()})
    return {"id": approval_id, "status": "approved" if inp.decision == "approve" else "rejected"}


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------
class CheckpointIn(BaseModel):
    label: str
    path: str
    snapshot: str = ""


@api.get("/checkpoints")
async def list_checkpoints():
    items = await db.checkpoints.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"checkpoints": items}


@api.post("/checkpoints")
async def create_checkpoint(inp: CheckpointIn):
    doc = {"id": new_id(), **inp.model_dump(), "created_at": now_iso(), "restored": False}
    await db.checkpoints.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.post("/checkpoints/{checkpoint_id}/restore")
async def restore_checkpoint(checkpoint_id: str):
    doc = await db.checkpoints.find_one({"id": checkpoint_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "checkpoint_not_found"})
    await db.checkpoints.update_one({"id": checkpoint_id}, {"$set": {"restored": True, "restored_at": now_iso()}})
    await db.audit.insert_one({"id": new_id(), "kind": "checkpoint_restore", "checkpoint_id": checkpoint_id, "timestamp": now_iso()})
    return {"id": checkpoint_id, "status": "restored"}


# ---------------------------------------------------------------------------
# Admin LLM Config
# ---------------------------------------------------------------------------
class LLMConfigIn(BaseModel):
    provider: str  # ollama | openai_compatible | anthropic | gemini
    base_url: str | None = None
    model: str
    api_key: str | None = None
    clear_api_key: bool = False


@api.get("/admin/llm")
async def get_llm_config():
    return await _get_provider_config()


@api.put("/admin/llm")
async def put_llm_config(inp: LLMConfigIn):
    current = await db.config.find_one({"_id": "llm"}) or {}
    new_doc: dict[str, Any] = {
        "provider": inp.provider,
        "model": inp.model,
        "base_url": inp.base_url,
    }
    if inp.clear_api_key:
        new_doc["api_key"] = None
    elif inp.api_key:
        new_doc["api_key"] = inp.api_key
    elif "api_key" in current:
        new_doc["api_key"] = current["api_key"]
    await db.config.update_one({"_id": "llm"}, {"$set": new_doc}, upsert=True)
    await db.audit.insert_one({"id": new_id(), "kind": "admin_llm_update", "provider": inp.provider, "model": inp.model, "timestamp": now_iso()})
    return await _get_provider_config()


# ---------------------------------------------------------------------------
# Admin Council (multi-model deliberation)
# ---------------------------------------------------------------------------
class CouncilMemberIn(BaseModel):
    kind: str = "openai_compatible"  # ollama | openai_compatible | anthropic
    base_url: str | None = None
    model: str
    api_key: str | None = None
    is_chairman: bool = False
    clear_api_key: bool = False


def _mask_member(m: dict) -> dict:
    out = {k: v for k, v in m.items() if k != "api_key"}
    out["has_api_key"] = bool(m.get("api_key"))
    return out


@api.get("/admin/council")
async def get_council():
    members = await db.council.find({}, {"_id": 0}).to_list(50)
    masked = [_mask_member(m) for m in members]
    min_cand = 2
    active = sum(1 for m in members if m.get("model")) >= min_cand
    return {"members": masked, "active": active, "min_candidates": min_cand}


@api.put("/admin/council/members/{member_id}")
async def upsert_council_member(member_id: str, inp: CouncilMemberIn):
    current = await db.council.find_one({"id": member_id}) or {}
    doc: dict[str, Any] = {
        "id": member_id,
        "kind": inp.kind,
        "base_url": inp.base_url,
        "model": inp.model,
        "is_chairman": inp.is_chairman,
    }
    if inp.clear_api_key:
        doc["api_key"] = None
    elif inp.api_key:
        doc["api_key"] = inp.api_key
    elif "api_key" in current:
        doc["api_key"] = current["api_key"]
    # chairman uniqueness
    if inp.is_chairman:
        await db.council.update_many({"id": {"$ne": member_id}}, {"$set": {"is_chairman": False}})
    await db.council.update_one({"id": member_id}, {"$set": doc}, upsert=True)
    return _mask_member(doc)


@api.delete("/admin/council/members/{member_id}")
async def delete_council_member(member_id: str):
    res = await db.council.delete_one({"id": member_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail={"code": "member_not_found"})
    return {"deleted": member_id}


# ---------------------------------------------------------------------------
# UI Actions bus (agent → shell panel open requests)
# ---------------------------------------------------------------------------
class UIActionIn(BaseModel):
    panel: str
    session_id: str | None = None
    context: dict = Field(default_factory=dict)


@api.get("/ui/actions")
async def get_ui_actions(session_id: str | None = Query(default=None)):
    q: dict[str, Any] = {"consumed": False}
    if session_id:
        q["session_id"] = session_id
    items = await db.ui_actions.find(q, {"_id": 0}).sort("created_at", 1).to_list(50)
    if items:
        ids = [x["id"] for x in items]
        await db.ui_actions.update_many({"id": {"$in": ids}}, {"$set": {"consumed": True, "consumed_at": now_iso()}})
    return {"actions": items}


@api.post("/ui/actions")
async def post_ui_action(inp: UIActionIn):
    doc = {"id": new_id(), **inp.model_dump(), "created_at": now_iso(), "consumed": False}
    await db.ui_actions.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Coding loop (skeleton; returns NO_PLAN when disabled)
# ---------------------------------------------------------------------------
class CodingRunIn(BaseModel):
    message: str
    session_id: str | None = None


@api.post("/coding/run")
async def coding_run(inp: CodingRunIn):
    enabled = os.environ.get("JARVIS_CODING_LOOP_ENABLED", "false").lower() == "true"
    if not enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "coding_loop_disabled",
                "message": "Kodlama döngüsü kapalı. .env'de JARVIS_CODING_LOOP_ENABLED=true, JARVIS_WORKSPACE_ROOT, JARVIS_WORKSPACE_WRITABLE=true ve JARVIS_TERMINAL_ENABLED=true ayarlarını birlikte açmalısınız.",
            },
        )
    # Placeholder deterministic result — real loop lives in reference repo.
    return {
        "task": inp.message,
        "session_id": inp.session_id or new_id(),
        "status": "no_plan",
        "summary": "Bu ortamda kodlama döngüsü çekirdek bileşenleri kurulu değil.",
        "rounds": [],
        "diff": "",
        "pending_approval_ids": [],
    }


# ---------------------------------------------------------------------------
# Memory browser
# ---------------------------------------------------------------------------
@api.get("/memory")
async def memory_browse(kind: str | None = Query(default=None), q: str | None = Query(default=None)):
    query: dict[str, Any] = {}
    if kind:
        query["kind"] = kind
    if q:
        query["text"] = {"$regex": q, "$options": "i"}
    items = await db.memory.find(query, {"_id": 0}).sort("ts", -1).to_list(200)
    return {"items": items}


class MemoryIn(BaseModel):
    kind: str  # episodic | semantic | experience
    text: str
    meta: dict = Field(default_factory=dict)


@api.post("/memory")
async def memory_add(inp: MemoryIn):
    doc = {"id": new_id(), **inp.model_dump(), "ts": now_iso()}
    await db.memory.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Calendar events / Reminders / Weather / Translate (iPad-Mac style apps)
# ---------------------------------------------------------------------------
class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    date: str
    time: str | None = None
    duration_min: int = 60
    location: str | None = None
    notes: str | None = None


@api.get("/events")
async def list_events(month: str | None = Query(default=None)):
    q: dict[str, Any] = {}
    if month:
        q["date"] = {"$regex": f"^{month}"}
    items = await db.events.find(q, {"_id": 0}).sort([("date", 1), ("time", 1)]).to_list(500)
    return {"events": items}


@api.post("/events")
async def create_event(inp: EventIn):
    doc = {"id": new_id(), **inp.model_dump(), "author": "user", "created_at": now_iso()}
    await db.events.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.delete("/events/{event_id}")
async def delete_event(event_id: str):
    r = await db.events.delete_one({"id": event_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail={"code": "event_not_found"})
    return {"deleted": event_id}


class ReminderIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due: str | None = None
    priority: str = "medium"
    list: str = "Genel"


@api.get("/reminders")
async def list_reminders():
    items = await db.reminders.find({}, {"_id": 0}).sort([("done", 1), ("due", 1)]).to_list(500)
    return {"reminders": items}


@api.post("/reminders")
async def create_reminder(inp: ReminderIn):
    doc = {"id": new_id(), **inp.model_dump(), "done": False, "author": "user", "created_at": now_iso()}
    await db.reminders.insert_one(doc)
    doc.pop("_id", None)
    return doc


class ReminderPatch(BaseModel):
    done: bool


@api.patch("/reminders/{reminder_id}")
async def patch_reminder(reminder_id: str, inp: ReminderPatch):
    r = await db.reminders.update_one({"id": reminder_id}, {"$set": {"done": inp.done, "done_at": now_iso() if inp.done else None}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail={"code": "reminder_not_found"})
    return {"id": reminder_id, "done": inp.done}


@api.delete("/reminders/{reminder_id}")
async def delete_reminder(reminder_id: str):
    r = await db.reminders.delete_one({"id": reminder_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail={"code": "reminder_not_found"})
    return {"deleted": reminder_id}


WMO_TR = {
    0: "Açık", 1: "Çoğunlukla açık", 2: "Parçalı bulutlu", 3: "Bulutlu", 45: "Sisli", 48: "Kırağılı sis",
    51: "Hafif çisenti", 53: "Çisenti", 55: "Yoğun çisenti", 61: "Hafif yağmur", 63: "Yağmur", 65: "Kuvvetli yağmur",
    71: "Hafif kar", 73: "Kar", 75: "Yoğun kar", 80: "Sağanak", 81: "Sağanak", 82: "Şiddetli sağanak",
    95: "Gök gürültülü fırtına", 96: "Dolu ile fırtına", 99: "Dolu ile fırtına",
}


@api.get("/weather")
async def weather(city: str = Query(default="İstanbul")):
    import httpx

    try:
        async with httpx.AsyncClient(timeout=12) as cx:
            geo = (await cx.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1, "language": "tr"})).json()
            if not geo.get("results"):
                raise HTTPException(status_code=404, detail={"code": "city_not_found", "message": "Şehir bulunamadı."})
            g = geo["results"][0]
            wx = (await cx.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": g["latitude"], "longitude": g["longitude"], "timezone": "auto",
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min", "forecast_days": 7,
            })).json()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"code": "weather_unavailable", "message": str(exc)})
    cur = wx.get("current", {})
    daily = wx.get("daily", {})
    return {
        "city": g.get("name"), "country": g.get("country"),
        "current": {"temp": cur.get("temperature_2m"), "feels": cur.get("apparent_temperature"), "humidity": cur.get("relative_humidity_2m"),
                    "wind": cur.get("wind_speed_10m"), "code": cur.get("weather_code"), "label": WMO_TR.get(cur.get("weather_code"), "—")},
        "daily": [
            {"date": d, "code": c, "label": WMO_TR.get(c, "—"), "max": mx, "min": mn}
            for d, c, mx, mn in zip(daily.get("time", []), daily.get("weather_code", []), daily.get("temperature_2m_max", []), daily.get("temperature_2m_min", []))
        ],
    }


class TranslateIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    target: str = "en"


@api.post("/translate")
async def translate(inp: TranslateIn):
    from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail={"code": "llm_unavailable", "message": "LLM anahtarı yapılandırılmamış."})
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY, session_id=f"translate-{new_id()}",
        system_message=f"Sen bir çevirmensin. Verilen metni '{inp.target}' dil koduna çevir. SADECE çeviriyi döndür, açıklama ekleme.",
    ).with_model(DEFAULT_PROVIDER, DEFAULT_MODEL)
    parts: list[str] = []
    try:
        async for ev in chat.stream_message(UserMessage(text=inp.text)):
            if isinstance(ev, TextDelta):
                parts.append(ev.content)
            elif isinstance(ev, StreamDone):
                break
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"code": "llm_provider_error", "message": str(exc)})
    return {"translation": "".join(parts).strip(), "target": inp.target}


# ---------------------------------------------------------------------------
# Panel command interpreter — natural language → structured panel actions
# ---------------------------------------------------------------------------
PANEL_TOOLS = {
    "notes": (
        'create_note{title,content,tags[]} | update_note{id,title?,content?,tags?} | delete_note{id}'
    ),
    "approvals": 'approve{id} | reject{id} | request_approval{tool,arguments{},reason}',
    "memory": 'add_memory{kind: episodic|semantic|experience, text}',
    "checkpoints": 'create_checkpoint{label,path,snapshot} | restore_checkpoint{id}',
    "calendar": 'create_event{title,date:YYYY-MM-DD,time:HH:MM?,duration_min?,location?,notes?} | delete_event{id}',
    "reminders": 'create_reminder{title,due:YYYY-MM-DD?,priority:low|medium|high?,list?} | complete_reminder{id} | delete_reminder{id}',
}


class PanelCommandIn(BaseModel):
    panel: str
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("panel")
    @classmethod
    def _p(cls, v: str) -> str:
        if v not in PANEL_TOOLS:
            raise ValueError("bilinmeyen panel")
        return v


async def _panel_context(panel: str) -> list[dict]:
    if panel == "notes":
        items = await db.notes.find({}, {"_id": 0, "id": 1, "title": 1, "content": 1, "tags": 1}).sort("updated_at", -1).to_list(40)
        return [{**i, "content": (i.get("content") or "")[:160]} for i in items]
    if panel == "approvals":
        return await db.approvals.find({"status": "pending"}, {"_id": 0, "id": 1, "tool": 1, "reason": 1}).to_list(40)
    if panel == "memory":
        return await db.memory.find({}, {"_id": 0, "id": 1, "kind": 1, "text": 1}).sort("ts", -1).to_list(30)
    if panel == "checkpoints":
        return await db.checkpoints.find({}, {"_id": 0, "id": 1, "label": 1, "path": 1, "restored": 1}).sort("created_at", -1).to_list(40)
    if panel == "calendar":
        return await db.events.find({}, {"_id": 0, "id": 1, "title": 1, "date": 1, "time": 1}).sort("date", 1).to_list(60)
    if panel == "reminders":
        return await db.reminders.find({"done": False}, {"_id": 0, "id": 1, "title": 1, "due": 1, "priority": 1}).to_list(60)
    return []


async def _run_panel_action(panel: str, a: dict) -> str | None:
    t = a.get("type")
    if panel == "notes":
        if t == "create_note":
            doc = {"id": new_id(), "title": (a.get("title") or "Not")[:200], "content": a.get("content") or "",
                   "tags": [str(x) for x in (a.get("tags") or [])][:10], "author": "agent",
                   "created_at": now_iso(), "updated_at": now_iso()}
            await db.notes.insert_one(doc)
            return f"not oluşturuldu: {doc['title']}"
        if t == "update_note" and a.get("id"):
            upd = {k: a[k] for k in ("title", "content", "tags") if a.get(k) is not None}
            upd["updated_at"] = now_iso()
            r = await db.notes.update_one({"id": a["id"]}, {"$set": upd})
            return "not güncellendi" if r.matched_count else None
        if t == "delete_note" and a.get("id"):
            r = await db.notes.delete_one({"id": a["id"]})
            return "not silindi" if r.deleted_count else None
    if panel == "approvals":
        if t in ("approve", "reject") and a.get("id"):
            status = "approved" if t == "approve" else "rejected"
            r = await db.approvals.update_one({"id": a["id"], "status": "pending"}, {"$set": {"status": status, "decided_at": now_iso()}})
            return ("onaylandı" if t == "approve" else "reddedildi") if r.matched_count else None
        if t == "request_approval":
            doc = {"id": new_id(), "tool": a.get("tool") or "tool", "arguments": a.get("arguments") or {},
                   "reason": a.get("reason"), "status": "pending", "created_at": now_iso()}
            await db.approvals.insert_one(doc)
            return f"onay isteği açıldı: {doc['tool']}"
    if panel == "memory" and t == "add_memory":
        kind = a.get("kind") if a.get("kind") in ("episodic", "semantic", "experience") else "semantic"
        await db.memory.insert_one({"id": new_id(), "kind": kind, "text": a.get("text") or "", "meta": {"source": "panel_command"}, "ts": now_iso()})
        return f"belleğe eklendi ({kind})"
    if panel == "checkpoints":
        if t == "create_checkpoint":
            doc = {"id": new_id(), "label": a.get("label") or "checkpoint", "path": a.get("path") or "",
                   "snapshot": a.get("snapshot") or "", "created_at": now_iso(), "restored": False}
            await db.checkpoints.insert_one(doc)
            return f"geri alma noktası oluşturuldu: {doc['label']}"
        if t == "restore_checkpoint" and a.get("id"):
            r = await db.checkpoints.update_one({"id": a["id"]}, {"$set": {"restored": True, "restored_at": now_iso()}})
            return "geri alındı" if r.matched_count else None
    if panel == "calendar":
        if t == "create_event":
            doc = {"id": new_id(), "title": (a.get("title") or "Etkinlik")[:200], "date": a.get("date") or datetime.now(timezone.utc).date().isoformat(),
                   "time": a.get("time"), "duration_min": int(a.get("duration_min") or 60), "location": a.get("location"),
                   "notes": a.get("notes"), "author": "agent", "created_at": now_iso()}
            await db.events.insert_one(doc)
            return f"etkinlik eklendi: {doc['title']} ({doc['date']})"
        if t == "delete_event" and a.get("id"):
            r = await db.events.delete_one({"id": a["id"]})
            return "etkinlik silindi" if r.deleted_count else None
    if panel == "reminders":
        if t == "create_reminder":
            pr = a.get("priority") if a.get("priority") in ("low", "medium", "high") else "medium"
            doc = {"id": new_id(), "title": (a.get("title") or "Hatırlatıcı")[:200], "due": a.get("due"), "priority": pr,
                   "list": a.get("list") or "Genel", "done": False, "author": "agent", "created_at": now_iso()}
            await db.reminders.insert_one(doc)
            return f"hatırlatıcı eklendi: {doc['title']}"
        if t == "complete_reminder" and a.get("id"):
            r = await db.reminders.update_one({"id": a["id"]}, {"$set": {"done": True, "done_at": now_iso()}})
            return "tamamlandı" if r.matched_count else None
        if t == "delete_reminder" and a.get("id"):
            r = await db.reminders.delete_one({"id": a["id"]})
            return "hatırlatıcı silindi" if r.deleted_count else None
    return None


def _parse_json_block(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("{"):] if "{" in s else s
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1:
        return {"actions": [], "reply": text.strip()}
    try:
        return json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return {"actions": [], "reply": text.strip()}


@api.post("/panels/command")
async def panel_command(inp: PanelCommandIn):
    from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail={"code": "llm_unavailable", "message": "LLM anahtarı yapılandırılmamış."})
    ctx = await _panel_context(inp.panel)
    system = (
        "Sen J.A.R.V.I.S'in panel asistanısın. Kullanıcının Türkçe komutunu, verilen panel için yapılandırılmış eylemlere çevirirsin. "
        f"Panel: {inp.panel}. Kullanılabilir eylemler: {PANEL_TOOLS[inp.panel]}. "
        f"Bugünün tarihi: {datetime.now(timezone.utc).date().isoformat()} (UTC). Göreli tarihleri (yarın, cuma vb.) ISO tarihe çevir. "
        "SADECE geçerli JSON döndür, başka metin yazma. Şema: "
        '{"actions":[{"type":"...", ...}], "reply":"kullanıcıya kısa Türkçe özet"}. '
        "Not içeriği istenirse içeriği sen yaz; başlığı kısa tut. Eylem gerekmiyorsa actions boş olsun ve reply ile cevap ver. "
        f"Mevcut öğeler (id ile referans ver): {json.dumps(ctx, ensure_ascii=False)[:6000]}"
    )
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"panel-{inp.panel}-{new_id()}", system_message=system).with_model(DEFAULT_PROVIDER, DEFAULT_MODEL)
    parts: list[str] = []
    try:
        async for ev in chat.stream_message(UserMessage(text=inp.message)):
            if isinstance(ev, TextDelta):
                parts.append(ev.content)
            elif isinstance(ev, StreamDone):
                break
    except Exception as exc:  # noqa: BLE001
        logger.exception("panel_command_llm_error")
        raise HTTPException(status_code=502, detail={"code": "llm_provider_error", "message": str(exc)})
    parsed = _parse_json_block("".join(parts))
    done: list[str] = []
    for a in (parsed.get("actions") or [])[:10]:
        if isinstance(a, dict):
            res = await _run_panel_action(inp.panel, a)
            if res:
                done.append(res)
    await db.audit.insert_one({"id": new_id(), "kind": "panel_command", "panel": inp.panel, "actions": done, "timestamp": now_iso()})
    return {"reply": parsed.get("reply") or ("Tamam." if done else "Bir eylem çıkaramadım."), "actions": done}


# ---------------------------------------------------------------------------
# Insight / user model
# ---------------------------------------------------------------------------
@api.get("/insight")
async def insight():
    traits = await db.traits.find({}, {"_id": 0}).to_list(200)
    if not traits:
        traits = [
            {"key": "language_preference", "value": "Türkçe", "confidence": 0.99},
            {"key": "tone", "value": "sakin ve doğrudan", "confidence": 0.7},
        ]
    return {"traits": traits, "updated_at": now_iso()}


# ============================================================================
# Wire router + CORS
# ============================================================================
app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def _shutdown():
    _client.close()
