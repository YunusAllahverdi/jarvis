import React, { useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, ErrorNote, Btn, TextArea, Field } from "./_shell";
import { Play } from "lucide-react";

const STATUS_STYLES = {
  completed:            { color: "#10B981", label: "Doğrulandı" },
  applied_unverified:   { color: "#F59E0B", label: "Uygulandı — doğrulanmadı" },
  no_plan:              { color: "#94A3B8", label: "Plan yok" },
  failed:               { color: "#EF4444", label: "Başarısız" },
  skipped:              { color: "#94A3B8", label: "Atlandı" },
};

export default function CodingPanel() {
  const [message, setMessage] = useState("");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    if (!message.trim()) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.codingRun(message.trim());
      setResult(r);
    } catch (e) { setErr(e); }
    finally { setBusy(false); }
  };

  return (
    <PanelShell
      title="Kodlama Stüdyosu"
      subtitle="Anla → planla → uygula → doğrula → düzelt. Yalnızca doğrulanmış sonuçlar 'completed' olur."
      testId="coding-panel"
    >
      {err && <ErrorNote err={err} testId="coding-error" />}
      <div className="p-6 space-y-3 max-w-3xl">
        <Field label="İstek">
          <TextArea rows={4} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Örn: tests/test_x.py'daki başarısız testi düzelt" data-testid="coding-input" />
        </Field>
        <Btn kind="primary" onClick={run} disabled={busy || !message.trim()} data-testid="coding-run">
          <Play size={12} className="inline mr-1" /> {busy ? "Çalışıyor…" : "Turu başlat"}
        </Btn>

        {result && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-2">
              <span className="pill" style={{ borderColor: (STATUS_STYLES[result.status]?.color || "#8884") + "AA", color: STATUS_STYLES[result.status]?.color }}>
                {STATUS_STYLES[result.status]?.label || result.status}
              </span>
              <span className="pill font-mono">rounds: {result.rounds?.length || 0}</span>
              <span className="pill font-mono">approvals: {result.pending_approval_ids?.length || 0}</span>
            </div>
            <div className="glass-soft rounded-lg p-4">
              <p className="text-xs uppercase tracking-widest text-muted font-mono">Özet</p>
              <p className="text-sm text-white mt-1">{result.summary}</p>
            </div>
            {result.diff && (
              <details className="glass-soft rounded-lg p-4" data-testid="coding-diff">
                <summary className="cursor-pointer text-xs uppercase tracking-widest text-muted font-mono">git diff</summary>
                <pre className="text-[11px] font-mono text-secondary mt-3 whitespace-pre-wrap">{result.diff}</pre>
              </details>
            )}
          </div>
        )}
      </div>
    </PanelShell>
  );
}
