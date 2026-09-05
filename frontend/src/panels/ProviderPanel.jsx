// Ayarlar — sağlayıcı yapılandırması ve bu cihazın erişim anahtarı.
//
// Emergent sürümü kendi sunucusunun alanlarını kullanıyordu (`provider`)
// ve listesinde OpenAI/Gemini gibi "Emergent" seçenekleri vardı. Bizim
// backend'de alan adı `kind` ve DESTEKLENEN tür yalnızca üç tane. Listeyi
// olduğu gibi bırakmak, seçilince 422 dönen seçenekler sunmak olurdu.
//
// İki farklı anahtar var ve karıştırılmamaları önemli:
//
//   * Sağlayıcı anahtarı — Anthropic/Google'a giden. SUNUCUDA durur,
//     panele geri gelmez; API yalnızca "tanımlı mı" der.
//   * Erişim anahtarı    — bu tarayıcının kendi sunucumuza girmesi için.
//     Tarayıcıda durur ve her isteğe başlık olarak eklenir.
//
// Biri kasanın, diğeri kapının anahtarı. Aynı ekranda ama ayrı kutularda.
import React, { useEffect, useState } from "react";
import { api, getToken, setToken } from "@/lib/api";
import { PanelShell, ErrorNote, LoadingBlock, Btn, Input, Field } from "./_shell";
import { Save, KeyRound } from "lucide-react";

// Backend'in gerçekten tanıdığı türler (LLMProviderKind).
const KINDS = [
  { value: "anthropic", label: "Anthropic (Claude)", url: "https://api.anthropic.com", model: "claude-haiku-4-5", needsKey: true },
  { value: "openai_compatible", label: "OpenAI uyumlu", url: "https://generativelanguage.googleapis.com/v1beta/openai", model: "gemini-2.0-flash", needsKey: true },
  { value: "ollama", label: "Ollama (yerel)", url: "http://127.0.0.1:11434", model: "llama3.2", needsKey: false },
];

const kindInfo = (k) => KINDS.find((x) => x.value === k) || KINDS[0];

