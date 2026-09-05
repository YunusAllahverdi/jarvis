// Global keyboard command palette (Cmd+K / Ctrl+K)
import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Command } from "lucide-react";

const ACTIONS = [
  { id: "nav-home",   label: "Ana Ekran'a git",           kbd: "H", to: "/" },
  { id: "nav-chat",   label: "Sohbet Sayfası'nı aç",       kbd: "C", to: "/chat" },
  { id: "nav-cowork", label: "Cowork Çalışma Alanı'nı aç", kbd: "W", to: "/cowork" },
  { id: "panel-notes",      label: "Cowork › Notlar",                   to: "/cowork?panel=notes" },
  { id: "panel-calendar",   label: "Cowork › Takvim",                   to: "/cowork?panel=calendar" },
  { id: "panel-reminders",  label: "Cowork › Hatırlatıcılar",           to: "/cowork?panel=reminders" },
  { id: "panel-weather",    label: "Cowork › Hava Durumu",              to: "/cowork?panel=weather" },
  { id: "panel-clock",      label: "Cowork › Saat",                     to: "/cowork?panel=clock" },
  { id: "panel-translate",  label: "Cowork › Çeviri",                   to: "/cowork?panel=translate" },
  { id: "panel-approvals",  label: "Cowork › Onaylar",                  to: "/cowork?panel=approvals" },
  { id: "panel-council",    label: "Cowork › Council",                  to: "/cowork?panel=council" },
  { id: "panel-provider",   label: "Cowork › Sağlayıcı",                to: "/cowork?panel=provider" },
  { id: "panel-memory",     label: "Cowork › Bellek",                   to: "/cowork?panel=memory" },
  { id: "panel-coding",     label: "Cowork › Kod Stüdyosu",             to: "/cowork?panel=coding" },
  { id: "panel-checkpoints",label: "Cowork › Checkpoint",               to: "/cowork?panel=checkpoints" },
  { id: "panel-diag",       label: "Cowork › Tanılama",                 to: "/cowork?panel=diagnostics" },
  { id: "panel-terminal",   label: "Cowork › Terminal",                 to: "/cowork?panel=terminal" },
  { id: "panel-calculator", label: "Cowork › Hesap Makinesi",           to: "/cowork?panel=calculator" },
];

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return ACTIONS;
    return ACTIONS.filter((a) => a.label.toLowerCase().includes(s));
  }, [q]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-24"
      data-testid="command-palette"
      onClick={() => setOpen(false)}
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative w-[min(680px,92vw)] glass rounded-xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b hairline">
          <Command size={16} className="electric-text" />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Komut yazın — panel açın, sayfa değiştirin, model seçin…"
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-muted"
            data-testid="palette-input"
          />
          <span className="pill font-mono">esc</span>
        </div>
        <ul className="max-h-[52vh] overflow-y-auto py-1">
          {filtered.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-muted">Eşleşme yok.</li>
          )}
          {filtered.map((a) => (
            <li key={a.id}>
              <button
                data-testid={`palette-item-${a.id}`}
                className="w-full flex items-center justify-between px-4 py-2.5 text-sm hover:bg-white/5"
                onClick={() => { setOpen(false); navigate(a.to); }}
              >
                <span>{a.label}</span>
                {a.kbd && <span className="pill font-mono">{a.kbd}</span>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
