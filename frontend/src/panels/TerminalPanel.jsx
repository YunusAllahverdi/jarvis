// Terminal panel — read-only display of policy. Real execution is off unless the
// coding loop / terminal flag is enabled on the backend.
import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell } from "./_shell";
import { Terminal } from "lucide-react";

export default function TerminalPanel() {
  const [health, setHealth] = useState(null);
  useEffect(() => { api.health().then(setHealth).catch(() => {}); }, []);
  const terminalOn = health?.features?.terminal;

  return (
    <PanelShell
      title="Terminal (salt okunur)"
      subtitle="Ajanın komut politikası ve durum bilgisi. Yürütme, kabuk olmadan argüman listesiyle yapılır."
      testId="terminal-panel"
    >
      <div className="p-6">
        <div className="glass-soft rounded-lg p-4 font-mono text-sm space-y-2">
          <div className="flex items-center gap-2 text-muted">
            <Terminal size={12} className="electric-text" />
            <span>~/jarvis</span>
            <span className="opacity-40">·</span>
            <span className={terminalOn ? "text-emerald-300" : "text-amber-300"}>
              {terminalOn ? "TERMINAL AÇIK" : "TERMINAL KAPALI"}
            </span>
          </div>
          <pre className="whitespace-pre-wrap text-secondary text-[12px] leading-relaxed">
{`# Politika
- Komutlar kabuk olmadan çalıştırılır (argüman listesi).
- Zincirleme ve yönlendirme mümkün değil.
- Alt sürece ortam değişkenleri devralınmaz.
- DANGEROUS seviye onay ister; terminal kapalıyken reddedilir.

# İzinli komutlar (örnek küme)
$ pytest -q
$ ruff check .
$ npm test

# Durum: ${terminalOn ? "onaydan geçen komutlar çalıştırılabilir" : "hiçbir komut yürütülemez"}`}
          </pre>
        </div>
        <p className="text-xs text-muted mt-3">
          Terminali açmak için .env dosyasında <span className="font-mono electric-text">JARVIS_TERMINAL_ENABLED=true</span> ayarlayın ve
          çalıştırılabilir komutları <span className="font-mono electric-text">JARVIS_TERMINAL_ALLOWED_COMMANDS</span> ile listelenmiş küme
          içine yazın.
        </p>
      </div>
    </PanelShell>
  );
}
