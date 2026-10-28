import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, Empty, ErrorNote, LoadingBlock, Btn } from "./_shell";
import { ShieldAlert, Lock, Unlock, RefreshCw } from "lucide-react";

// İzin seviyesi rozetleri. Renk kodu bilinçli olarak sabittir:
// READ yeşil (serbest), WRITE sarı (onay gerekir), DANGEROUS kırmızı
// (bayrak açık değilse reddedilir). Aynı renk panelin her yerinde
// aynı anlama gelir; kullanıcı renkten seviyeyi okuyabilmelidir.
const LEVEL_STYLE = {
  READ: { bg: "rgba(52,199,89,0.14)", fg: "#8ee7a6", border: "rgba(52,199,89,0.4)" },
  WRITE: { bg: "rgba(255,204,0,0.14)", fg: "#fbe1a3", border: "rgba(255,204,0,0.4)" },
  DANGEROUS: { bg: "rgba(255,69,58,0.16)", fg: "#ff9a91", border: "rgba(255,69,58,0.45)" },
};

const RISK_LABEL = {
  network: "ağ",
  filesystem: "dosya",
  device: "cihaz",
  money: "para",
  irreversible: "geri alınamaz",
  personal_data: "kişisel veri",
};

function LevelBadge({ level, testId }) {
  const s = LEVEL_STYLE[level] || LEVEL_STYLE.READ;
  return (
    <span
      className="text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded border"
      style={{ background: s.bg, color: s.fg, borderColor: s.border }}
      data-testid={testId}
    >
      {level}
    </span>
  );
}

