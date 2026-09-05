// Clock — world clocks + stopwatch + timer (frontend only).
import React, { useEffect, useRef, useState } from "react";
import { PanelShell, Btn } from "./_shell";

const ZONES = [
  { city: "İstanbul", tz: "Europe/Istanbul" },
  { city: "Londra", tz: "Europe/London" },
  { city: "New York", tz: "America/New_York" },
  { city: "Tokyo", tz: "Asia/Tokyo" },
  { city: "Dubai", tz: "Asia/Dubai" },
  { city: "Sydney", tz: "Australia/Sydney" },
];

const fmt = (ms) => {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}.${String(Math.floor((ms % 1000) / 10)).padStart(2, "0")}`;
};

export default function ClockPanel() {
  const [now, setNow] = useState(new Date());
  const [sw, setSw] = useState({ running: false, start: 0, acc: 0 });
  const [timer, setTimer] = useState({ running: false, end: 0, left: 5 * 60 * 1000, preset: 5 });
  const raf = useRef(0);

  useEffect(() => {
    const tick = () => {
      setNow(new Date());
      setTimer((t) => (t.running ? { ...t, left: Math.max(0, t.end - Date.now()), running: t.end - Date.now() > 0 } : t));
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, []);

  const swMs = sw.acc + (sw.running ? Date.now() - sw.start : 0);

  return (
    <PanelShell title="Saat" subtitle="Dünya saatleri, kronometre ve zamanlayıcı." testId="clock-panel">
      <div className="p-6 grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-1 space-y-2">
          {ZONES.map((z) => {
            const local = new Intl.DateTimeFormat("tr-TR", { timeZone: z.tz, hour: "2-digit", minute: "2-digit" }).format(now);
            const off = (new Date(now.toLocaleString("en-US", { timeZone: z.tz })) - new Date(now.toLocaleString("en-US", { timeZone: "Europe/Istanbul" }))) / 36e5;
            return (
              <div key={z.tz} className="glass-soft rounded-xl px-4 py-3 flex items-center justify-between" data-testid={`clock-${z.tz}`}>
                <div>
                  <p className="text-sm font-semibold">{z.city}</p>
                  <p className="text-[11px] text-muted">{off === 0 ? "Bugün" : `${off > 0 ? "+" : ""}${off} sa`}</p>
                </div>
                <p className="font-display text-2xl tabular-nums">{local}</p>
              </div>
            );
          })}
        </div>

        <div className="glass-soft rounded-2xl p-6 flex flex-col items-center" data-testid="stopwatch">
          <p className="text-[11px] uppercase tracking-[0.2em] text-muted font-mono">Kronometre</p>
          <p className="font-display text-5xl tabular-nums my-6">{fmt(swMs)}</p>
          <div className="flex gap-2">
            <Btn kind="primary" onClick={() => setSw((s) => (s.running ? { running: false, start: 0, acc: s.acc + Date.now() - s.start } : { ...s, running: true, start: Date.now() }))} data-testid="sw-toggle">
              {sw.running ? "Durdur" : "Başlat"}
            </Btn>
            <Btn onClick={() => setSw({ running: false, start: 0, acc: 0 })} data-testid="sw-reset">Sıfırla</Btn>
          </div>
        </div>

        <div className="glass-soft rounded-2xl p-6 flex flex-col items-center" data-testid="timer">
          <p className="text-[11px] uppercase tracking-[0.2em] text-muted font-mono">Zamanlayıcı</p>
          <p className={`font-display text-5xl tabular-nums my-6 ${timer.left === 0 ? "text-[#ff3b30]" : ""}`}>{fmt(timer.left).slice(0, 5)}</p>
          <div className="flex gap-1.5 mb-3">
            {[1, 5, 10, 25].map((m) => (
              <button key={m} onClick={() => setTimer({ running: false, end: 0, left: m * 60000, preset: m })} className={`pill ${timer.preset === m ? "!border-black/30" : ""}`} data-testid={`timer-preset-${m}`}>{m} dk</button>
            ))}
          </div>
          <div className="flex gap-2">
            <Btn kind="primary" onClick={() => setTimer((t) => (t.running ? { ...t, running: false } : { ...t, running: true, end: Date.now() + (t.left || t.preset * 60000) }))} data-testid="timer-toggle">
              {timer.running ? "Duraklat" : "Başlat"}
            </Btn>
            <Btn onClick={() => setTimer((t) => ({ running: false, end: 0, left: t.preset * 60000, preset: t.preset }))} data-testid="timer-reset">Sıfırla</Btn>
          </div>
        </div>
      </div>
    </PanelShell>
  );
}
