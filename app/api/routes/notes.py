"""Notların yönetildiği uçlar.

Ajanın not araçlarından FARKLI olarak burada silme de vardır: bir notu
silmek kullanıcının kararıdır ve kullanıcı bu uçların arkasındadır. Ajanın
elinde silme aracı yoktur — yanlış anlamayla kalıcı bir metni yok
edebilmesi, kazanılan kolaylığa değmez.
"""

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.notes.store import MAX_CONTENT_CHARS, MAX_TITLE_CHARS, Note, NoteStore

router = APIRouter(tags=["notes"], prefix="/notes")

_UNAVAILABLE_DETAIL = {
    "code": "notes_unavailable",
    "message": "Not deposu bu uygulama örneğinde bağlı değil.",
}


class NoteCreate(BaseModel):
    """Yeni not veya güncelleme gövdesi."""

    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    title: str = Field(default="", max_length=MAX_TITLE_CHARS)


class NoteListResponse(BaseModel):
    notes: list[Note]
    count: int


def _store(request: Request) -> NoteStore:
    store = getattr(request.app.state, "note_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE_DETAIL
        )
    return store


@router.get("", response_model=NoteListResponse)
async def list_notes(
    request: Request,
    query: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
) -> NoteListResponse:
    """Notları döndürür; sorgu verilirse arar."""
    notes = _store(request).list(query=query, limit=limit)
    return NoteListResponse(notes=notes, count=len(notes))


@router.post("", response_model=Note, status_code=status.HTTP_201_CREATED)
async def create_note(body: NoteCreate, request: Request) -> Note:
    """Yeni bir not oluşturur."""
    try:
        return _store(request).add(
            content=body.content, title=body.title, created_by="user"
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "note_limit", "message": str(exc)},
        ) from exc


@router.put("/{note_id}", response_model=Note)
async def update_note(note_id: str, body: NoteCreate, request: Request) -> Note:
    """Var olan bir notu günceller."""
    note = _store(request).update(note_id, content=body.content, title=body.title)
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "note_not_found", "message": "Not bulunamadı."},
        )
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: str, request: Request) -> None:
    """Bir notu KALICI olarak siler."""
    if not _store(request).delete(note_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "note_not_found", "message": "Not bulunamadı."},
        )
