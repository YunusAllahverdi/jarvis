// Tanılama — sistemin GERÇEKTEN ölçülebilen hâli.
//
// Emergent sürümü `/diagnostics` ve `/insight` adında iki uçtan besleniyordu;
// bizim backend'de ikisi de yok. Uydurulmuş sayılar göstermek yerine panel
// var olan uçlara göre yeniden yazıldı:
//
//   /api/v1/health      → sunucu ayakta mı, hangi sürüm
//   /api/admin/llm      → hangi sağlayıcı ve model bağlı
//   /api/system/status  → CPU, bellek, disk (gerçek ölçüm)
//   /api/agent/tools    → ajanın ELİNDE olan araçlar ve izin seviyeleri
//   /api/notes|approvals|checkpoints → sayımlar
//
// Araç listesi burada bilerek var: "izin duruşu" sabit bir metin olarak
// yazılabilirdi ama o zaman ekrandaki söz ile sistemin gerçeği ayrışabilirdi.
// Liste doğrudan kayıttan geldiği için, kapalı bir yetenek burada da yoktur.
import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, ErrorNote, LoadingBlock } from "./_shell";

function StatBox({ label, value, sub, tone = "electric" }) {
  const c = { electric: "#2F6FED", green: "#34C759", amber: "#FF9F0A", red: "#FF375F" }[tone];
  return (
    <div className="glass-soft rounded-lg p-4">
      <p className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted">{label}</p>
      <p className="text-2xl font-display mt-1" style={{ color: c }}>{value}</p>
      {sub && <p className="text-[11px] text-muted mt-0.5">{sub}</p>}
    </div>
  );
}

const gb = (b) => (b / 1024 ** 3).toFixed(1);

// Yük arttıkça renk değişir; %90 üstü kırmızı olmalı ki sorun göze çarpsın.
const loadTone = (pct) => (pct >= 90 ? "red" : pct >= 75 ? "amber" : "green");

// READ sessizce çalışır; WRITE ve üstü onaydan geçer. Renk bu ayrımı taşır.
const permTone = (p) => (String(p).toUpperCase() === "READ" ? "green" : "amber");

export default function DiagnosticsPanel() {
  const [health, setHealth] = useState(null);
  const [llm, setLlm] = useState(null);
  const [sys, setSys] = useState(null);
  const [tools, setTools] = useState(null);
  const [counts, setCounts] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    // Her çağrı AYRI yakalanıyor: biri kapalıysa (ör. ajan bağlı değilse)
    // panelin geri kalanı yine görünmeli. Tek bir Promise.all hepsini
    // birden düşürürdü.
    api.health().then(setHealth).catch(setErr);
    api.getLLM().then(setLlm).catch(() => setLlm(null));
    api.systemStatus().then(setSys).catch(() => setSys(null));
    api.agentTools().then((r) => setTools(r.tools || [])).catch(() => setTools([]));

    Promise.all([
      api.listNotes().then((r) => r.notes.length).catch(() => null),
      api.listApprovals().then((r) => r.approvals.length).catch(() => null),
      api.listCheckpoints().then((r) => r.checkpoints.length).catch(() => null),
    ]).then(([notes, approvals, checkpoints]) =>
      setCounts({ notes, approvals, checkpoints })
    );
  }, []);

  return (
    <PanelShell
      title="Sistem Tanılama"
      subtitle="Ölçülen değerler. Buradaki her sayı bir uçtan geliyor; sabit yazılmış hiçbir şey yok."
      testId="diagnostics-panel"
    >
      {err && <ErrorNote err={err} testId="diag-error" />}
      {!health && !err && <LoadingBlock />}

      {health && (
        <div className="p-6 space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <StatBox
              label="Notlar"
              value={counts?.notes ?? "—"}
              sub={counts?.notes === null ? "okunamadı" : "kalıcı"}
            />
            <StatBox
              label="Bekleyen onay"
              value={counts?.approvals ?? "—"}
              tone={counts?.approvals > 0 ? "amber" : "electric"}
              sub={counts?.approvals > 0 ? "karar bekliyor" : "temiz"}
            />
            <StatBox
              label="Checkpoint"
              value={counts?.checkpoints ?? "—"}
              sub="geri alınabilir"
            />
            {sys && (
              <>
                <StatBox
                  label="İşlemci"
                  value={`%${sys.cpu_percent.toFixed(0)}`}
                  tone={loadTone(sys.cpu_percent)}
                  sub={sys.is_local ? "bu makine" : "sunucunun makinesi"}
                />
                <StatBox
                  label="Bellek"
                  value={`%${sys.memory_percent.toFixed(0)}`}
                  tone={loadTone(sys.memory_percent)}
                  sub={`${gb(sys.memory_available_bytes)} GB boş`}
                />
                <StatBox
                  label="Disk"
                  value={`%${sys.disk_percent.toFixed(0)}`}
                  tone={loadTone(sys.disk_percent)}
                  sub={`${gb(sys.disk_free_bytes)} GB boş`}
                />
              </>
            )}
          </div>

          <div>
            <p className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted mb-2">
              Sunucu
            </p>
            <div className="flex flex-wrap gap-2">
              <span className="pill">
                durum: <b className="ml-1 text-white">{health.status}</b>
              </span>
              {health.version && (
                <span className="pill">
                  sürüm: <b className="ml-1 text-white">{health.version}</b>
                </span>
              )}
              {health.environment && (
                <span className="pill">
                  ortam: <b className="ml-1 text-white">{health.environment}</b>
                </span>
              )}
            </div>
          </div>

          <div>
            <p className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted mb-2">
              Sağlayıcı
            </p>
            {llm ? (
              <div className="flex flex-wrap gap-2">
                <span className="pill">
                  tür: <b className="ml-1 text-white">{llm.kind}</b>
                </span>
                <span className="pill">
                  model: <b className="ml-1 text-white">{llm.model || "seçilmedi"}</b>
                </span>
                <span
                  className="pill"
                  style={
                    llm.has_api_key
                      ? { borderColor: "rgba(16,185,129,0.4)", color: "#8ff0c8" }
                      : { borderColor: "rgba(245,158,11,0.4)", color: "#fbe1a3" }
                  }
                >
                  anahtar: {llm.has_api_key ? "tanımlı" : "yok"}
                </span>
              </div>
            ) : (
              <p className="text-xs text-muted">Sağlayıcı ayarı okunamadı.</p>
            )}
          </div>

          <div>
            <p className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted mb-2">
              Ajanın Araçları {tools && `· ${tools.length}`}
            </p>
            {tools === null ? (
              <p className="text-xs text-muted">Yükleniyor…</p>
            ) : tools.length === 0 ? (
              <p className="text-xs text-muted">
                Kayıtlı araç yok — ajan bu örnekte bağlı değil. Her yetenek
                varsayılan olarak kapalıdır.
              </p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {tools.map((t) => (
                  <span
                    key={t.name}
                    className="pill font-mono"
                    title={t.description}
                    style={
                      permTone(t.permission) === "green"
                        ? { borderColor: "rgba(16,185,129,0.35)", color: "#8ff0c8" }
                        : { borderColor: "rgba(245,158,11,0.35)", color: "#fbe1a3" }
                    }
                  >
                    {t.name}
                  </span>
                ))}
              </div>
            )}
            <p className="text-[11px] text-muted mt-2 leading-relaxed">
              Yeşil araçlar READ izinlidir ve sessizce çalışır. Sarı olanlar
              WRITE ve üstüdür; her çağrıları Onaylar panelinden geçer.
            </p>
          </div>
        </div>
      )}
    </PanelShell>
  );
}
