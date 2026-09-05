import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, ErrorNote, LoadingBlock, Btn, Input, Field } from "./_shell";
import { Save } from "lucide-react";

export default function ProviderPanel() {
  const [cfg, setCfg] = useState(null);
  const [draft, setDraft] = useState(null);
  const [err, setErr] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getLLM().then((c) => { setCfg(c); setDraft({ ...c, api_key: "", clear_api_key: false }); }).catch(setErr);
  }, []);

  const save = async () => {
    try {
      setSaving(true);
      const next = await api.putLLM({
        provider: draft.provider,
        base_url: draft.base_url || null,
        model: draft.model,
        api_key: draft.api_key || null,
        clear_api_key: !!draft.clear_api_key,
      });
      setCfg(next);
      setDraft({ ...next, api_key: "", clear_api_key: false });
    } catch (e) { setErr(e); } finally { setSaving(false); }
  };

  return (
    <PanelShell
      title="Sağlayıcı Ayarları"
      subtitle="Çalışma zamanında değiştirilebilir. Anahtar sunucuda saklanır ve panele geri dönmez."
      testId="provider-panel"
    >
      {err && <ErrorNote err={err} testId="provider-error" />}
      {cfg === null && <LoadingBlock />}
      {draft && (
        <div className="p-6 space-y-4 max-w-xl">
          <div className="flex items-center gap-2 text-xs">
            <span className="pill">provider: <b className="text-white ml-1">{cfg.provider}</b></span>
            <span className="pill">model: <b className="text-white ml-1">{cfg.model}</b></span>
            <span className="pill" style={{ borderColor: cfg.has_api_key ? "rgba(16,185,129,0.4)" : "rgba(239,68,68,0.35)" }}>
              {cfg.has_api_key ? "anahtar tanımlı" : "anahtar yok"}
            </span>
          </div>

          <Field label="Sağlayıcı Türü">
            <select
              value={draft.provider}
              onChange={(e) => setDraft({ ...draft, provider: e.target.value })}
              className="w-full bg-black/30 border hairline rounded-md px-3 py-2 text-sm"
              data-testid="provider-kind"
            >
              <option value="anthropic">Anthropic (Emergent)</option>
              <option value="openai">OpenAI (Emergent)</option>
              <option value="gemini">Gemini (Emergent)</option>
              <option value="openai_compatible">OpenAI Uyumlu (özel)</option>
              <option value="ollama">Ollama (yerel)</option>
            </select>
          </Field>

          <Field label="Base URL" hint="Yalnızca OpenAI uyumlu / Ollama sağlayıcıları için gerekli.">
            <Input value={draft.base_url || ""} onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} data-testid="provider-base-url" />
          </Field>

          <Field label="Model">
            <Input value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} data-testid="provider-model" />
          </Field>

          <Field label="API Anahtarı" hint="Boş bırakılırsa mevcut anahtar korunur.">
            <Input type="password" value={draft.api_key || ""} onChange={(e) => setDraft({ ...draft, api_key: e.target.value })} data-testid="provider-api-key" />
          </Field>

          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={!!draft.clear_api_key} onChange={(e) => setDraft({ ...draft, clear_api_key: e.target.checked })} data-testid="provider-clear-key" />
            Mevcut anahtarı sil
          </label>

          <div>
            <Btn kind="primary" onClick={save} disabled={saving} data-testid="provider-save">
              <Save size={12} className="inline mr-1" /> {saving ? "Kaydediliyor…" : "Kaydet ve devreye al"}
            </Btn>
          </div>
        </div>
      )}
    </PanelShell>
  );
}
