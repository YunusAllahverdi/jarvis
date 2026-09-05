import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, Empty, ErrorNote, LoadingBlock, Btn, Input } from "./_shell";
import { Search } from "lucide-react";

/**
 * Süzgeç türleri backend'in GERÇEK `MemoryType` kümesidir.
 *
 * Emergent şablonu "episodic / semantic / experience" yazıyordu; bunlar
 * yaygın bellek terimleri ama BU sistemde böyle bir tür yok. Bırakılsaydı
 * üç sekme de her zaman boş çıkardı ve kullanıcı belleğin bozuk olduğunu
 * sanırdı — oysa yalnızca var olmayan bir etikete göre süzüyordu.
 */
const KINDS = [
  { key: "", label: "Hepsi" },
  { key: "fact", label: "Bilgi" },
  { key: "event", label: "Olay" },
  { key: "preference", label: "Tercih" },
  { key: "goal", label: "Hedef" },
  { key: "world_state", label: "Durum" },
  { key: "other", label: "Diğer" },
];

export default function MemoryPanel() {
  const [items, setItems] = useState(null);
  const [err, setErr] = useState(null);
  const [q, setQ] = useState("");
  const qRef = useRef("");
  qRef.current = q;
  const [kind, setKind] = useState("");

  // `q` bilerek bağımlılık DEĞİL: her harfte yeniden sorgu atılırdı.
  // Arama Enter ya da düğmeyle tetiklenir; tür değişimi anında yeniler.
  const refresh = useCallback(
    () => api.listMemory(kind || undefined, qRef.current || undefined).then((r) => setItems(r.items || [])).catch(setErr),
    [kind],
  );
  useEffect(() => { refresh(); }, [refresh]);

  return (
    <PanelShell
      title="Bellek Tarayıcısı"
      subtitle="Episodic (olay), semantic (bilgi), experience (deneyim). Bellek Jarvis'in çıkardığı bilgidir; notlardan ayrıdır."
      testId="memory-panel"
      command="memory"
      onCommandDone={refresh}
    >
      {err && <ErrorNote err={err} testId="memory-error" />}
      <div className="px-6 pt-4 flex flex-wrap items-center gap-2">
        {KINDS.map((k) => (
          <button
            key={k.key}
            onClick={() => setKind(k.key)}
            className={`pill ${kind === k.key ? "text-white !border-[rgba(47,111,237,0.5)] !bg-[rgba(47,111,237,0.08)]" : ""}`}
            data-testid={`memory-kind-${k.key || "all"}`}
          >
            {k.label}
          </button>
        ))}
        <div className="flex-1 min-w-[160px] flex items-center gap-2">
          <Search size={14} className="text-muted" />
          <Input
            placeholder="Metin ara…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && refresh()}
            data-testid="memory-search"
          />
          <Btn onClick={refresh}>ara</Btn>
        </div>
      </div>

      {items === null && <LoadingBlock />}
      {items && items.length === 0 && (
        <Empty label="Bellek boş." hint="Jarvis sohbet sırasında çıkardığı bilgileri buraya kaydeder." testId="memory-empty" />
      )}
      {items && items.length > 0 && (
        <ul className="p-6 space-y-2">
          {items.map((m) => (
            <li key={m.id} className="glass-soft rounded-lg p-3" data-testid={`memory-item-${m.id}`}>
              <div className="flex items-center gap-2 text-xs text-muted">
                <span className="pill">{KINDS.find((k) => k.key === m.kind)?.label || m.kind}</span>
                <span className="font-mono">{new Date(m.ts).toLocaleString("tr-TR")}</span>
              </div>
              <p className="text-sm text-white mt-1 whitespace-pre-wrap">{m.text}</p>
            </li>
          ))}
        </ul>
      )}
    </PanelShell>
  );
}
