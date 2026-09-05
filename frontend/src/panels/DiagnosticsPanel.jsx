import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, ErrorNote, LoadingBlock } from "./_shell";

function StatBox({ label, value, tone = "electric" }) {
  const c = { electric: "#2F6FED", green: "#34C759", amber: "#FF9F0A", red: "#FF375F" }[tone];
  return (
    <div className="glass-soft rounded-lg p-4">
      <p className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted">{label}</p>
      <p className="text-2xl font-display mt-1" style={{ color: c }}>{value}</p>
    </div>
  );
}

export default function DiagnosticsPanel() {
  const [data, setData] = useState(null);
  const [health, setHealth] = useState(null);
  const [insight, setInsight] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.diagnostics().then(setData).catch(setErr);
    api.health().then(setHealth).catch(setErr);
    api.insight().then(setInsight).catch(() => {});
  }, []);

  return (
    <PanelShell
      title="Sistem Tanılama"
      subtitle="İzin duruşu, denetim kaydı ve sağlayıcı özeti."
      testId="diagnostics-panel"
    >
      {err && <ErrorNote err={err} testId="diag-error" />}
      {(!data || !health) && <LoadingBlock />}
      {data && health && (
        <div className="p-6 space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatBox label="Notlar" value={data.counts.notes} />
            <StatBox label="Onay" value={data.counts.approvals} tone={data.counts.approvals > 0 ? "amber" : "electric"} />
            <StatBox label="Checkpoint" value={data.counts.checkpoints} />
            <StatBox label="Oturum" value={data.counts.sessions} />
            <StatBox label="Mesaj" value={data.counts.messages} />
            <StatBox label="Denetim" value={data.counts.audit} />
          </div>

          <div>
            <p className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted mb-2">İzin Duruşu</p>
            <div className="flex flex-wrap gap-2">
              <span className="pill" style={{ borderColor: "rgba(16,185,129,0.4)", color: "#8ff0c8" }}>READ: serbest</span>
              <span className="pill" style={{ borderColor: "rgba(245,158,11,0.4)", color: "#fbe1a3" }}>WRITE: onaydan geçer</span>
              <span className="pill" style={{ borderColor: data.permissions.dangerous === "denied" ? "rgba(239,68,68,0.4)" : "rgba(245,158,11,0.4)", color: data.permissions.dangerous === "denied" ? "#ffbcbc" : "#fbe1a3" }}>
                DANGEROUS: {data.permissions.dangerous === "denied" ? "reddedilir" : "onaya tabi"}
              </span>
            </div>
          </div>

          <div>
            <p className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted mb-2">Sağlayıcı</p>
            <div className="flex flex-wrap gap-2">
              <span className="pill">provider: <b className="ml-1 text-white">{health.provider}</b></span>
              <span className="pill">model: <b className="ml-1 text-white">{health.model}</b></span>
              <span className="pill">tz: <b className="ml-1 text-white">{health.timezone}</b></span>
            </div>
          </div>

          {insight && (
            <div>
              <p className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted mb-2">Kullanıcı Modeli (traits)</p>
              <ul className="space-y-1">
                {insight.traits.map((t, i) => (
                  <li key={i} className="text-sm text-secondary">
                    <span className="font-mono electric-text">{t.key}</span>: <span className="text-white">{String(t.value)}</span>
                    <span className="ml-2 text-muted">conf {Math.round(t.confidence * 100)}%</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <p className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted mb-2">Son Denetim Olayları</p>
            {data.recent_audit.length === 0 ? (
              <p className="text-xs text-muted">Kayıt yok.</p>
            ) : (
              <ul className="space-y-1 text-xs font-mono">
                {data.recent_audit.slice(0, 12).map((e, i) => (
                  <li key={i} className="text-secondary">
                    <span className="text-muted">{new Date(e.timestamp).toLocaleTimeString("tr-TR")}</span>{" "}
                    <span className="electric-text">{e.kind}</span>{" "}
                    <span>{e.session_id || e.approval_id || e.checkpoint_id || ""}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </PanelShell>
  );
}
