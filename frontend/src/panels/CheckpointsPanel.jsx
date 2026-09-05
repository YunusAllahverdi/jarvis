import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, Empty, ErrorNote, LoadingBlock, Btn } from "./_shell";
import { Undo2 } from "lucide-react";

export default function CheckpointsPanel() {
  const [items, setItems] = useState(null);
  const [err, setErr] = useState(null);

  const refresh = () => api.listCheckpoints().then((r) => setItems(r.checkpoints || [])).catch(setErr);
  useEffect(() => { refresh(); }, []);

  const restore = async (id) => { try { await api.restoreCheckpoint(id); refresh(); } catch (e) { setErr(e); } };

  return (
    <PanelShell
      title="Geri Alma Noktaları"
      subtitle="Bir dosya değiştirilmeden önceki hâli. Geri alma kullanıcının kararıdır, ajanın aracı değildir."
      testId="checkpoints-panel"
      command="checkpoints"
      onCommandDone={refresh}
    >
      {err && <ErrorNote err={err} testId="cp-error" />}
      {items === null && <LoadingBlock />}
      {items && items.length === 0 && (
        <Empty label="Geri alma noktası yok." hint="Ajan bir dosya değiştirdiğinde önceki hâl burada birikir." testId="cp-empty" />
      )}
      {items && items.length > 0 && (
        <ul className="p-6 space-y-2">
          {items.map((c) => (
            <li key={c.id} className="glass-soft rounded-lg p-3 flex items-center gap-3" data-testid={`cp-item-${c.id}`}>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white truncate">{c.label || c.path}</p>
                <p className="text-xs text-muted font-mono truncate">{c.path} · {new Date(c.created_at).toLocaleString("tr-TR")}</p>
              </div>
              {c.restored ? (
                <span className="pill" style={{ borderColor: "rgba(16,185,129,0.4)", color: "#8ff0c8" }}>geri alındı</span>
              ) : (
                <Btn kind="primary" onClick={() => restore(c.id)} data-testid={`cp-restore-${c.id}`}><Undo2 size={12} className="inline mr-1" /> Geri al</Btn>
              )}
            </li>
          ))}
        </ul>
      )}
    </PanelShell>
  );
}
