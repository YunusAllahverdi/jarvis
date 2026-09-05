// Reminders — Apple-style checklist; Jarvis adds items via the command bar.
import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, Empty, ErrorNote, LoadingBlock } from "./_shell";
import { Trash2, Sparkles, Flag } from "lucide-react";

const PRIO = { high: "#ff3b30", medium: "#ff9500", low: "#34c759" };

export default function RemindersPanel() {
  const [items, setItems] = useState(null);
  const [err, setErr] = useState(null);
  const [showDone, setShowDone] = useState(false);

  const refresh = () => api.listReminders().then((r) => setItems(r.reminders || [])).catch(setErr);
  useEffect(() => { refresh(); }, []);

  const toggle = (r) => api.patchReminder(r.id, !r.done).then(refresh).catch(setErr);
  const remove = (id) => api.deleteReminder(id).then(refresh).catch(setErr);

  const visible = (items || []).filter((r) => showDone || !r.done);
  const doneCount = (items || []).filter((r) => r.done).length;

  return (
    <PanelShell
      title="Hatırlatıcılar"
      subtitle="Söyle, Jarvis listeye eklesin — “Yarın faturayı öde, yüksek öncelik”."
      testId="reminders-panel"
      command="reminders"
      onCommandDone={refresh}
      right={
        <button onClick={() => setShowDone((v) => !v)} className="pill" data-testid="rem-toggle-done">
          {showDone ? "Tamamlananları gizle" : `Tamamlananlar (${doneCount})`}
        </button>
      }
    >
      {err && <ErrorNote err={err} testId="rem-error" />}
      {items === null && <LoadingBlock />}
      {items && visible.length === 0 && (
        <Empty label="Hatırlatıcı yok." hint="Alttaki satıra yaz — Jarvis öncelik ve tarihi kendisi çıkarır." testId="rem-empty" />
      )}
      {visible.length > 0 && (
        <ul className="p-5 space-y-1.5 max-w-3xl">
          {visible.map((r) => (
            <li key={r.id} className={`group flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-black/[0.03] ${r.done ? "opacity-50" : ""}`} data-testid={`rem-${r.id}`}>
              <button
                onClick={() => toggle(r)}
                className="w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 transition"
                style={{ borderColor: PRIO[r.priority] || "#8e8e93", background: r.done ? PRIO[r.priority] || "#8e8e93" : "transparent" }}
                aria-label="Tamamla"
                data-testid={`rem-toggle-${r.id}`}
              >
                {r.done && <span className="w-1.5 h-1.5 rounded-full bg-white" />}
              </button>
              <div className="flex-1 min-w-0">
                <p className={`text-sm ${r.done ? "line-through" : ""}`}>{r.title}</p>
                <div className="flex items-center gap-2 text-[11px] text-muted">
                  {r.due && <span>{new Date(r.due).toLocaleDateString("tr-TR", { day: "numeric", month: "short" })}</span>}
                  <span>{r.list}</span>
                  {r.priority === "high" && <Flag size={10} color={PRIO.high} />}
                  {r.author === "agent" && <Sparkles size={10} style={{ color: "#2f6fed" }} />}
                </div>
              </div>
              <button onClick={() => remove(r.id)} className="opacity-0 group-hover:opacity-100 text-muted hover:text-red-500" aria-label="Sil" data-testid={`rem-del-${r.id}`}><Trash2 size={12} /></button>
            </li>
          ))}
        </ul>
      )}
    </PanelShell>
  );
}
