"""Ajanın notlara erişmesini sağlayan araçlar.

İzin seviyeleri bilinçli olarak AYRIŞTIRILMIŞTIR:

- `note_search` READ'tir: okumak serbesttir.
- `note_write` WRITE'tır ve her çağrısı kullanıcı onayından geçer.

Okumak ile yazmak aynı seviyeye konsaydı, ajanın notlarımızı okuyabilmesi
için ona yazma yetkisi de vermemiz gerekirdi. Ajanın yazdığı not kalıcıdır
ve kullanıcının kendi yazdıklarının arasına karışır; bu yüzden yazma
sessizce gerçekleşmemelidir.

Silme aracı BİLİNÇLİ OLARAK YOKTUR. Bir notu silmek kullanıcının kararıdır;
ajanın yanlış anlamayla kalıcı bir metni yok edebilmesi, kazanılan
kolaylığa değmez. Silme yalnızca API üzerinden, kullanıcı tarafından yapılır.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.notes.store import MAX_CONTENT_CHARS, MAX_TITLE_CHARS, NoteStore
from app.tools.base import PermissionLevel, Tool, ToolExecutionError, ToolInput

NOTE_SEARCH_TOOL_NAME = "note_search"
NOTE_WRITE_TOOL_NAME = "note_write"

_MAX_RESULTS = 20
_SNIPPET_CHARS = 600
"""Sonuçta taşınacak en fazla karakter (not başına).

Notlar 20.000 karaktere kadar olabilir; tamamını modele vermek tek bir
aramayla bağlamı doldurabilirdi.
"""


class NoteSearchInput(ToolInput):
    """`note_search` tool'unun doğrulanmış input'u."""

    query: str = Field(default="", max_length=200)
    limit: int = Field(default=10, ge=1, le=_MAX_RESULTS)


class NoteSearchTool(Tool[NoteSearchInput]):
    """Kullanıcının notlarını arar veya listeler."""

    name = NOTE_SEARCH_TOOL_NAME
    description = (
        "Kullanıcının kayıtlı notlarını arar. Sorgu verilmezse en son "
        "güncellenen notları döndürür."
    )
    permission = PermissionLevel.READ
    input_model = NoteSearchInput

    def __init__(self, *, store: NoteStore) -> None:
        self._store = store

    async def execute(self, tool_input: NoteSearchInput) -> dict[str, Any]:
        try:
            notes = self._store.list(query=tool_input.query, limit=tool_input.limit)
        except Exception as exc:  # noqa: BLE001
            raise ToolExecutionError("Notlar okunamadı.") from exc

        return {
            "count": len(notes),
            "notes": [
                {
                    "id": note.id,
                    "title": note.title,
                    "content": note.content[:_SNIPPET_CHARS],
                    "created_by": note.created_by,
                    "updated_at": note.updated_at.isoformat(),
                }
                for note in notes
            ],
        }


class NoteWriteInput(ToolInput):
    """`note_write` tool'unun doğrulanmış input'u."""

    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    title: str = Field(default="", max_length=MAX_TITLE_CHARS)

    note_id: str | None = Field(default=None, max_length=64)
    """Verilirse var olan not güncellenir, verilmezse yenisi eklenir.

    Güncelleme ve ekleme tek araçtadır çünkü ikisi de "bu metni kalıcı hâle
    getir" isteğidir ve ikisi de aynı onay kapısından geçmelidir.
    """


class NoteWriteTool(Tool[NoteWriteInput]):
    """Bir notu kaydeder veya günceller."""

    name = NOTE_WRITE_TOOL_NAME
    description = (
        "Kalıcı bir not kaydeder. note_id verilirse o notu günceller, "
        "verilmezse yeni bir not oluşturur."
    )
    permission = PermissionLevel.WRITE
    input_model = NoteWriteInput

    def __init__(self, *, store: NoteStore, session_id: str | None = None) -> None:
        self._store = store
        self._session_id = session_id

    async def execute(self, tool_input: NoteWriteInput) -> dict[str, Any]:
        if tool_input.note_id:
            note = self._store.update(
                tool_input.note_id,
                content=tool_input.content,
                title=tool_input.title or None,
            )
            if note is None:
                raise ToolExecutionError("Güncellenecek not bulunamadı.")
            return {"id": note.id, "title": note.title, "updated": True}

        try:
            note = self._store.add(
                content=tool_input.content,
                title=tool_input.title,
                # Ajanın yazdığı notlar işaretlenir: kullanıcı kendi
                # yazdıklarıyla ajanınkini ayırt edebilmelidir.
                created_by="agent",
                session_id=self._session_id,
            )
        except ValueError as exc:
            raise ToolExecutionError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise ToolExecutionError("Not kaydedilemedi.") from exc

        return {"id": note.id, "title": note.title, "updated": False}
