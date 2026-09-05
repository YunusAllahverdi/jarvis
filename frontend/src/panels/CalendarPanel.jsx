// Calendar — Apple-style month grid; Jarvis adds events via the command bar.
import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, ErrorNote } from "./_shell";
import { ChevronLeft, ChevronRight, Trash2, MapPin, Sparkles } from "lucide-react";

const DAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];
const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export default function CalendarPanel() {
  const today = new Date();
  const [cursor, setCursor] = useState(new Date(today.getFullYear(), today.getMonth(), 1));
  const [selected, setSelected] = useState(ymd(today));
  const [events, setEvents] = useState([]);
  const [err, setErr] = useState(null);

  const month = `${cursor.getFullYear()}-${pad(cursor.getMonth() + 1)}`;
  const refresh = () => api.listEvents(month).then((r) => setEvents(r.events || [])).catch(setErr);
  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [month]);

  const cells = useMemo(() => {
    const first = new Date(cursor);
    const offset = (first.getDay() + 6) % 7;
    const daysIn = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0).getDate();
    const arr = [];
    for (let i = 0; i < offset; i++) arr.push(null);
    for (let d = 1; d <= daysIn; d++) arr.push(new Date(cursor.getFullYear(), cursor.getMonth(), d));
    while (arr.length % 7) arr.push(null);
    return arr;
  }, [cursor]);

  const byDate = useMemo(() => {
    const m = {};
    events.forEach((e) => { (m[e.date] ||= []).push(e); });
    return m;
  }, [events]);

  const dayEvents = byDate[selected] || [];
  const title = cursor.toLocaleDateString("tr-TR", { month: "long", year: "numeric" });

  return (
    <PanelShell
      title="Takvim"
      subtitle="Söyle, Jarvis etkinliği eklesin — “Cuma 15:00 diş hekimi”."
      testId="calendar-panel"
      command="calendar"
      onCommandDone={refresh}
      right={
        <div className="flex items-center gap-1">
          <button onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))} className="w-7 h-7 rounded-md hover:bg-black/5 flex items-center justify-center" data-testid="cal-prev"><ChevronLeft size={14} /></button>
          <button onClick={() => { const n = new Date(); setCursor(new Date(n.getFullYear(), n.getMonth(), 1)); setSelected(ymd(n)); }} className="pill" data-testid="cal-today">Bugün</button>
          <button onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))} className="w-7 h-7 rounded-md hover:bg-black/5 flex items-center justify-center" data-testid="cal-next"><ChevronRight size={14} /></button>
        </div>
      }
    >
      {err && <ErrorNote err={err} testId="cal-error" />}
      <div className="flex flex-col lg:flex-row h-full">
        <div className="flex-1 p-5 max-w-[760px]">
          <p className="font-display text-xl font-semibold capitalize mb-3" data-testid="cal-month">{title}</p>
          <div className="grid grid-cols-7 text-[11px] text-muted mb-1">
            {DAYS.map((d) => <div key={d} className="text-center py-1">{d}</div>)}
          </div>
          <div className="grid grid-cols-7 gap-1">
            {cells.map((d, i) => {
              if (!d) return <div key={i} />;
              const k = ymd(d);
              const isToday = k === ymd(today);
              const isSel = k === selected;
              const n = (byDate[k] || []).length;
              return (
                <button
                  key={k}
                  onClick={() => setSelected(k)}
                  className={`h-12 md:h-14 rounded-xl flex flex-col items-center justify-center text-sm transition ${
                    isSel ? "bg-[#ff3b30] text-white" : isToday ? "bg-black/5 font-semibold" : "hover:bg-black/5"
                  }`}
                  data-testid={`cal-day-${k}`}
                >
                  <span>{d.getDate()}</span>
                  <span className={`mt-0.5 flex gap-0.5 h-1`}>
                    {Array.from({ length: Math.min(n, 3) }).map((_, j) => (
                      <span key={j} className={`w-1 h-1 rounded-full ${isSel ? "bg-white" : "bg-[#ff3b30]"}`} />
                    ))}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
        <div className="lg:w-80 border-t lg:border-t-0 lg:border-l hairline p-5 overflow-y-auto">
          <p className="text-[11px] uppercase tracking-[0.2em] text-muted font-mono">
            {new Date(selected).toLocaleDateString("tr-TR", { weekday: "long", day: "numeric", month: "long" })}
          </p>
          {dayEvents.length === 0 && <p className="text-sm text-muted mt-4">Etkinlik yok.</p>}
          <ul className="mt-3 space-y-2">
            {dayEvents.map((e) => (
              <li key={e.id} className="glass-soft rounded-xl p-3 flex gap-3" data-testid={`event-${e.id}`}>
                <div className="w-1 rounded-full bg-[#ff3b30]" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold truncate">{e.title}</p>
                  <p className="text-xs text-muted">{e.time || "Tüm gün"}{e.duration_min ? ` · ${e.duration_min} dk` : ""}</p>
                  {e.location && <p className="text-xs text-muted flex items-center gap-1 mt-0.5"><MapPin size={10} />{e.location}</p>}
                  {e.author === "agent" && <span className="pill inline-flex items-center gap-1 mt-1.5" style={{ color: "#2f6fed" }}><Sparkles size={9} /> Jarvis</span>}
                </div>
                <button onClick={() => api.deleteEvent(e.id).then(refresh)} className="text-muted hover:text-red-500 self-start" aria-label="Sil" data-testid={`event-del-${e.id}`}><Trash2 size={12} /></button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </PanelShell>
  );
}
