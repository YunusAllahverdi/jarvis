// Notes panel — Jarvis writes notes on command; no manual forms.
import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, Empty, ErrorNote, LoadingBlock } from "./_shell";
import { Trash2, Sparkles } from "lucide-react";

export default function NotesPanel() {
  const [notes, setNotes] = useState(null);
  const [err, setErr] = useState(null);

  const refresh = () => api.listNotes().then((r) => setNotes(r.notes || [])).catch(setErr);
  useEffect(() => { refresh(); }, []);

  const remove = async (id) => {
    try { await api.deleteNote(id); refresh(); } catch (e) { setErr(e); }
  };

  return (
    <PanelShell
      title="Notlar"
      subtitle="Söyle, Jarvis yazsın. Notlar kalıcıdır ve bellekten ayrıdır."
      testId="notes-panel"
      command="notes"
      onCommandDone={refresh}
    >
      {err && <ErrorNote err={err} testId="notes-error" />}
      {notes === null && <LoadingBlock />}

      {notes && notes.length === 0 && (
        <Empty
          label="Henüz not yok."
          hint="Alttaki satıra ne istediğini yaz — örneğin “Bugünkü toplantı için gündem notu hazırla”. Jarvis notu senin için yazar."
          testId="notes-empty"
        />
      )}

      {notes && notes.length > 0 && (
        <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-4">
          {notes.map((n) => (
            <div key={n.id} className="glass-soft rounded-2xl p-4" data-testid={`note-${n.id}`}>
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-display text-white text-base font-semibold">{n.title}</h3>
                <button className="text-muted hover:text-red-500" onClick={() => remove(n.id)} aria-label="Sil" data-testid={`note-del-${n.id}`}>
                  <Trash2 size={13} />
                </button>
              </div>
              <p className="text-sm text-secondary mt-2 whitespace-pre-wrap leading-relaxed">{n.content || "(içerik yok)"}</p>
              <div className="flex items-center gap-1.5 mt-3 flex-wrap">
                {n.author === "agent" && (
                  <span className="pill flex items-center gap-1" style={{ color: "#2f6fed", borderColor: "rgba(47,111,237,0.3)" }}>
                    <Sparkles size={10} /> Jarvis yazdı
                  </span>
                )}
                {(n.tags || []).map((t, i) => (
                  <span key={i} className="pill">#{t}</span>
                ))}
                <span className="pill font-mono ml-auto text-[10px]">{new Date(n.updated_at).toLocaleString("tr-TR")}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </PanelShell>
  );
}
