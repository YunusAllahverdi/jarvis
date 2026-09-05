import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, Empty, ErrorNote, LoadingBlock, Btn } from "./_shell";
import { Check, X as XIcon } from "lucide-react";

export default function ApprovalsPanel() {
  const [items, setItems] = useState(null);
  const [err, setErr] = useState(null);

  const refresh = () => api.listApprovals().then((r) => setItems(r.approvals || [])).catch(setErr);
  useEffect(() => { refresh(); const t = setInterval(refresh, 8000); return () => clearInterval(t); }, []);

  const decide = async (id, decision) => {
    try { await api.decideApproval(id, decision); refresh(); } catch (e) { setErr(e); }
  };

  return (
    <PanelShell
      title="Onay Bekleyenler"
      subtitle="WRITE ve DANGEROUS seviyeler her zaman onaydan geçer. Onay tek kullanımlıktır."
      testId="approvals-panel"
      command="approvals"
      onCommandDone={refresh}
    >
      {err && <ErrorNote err={err} testId="approvals-error" />}
      {items === null && <LoadingBlock />}
      {items && items.length === 0 && (
        <Empty
          label="Bekleyen onay yok."
          hint="Bir araç WRITE veya DANGEROUS seviyeye ulaştığında burada görünür ve buradan onaylanır."
          testId="approvals-empty"
        />
      )}
      {items && items.length > 0 && (
        <div className="p-6 space-y-3">
          {items.map((a) => (
            <div key={a.id} className="glass-soft rounded-lg p-4" data-testid={`approval-${a.id}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-mono uppercase tracking-widest text-muted">{a.tool}</p>
                  <p className="text-sm text-white mt-1">{a.reason || "Sebep belirtilmedi."}</p>
                  <pre className="text-[11px] mt-2 font-mono text-secondary bg-black/30 rounded p-2 overflow-x-auto">
{JSON.stringify(a.arguments, null, 2)}
                  </pre>
                </div>
                <div className="flex flex-col gap-2 shrink-0">
                  <Btn kind="primary" onClick={() => decide(a.id, "approve")} data-testid={`approve-${a.id}`}>
                    <Check size={12} className="inline mr-1" /> Onayla
                  </Btn>
                  <Btn kind="danger" onClick={() => decide(a.id, "reject")} data-testid={`reject-${a.id}`}>
                    <XIcon size={12} className="inline mr-1" /> Reddet
                  </Btn>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </PanelShell>
  );
}
