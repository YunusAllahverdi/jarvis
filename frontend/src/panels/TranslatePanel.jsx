// Translate — Apple Translate-like two-pane UI backed by the LLM.
import React, { useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, ErrorNote, TextArea, Btn } from "./_shell";
import { ArrowRightLeft, Copy, Check } from "lucide-react";

const LANGS = [
  { code: "en", name: "İngilizce" }, { code: "tr", name: "Türkçe" }, { code: "de", name: "Almanca" },
  { code: "fr", name: "Fransızca" }, { code: "es", name: "İspanyolca" }, { code: "it", name: "İtalyanca" },
  { code: "ja", name: "Japonca" }, { code: "ar", name: "Arapça" }, { code: "ru", name: "Rusça" },
];

export default function TranslatePanel() {
  const [text, setText] = useState("");
  const [target, setTarget] = useState("en");
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [copied, setCopied] = useState(false);

  const run = async () => {
    if (!text.trim() || busy) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.translate(text.trim(), target);
      setOut(r.translation);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };

  const copy = () => navigator.clipboard?.writeText(out).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); });

  return (
    <PanelShell title="Çeviri" subtitle="Metni yaz, hedef dili seç — Jarvis çevirir." testId="translate-panel">
      {err && <ErrorNote err={err} testId="translate-error" />}
      <div className="p-6 max-w-4xl">
        <div className="flex items-center gap-2 mb-3">
          <span className="pill">Otomatik algıla</span>
          <ArrowRightLeft size={14} className="text-muted" />
          <select value={target} onChange={(e) => setTarget(e.target.value)} className="pill bg-transparent outline-none cursor-pointer" data-testid="translate-target">
            {LANGS.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
          </select>
          <Btn kind="primary" className="ml-auto" onClick={run} disabled={busy || !text.trim()} data-testid="translate-run">
            {busy ? "Çevriliyor…" : "Çevir"}
          </Btn>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <TextArea rows={8} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && run()} placeholder="Çevrilecek metin… (⌘+Enter)" data-testid="translate-input" />
          <div className="relative glass-soft rounded-md p-3 min-h-[200px] text-sm whitespace-pre-wrap" data-testid="translate-output">
            {out || <span className="text-muted">Çeviri burada görünür.</span>}
            {out && (
              <button onClick={copy} className="absolute top-2 right-2 text-muted hover:text-black" aria-label="Kopyala" data-testid="translate-copy">
                {copied ? <Check size={14} color="#34c759" /> : <Copy size={14} />}
              </button>
            )}
          </div>
        </div>
      </div>
    </PanelShell>
  );
}
