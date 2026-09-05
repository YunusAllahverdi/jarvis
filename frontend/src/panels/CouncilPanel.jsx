import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, Empty, ErrorNote, LoadingBlock, Btn, Input, Field } from "./_shell";
import { Crown, Save, Trash2, Plus } from "lucide-react";

const EMPTY_MEMBER = { kind: "openai_compatible", base_url: "", model: "", api_key: "", is_chairman: false };

export default function CouncilPanel() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState(EMPTY_MEMBER);

  const refresh = () => api.getCouncil().then(setData).catch(setErr);
  useEffect(() => { refresh(); }, []);

  const startNew = () => { setEditingId("__new__"); setDraft(EMPTY_MEMBER); };
  const startEdit = (m) => { setEditingId(m.id); setDraft({ ...m, api_key: "", clear_api_key: false }); };
  const save = async () => {
    try {
      const id = editingId === "__new__" ? `member-${Date.now().toString(36)}` : editingId;
      await api.upsertMember(id, draft);
      setEditingId(null);
      refresh();
    } catch (e) { setErr(e); }
  };
  const remove = async (id) => { try { await api.deleteMember(id); refresh(); } catch (e) { setErr(e); } };

  return (
    <PanelShell
      title="Council Üyeleri"
      subtitle="Üye başına sağlayıcı ve anahtar. Etkin üye sayısı en az 2 olmadan Council kurulmaz."
      right={<Btn kind="primary" onClick={startNew} data-testid="council-new"><Plus size={12} className="inline mr-1" /> Üye ekle</Btn>}
      testId="council-panel"
    >
      {err && <ErrorNote err={err} testId="council-error" />}
      {data === null && <LoadingBlock />}
      {data && (
        <div className="p-6 space-y-4">
          <div className="flex items-center gap-2 text-xs">
            <span className="pill" style={{ borderColor: data.active ? "rgba(16,185,129,0.4)" : "rgba(245,158,11,0.4)" }}>
              {data.active ? "Etkin" : `En az ${data.min_candidates} üye gerekli`}
            </span>
            <span className="pill">{data.members.length} üye</span>
          </div>

          {editingId && (
            <div className="glass-soft rounded-lg p-4 space-y-3" data-testid="council-editor">
              <Field label="Kind">
                <select
                  value={draft.kind}
                  onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
                  className="w-full bg-black/30 border hairline rounded-md px-3 py-2 text-sm"
                  data-testid="council-kind"
                >
                  <option value="openai_compatible">OpenAI Uyumlu</option>
                  <option value="ollama">Ollama (yerel)</option>
                  <option value="anthropic">Anthropic</option>
                </select>
              </Field>
              <Field label="Base URL" hint="Ollama için http://127.0.0.1:11434 gibi. Anthropic için boş bırakın.">
                <Input value={draft.base_url || ""} onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} data-testid="council-base-url" />
              </Field>
              <Field label="Model">
                <Input value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} data-testid="council-model" />
              </Field>
              <Field label="API Anahtarı" hint="Boş bırakılırsa mevcut anahtar korunur. Anahtar geri okunmaz.">
                <Input type="password" value={draft.api_key || ""} onChange={(e) => setDraft({ ...draft, api_key: e.target.value })} data-testid="council-api-key" />
              </Field>
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={!!draft.is_chairman} onChange={(e) => setDraft({ ...draft, is_chairman: e.target.checked })} data-testid="council-chairman" />
                <Crown size={12} /> Chairman
              </label>
              <div className="flex gap-2">
                <Btn kind="primary" onClick={save} data-testid="council-save"><Save size={12} className="inline mr-1" /> Kaydet</Btn>
                <Btn onClick={() => setEditingId(null)}>Vazgeç</Btn>
              </div>
            </div>
          )}

          {data.members.length === 0 && !editingId && (
            <Empty label="Henüz üye yok." hint="En az 2 üye tanımlandığında Council devreye girer." testId="council-empty" />
          )}

          <ul className="space-y-2">
            {data.members.map((m) => (
              <li key={m.id} className="glass-soft rounded-lg p-3 flex items-center gap-3" data-testid={`council-member-${m.id}`}>
                {m.is_chairman && <Crown size={14} className="text-amber-400" />}
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-white truncate">{m.id}</p>
                  <p className="text-xs text-muted font-mono truncate">{m.kind} · {m.model} {m.base_url ? `· ${m.base_url}` : ""}</p>
                </div>
                <span className="pill">{m.has_api_key ? "anahtar var" : "anahtar yok"}</span>
                <Btn onClick={() => startEdit(m)}>düzenle</Btn>
                <Btn kind="danger" onClick={() => remove(m.id)} data-testid={`council-del-${m.id}`}><Trash2 size={12} /></Btn>
              </li>
            ))}
          </ul>
        </div>
      )}
    </PanelShell>
  );
}