export default function CapabilitiesPanel() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(
    () =>
      api
        .getCapabilities()
        .then((r) => {
          setData(r);
          setErr(null);
        })
        .catch(setErr),
    []
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Override uygular. Düşürme isteniyorsa ÖNCE onay alınır: sessiz bir
  // WRITE → READ bir yetki genişlemesidir ve kullanıcının bunu açıkça
  // istediğinden emin olunmalıdır.
  const apply = async (tool, body, needsConfirm) => {
    if (needsConfirm) {
      const ok = window.confirm(
        `"${tool.name}" aracının izin seviyesini ${tool.permission} → ${body.permission} ` +
          `düşürmek üzeresin. Bu, aracın onay akışını zayıflatır ve denetim kaydına ` +
          `"permission_downgrade" olarak yazılır. Devam edilsin mi?`
      );
      if (!ok) return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const r = await api.setToolOverride(tool.name, body);
      setNotice({
        text: r.accepted ? r.reason : `Reddedildi: ${r.reason}`,
        error: !r.accepted,
      });
      await refresh();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const toggle = (tool) => apply(tool, { enabled: !tool.enabled }, false);

  const upgrade = (tool, level) => apply(tool, { permission: level }, false);

  const downgrade = (tool, level) =>
    apply(tool, { permission: level, allow_downgrade: true }, true);

  // Skill'ler yalnızca aç/kapa edilir; izin seviyesi kavramı yoktur (izin,
  // skill'in araçlarının kendi seviyesinden gelir). Bu yüzden onay istemez.
  const toggleSkill = async (skill) => {
    setBusy(true);
    setNotice(null);
    try {
      const r = await api.setSkillOverride(skill.slug, { enabled: !skill.enabled });
      setNotice({
        text: r.accepted ? r.reason : `Reddedildi: ${r.reason}`,
        error: !r.accepted,
      });
      await refresh();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelShell
      title="Yetenek Kaydı"
      subtitle="Sağlayıcılar, skill'ler ve araçlar. İzin yükseltme serbest; düşürme yalnızca onayla."
      testId="capabilities-panel"
      command="capabilities"
      onCommandDone={refresh}
      right={
        <Btn kind="ghost" onClick={refresh} disabled={busy} data-testid="capabilities-refresh">
          <RefreshCw size={12} className="inline mr-1" /> Yenile
        </Btn>
      }
    >
      {err && <ErrorNote err={err} testId="capabilities-error" />}
      {notice && (
        <div
          className={`m-6 mb-0 p-3 rounded-lg border text-xs ${
            notice.error ? "border-red-500/40 text-red-300" : "border-emerald-500/30 text-emerald-200"
          }`}
          data-testid="capabilities-notice"
        >
          {notice.text}
        </div>
      )}
      {data === null && !err && <LoadingBlock />}
      {data && (
        <div className="p-6 space-y-6">
          {data.errors?.length > 0 && (
            <div className="rounded-lg p-3 border border-amber-500/30 bg-amber-500/5" data-testid="capabilities-warnings">
              <p className="text-[10px] uppercase tracking-[0.28em] font-mono text-amber-200 mb-1">
                Kayıt uyarıları
              </p>
              {data.errors.map((e, i) => (
                <p key={i} className="text-xs text-amber-100/90">
                  {e}
                </p>
              ))}
            </div>
          )}

          <section data-testid="capabilities-providers">
            <h3 className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted mb-2">
              Sağlayıcılar
            </h3>
            <div className="space-y-2">
              {(data.providers || []).map((p) => (
                <div
                  key={p.id}
                  className="glass-soft rounded-lg px-4 py-2.5 flex items-center justify-between gap-3"
                  data-testid={`provider-${p.id}`}
                >
                  <div className="min-w-0">
                    <p className="text-sm text-white font-mono">{p.id}</p>
                    {p.description && <p className="text-xs text-muted truncate">{p.description}</p>}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-[11px] text-muted">{p.tool_count} araç</span>
                    <span
                      className={`text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded border ${
                        p.enabled
                          ? "border-emerald-500/40 text-emerald-200"
                          : "border-white/15 text-muted"
                      }`}
                      data-testid={`provider-state-${p.id}`}
                    >
                      {p.enabled ? "açık" : "kapalı"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section data-testid="capabilities-skills">
            <h3 className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted mb-2">
              Skill'ler
            </h3>
            {(data.skills || []).length === 0 ? (
              <Empty
                label="Keşfedilen skill yok."
                hint="skills/ klasörüne agentskills.io biçiminde bir SKILL.md koyun; ayrıntılar docs/skills.md."
                testId="capabilities-skills-empty"
              />
            ) : (
              <div className="space-y-3">
                {data.skills.map((s) => (
                  <div key={s.slug} className="glass-soft rounded-lg p-4" data-testid={`skill-${s.slug}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="text-sm text-white font-mono">{s.name}</p>
                          {s.license && (
                            <span className="text-[10px] font-mono text-muted border hairline rounded px-1.5 py-0.5">
                              {s.license}
                            </span>
                          )}
                          <span
                            className={`text-[10px] font-mono uppercase tracking-widest px-2 py-0.5 rounded border ${
                              s.enabled
                                ? "border-emerald-500/40 text-emerald-200"
                                : "border-white/15 text-muted"
                            }`}
                            data-testid={`skill-state-${s.slug}`}
                          >
                            {s.enabled ? "açık" : "kapalı"}
                          </span>
                        </div>
                        <p className="text-xs text-muted mt-1.5 leading-relaxed">{s.description}</p>
                        {s.source && (
                          <a
                            href={s.source}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="text-[10px] text-secondary hover:underline break-all mt-2 inline-block"
                            data-testid={`skill-source-${s.slug}`}
                          >
                            {s.source}
                            {s.source_sha ? ` @ ${s.source_sha.slice(0, 12)}` : ""}
                          </a>
                        )}
                      </div>
                      <div className="flex flex-col gap-2 shrink-0 w-36">
                        <Btn
                          kind={s.enabled ? "ghost" : "primary"}
                          onClick={() => toggleSkill(s)}
                          disabled={busy}
                          data-testid={`skill-toggle-${s.slug}`}
                        >
                          {s.enabled ? (
                            <>
                              <Lock size={11} className="inline mr-1" /> Kapat
                            </>
                          ) : (
                            <>
                              <Unlock size={11} className="inline mr-1" /> Aç
                            </>
                          )}
                        </Btn>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section data-testid="capabilities-tools">
            <h3 className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted mb-2">
              Araçlar
            </h3>
            {(data.tools || []).length === 0 ? (
              <Empty
                label="Kayıtlı araç yok."
                hint="Yetenekler varsayılan olarak KAPALI doğar; .env üzerinden bir aile açıldığında araçları burada görünür."
                testId="capabilities-empty"
              />
            ) : (
              <div className="space-y-3">
                {data.tools.map((t) => (
                  <div key={t.name} className="glass-soft rounded-lg p-4" data-testid={`tool-${t.name}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="text-sm text-white font-mono">{t.name}</p>
                          <span className="text-[10px] font-mono text-muted border hairline rounded px-1.5 py-0.5">
                            {t.source}
                          </span>
                          {t.category && (
                            <span className="text-[10px] text-muted">{t.category}</span>
                          )}
                          <LevelBadge level={t.permission} testId={`tool-level-${t.name}`} />
                          {t.declared_permission !== t.permission && (
                            <span
                              className="text-[10px] text-muted"
                              data-testid={`tool-declared-${t.name}`}
                            >
                              (beyan: {t.declared_permission})
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted mt-1.5 leading-relaxed">{t.description}</p>
                        <div className="flex items-center gap-2 flex-wrap mt-2">
                          {(t.risk_tags || []).map((tag) => (
                            <span
                              key={tag}
                              className="text-[10px] font-mono text-secondary bg-white/5 rounded px-1.5 py-0.5"
                            >
                              {RISK_LABEL[tag] || tag}
                            </span>
                          ))}
                          {t.untrusted_output && (
                            <span className="text-[10px] font-mono text-amber-200 bg-amber-500/10 border border-amber-500/30 rounded px-1.5 py-0.5 flex items-center gap-1">
                              <ShieldAlert size={10} /> güvenilmez çıktı
                            </span>
                          )}
                          {t.requires_approval && (
                            <span className="text-[10px] font-mono text-muted">onay gerekir</span>
                          )}
                          {t.timeout_seconds != null && (
                            <span className="text-[10px] font-mono text-muted">
                              {t.timeout_seconds}s sınır
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="flex flex-col gap-2 shrink-0 w-36">
                        <Btn
                          kind={t.enabled ? "ghost" : "primary"}
                          onClick={() => toggle(t)}
                          disabled={busy}
                          data-testid={`tool-toggle-${t.name}`}
                        >
                          {t.enabled ? (
                            <>
                              <Lock size={11} className="inline mr-1" /> Kapat
                            </>
                          ) : (
                            <>
                              <Unlock size={11} className="inline mr-1" /> Aç
                            </>
                          )}
                        </Btn>

                        {t.permission !== "DANGEROUS" && (
                          <Btn
                            kind="ghost"
                            onClick={() => upgrade(t, "DANGEROUS")}
                            disabled={busy}
                            data-testid={`tool-upgrade-${t.name}`}
                          >
                            DANGEROUS'a yükselt
                          </Btn>
                        )}

                        {/* Düşürme yalnızca READ değilken ve DANGEROUS değilken
                            sunulur: DANGEROUS düşürme sunucuda reddedilir,
                            bu yüzden düğmeyi hiç göstermemek doğrudur. */}
                        {t.permission === "WRITE" && (
                          <Btn
                            kind="danger"
                            onClick={() => downgrade(t, "READ")}
                            disabled={busy}
                            data-testid={`tool-downgrade-${t.name}`}
                          >
                            READ'e düşür
                          </Btn>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </PanelShell>
  );
}