export default function ProviderPanel() {
  const [cfg, setCfg] = useState(null);
  const [draft, setDraft] = useState(null);
  const [err, setErr] = useState(null);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState(null);

  const [tokenDraft, setTokenDraft] = useState("");
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    setHasToken(!!getToken());
    api
      .getLLM()
      .then((c) => {
        setCfg(c);
        // Anahtar alanı BOŞ açılır: panel anahtarı geri okuyamaz,
        // dolu göstermek "bu yazılı" yanılgısı yaratırdı.
        setDraft({ ...c, api_key: "", clear_api_key: false });
      })
      .catch(setErr);
  }, []);

  const chooseKind = (value) => {
    const info = kindInfo(value);
    setDraft((d) => ({
      ...d,
      kind: value,
      // Kullanıcının kendi yazdığı adres EZİLMEZ; yalnızca boşsa ya da
      // önerilerden biriyse değiştirilir.
      base_url:
        !d.base_url || KINDS.some((k) => k.url === d.base_url) ? info.url : d.base_url,
    }));
  };

  const save = async () => {
    setSaving(true);
    setErr(null);
    setNote(null);
    try {
      const next = await api.putLLM({
        kind: draft.kind,
        // base_url backend'de zorunlu; boş gönderilirse 422 döner.
        base_url: (draft.base_url || kindInfo(draft.kind).url).trim(),
        model: (draft.model || "").trim() || null,
        ...(draft.api_key ? { api_key: draft.api_key } : {}),
        ...(draft.clear_api_key ? { clear_api_key: true } : {}),
      });
      setCfg(next);
      setDraft({ ...next, api_key: "", clear_api_key: false });
      setNote("Kaydedildi ve devreye alındı.");
    } catch (e) {
      setErr(e);
    } finally {
      setSaving(false);
    }
  };

  const saveToken = () => {
    setToken(tokenDraft);
    setHasToken(!!tokenDraft.trim());
    setTokenDraft("");
    setNote(
      tokenDraft.trim() ? "Erişim anahtarı kaydedildi." : "Erişim anahtarı silindi."
    );
  };

  const info = draft ? kindInfo(draft.kind) : null;

  return (
    <PanelShell
      title="Ayarlar"
      subtitle="Sağlayıcı çalışma zamanında değiştirilir; yeniden başlatma gerekmez."
      testId="provider-panel"
    >
      {err && <ErrorNote err={err} testId="provider-error" />}
      {cfg === null && !err && <LoadingBlock />}

      {draft && (
        <div className="p-6 space-y-6 max-w-xl">
          {note && (
            <p className="text-xs" style={{ color: "#8ff0c8" }} data-testid="provider-note">
              {note}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="pill">
              tür: <b className="text-white ml-1">{kindInfo(cfg.kind).label}</b>
            </span>
            <span className="pill">
              model: <b className="text-white ml-1">{cfg.model || "seçilmedi"}</b>
            </span>
            <span
              className="pill"
              style={
                cfg.has_api_key
                  ? { borderColor: "rgba(16,185,129,0.4)", color: "#8ff0c8" }
                  : { borderColor: "rgba(245,158,11,0.4)", color: "#fbe1a3" }
              }
            >
              {cfg.has_api_key ? "anahtar tanımlı" : "anahtar yok"}
            </span>
          </div>

          <Field label="Sağlayıcı">
            <select
              value={draft.kind}
              onChange={(e) => chooseKind(e.target.value)}
              className="w-full bg-black/30 border hairline rounded-md px-3 py-2 text-sm"
              data-testid="provider-kind"
            >
              {KINDS.map((k) => (
                <option key={k.value} value={k.value}>{k.label}</option>
              ))}
            </select>
          </Field>

          <Field label="Adres" hint="Sağlayıcının kök adresi.">
            <Input
              value={draft.base_url || ""}
              onChange={(e) => setDraft({ ...draft, base_url: e.target.value })}
              placeholder={info.url}
              data-testid="provider-base-url"
            />
          </Field>

          <Field label="Model" hint={`ör. ${info.model}`}>
            <Input
              value={draft.model || ""}
              onChange={(e) => setDraft({ ...draft, model: e.target.value })}
              placeholder={info.model}
              data-testid="provider-model"
            />
          </Field>

          {info.needsKey && (
            <>
              <Field
                label="Sağlayıcı API anahtarı"
                hint="Sunucuda saklanır ve panele geri dönmez. Boş bırakılırsa mevcut anahtar korunur."
              >
                <Input
                  type="password"
                  autoComplete="off"
                  value={draft.api_key || ""}
                  onChange={(e) => setDraft({ ...draft, api_key: e.target.value })}
                  placeholder={cfg.has_api_key ? "değiştirmek için yeni anahtar" : "anahtarı yapıştırın"}
                  data-testid="provider-api-key"
                />
              </Field>

              {cfg.has_api_key && (
                <label className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={!!draft.clear_api_key}
                    onChange={(e) => setDraft({ ...draft, clear_api_key: e.target.checked })}
                    data-testid="provider-clear-key"
                  />
                  Mevcut anahtarı sil
                </label>
              )}
            </>
          )}

          <div>
            <Btn kind="primary" onClick={save} disabled={saving} data-testid="provider-save">
              <Save size={12} className="inline mr-1" />
              {saving ? "Kaydediliyor…" : "Kaydet ve devreye al"}
            </Btn>
          </div>

          <div className="pt-5 border-t hairline space-y-3">
            <div>
              <p className="text-[10px] uppercase tracking-[0.28em] font-mono text-muted">
                Bu cihazın erişim anahtarı
              </p>
              <p className="text-[11px] text-muted mt-1 leading-relaxed">
                Sunucu ağa açıldığında (tabletten kullanmak için) zorunlu olur.
                Sunucudaki <span className="font-mono">JARVIS_API_TOKEN</span>{" "}
                değeriyle aynı olmalı. Sağlayıcı anahtarıyla ilgisi yoktur.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <span
                className="pill"
                style={
                  hasToken
                    ? { borderColor: "rgba(16,185,129,0.4)", color: "#8ff0c8" }
                    : { borderColor: "rgba(255,255,255,0.14)" }
                }
              >
                {hasToken ? "tanımlı" : "yok"}
              </span>
            </div>

            <Input
              type="password"
              autoComplete="off"
              value={tokenDraft}
              onChange={(e) => setTokenDraft(e.target.value)}
              placeholder={hasToken ? "değiştirmek için yeni anahtar" : "anahtarı yapıştırın"}
              data-testid="access-token-input"
            />

            <div className="flex gap-2">
              <Btn onClick={saveToken} data-testid="access-token-save">
                <KeyRound size={12} className="inline mr-1" /> Anahtarı kaydet
              </Btn>
              {hasToken && (
                <Btn
                  kind="danger"
                  onClick={() => { setToken(""); setHasToken(false); setNote("Erişim anahtarı silindi."); }}
                  data-testid="access-token-clear"
                >
                  Sil
                </Btn>
              )}
            </div>
          </div>
        </div>
      )}
    </PanelShell>
  );
}
