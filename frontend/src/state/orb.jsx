// Global orb state via React context — used by the persistent mini orb and pages.
import React, { createContext, useContext, useMemo, useState, useCallback } from "react";

const OrbCtx = createContext(null);

export function OrbProvider({ children }) {
  const [state, setState] = useState("idle"); // idle|listening|thinking|streaming|error|muted
  const [meta, setMeta] = useState({ label: "hazır", detail: "" });
  const setOrb = useCallback((s, m = {}) => {
    setState(s);
    setMeta((prev) => ({ ...prev, ...m }));
  }, []);
  const value = useMemo(() => ({ state, meta, setOrb }), [state, meta, setOrb]);
  return <OrbCtx.Provider value={value}>{children}</OrbCtx.Provider>;
}

export function useOrb() {
  const ctx = useContext(OrbCtx);
  if (!ctx) throw new Error("useOrb must be used inside OrbProvider");
  return ctx;
}

export const STATE_COLORS = {
  idle:      { core: "#8AB4FF", glow: "#8AB4FF66", label: "Bekleniyor" },
  listening: { core: "#8FE3FF", glow: "#8FE3FF88", label: "Dinliyor" },
  thinking:  { core: "#C3A6FF", glow: "#C3A6FF88", label: "Düşünüyor" },
  streaming: { core: "#8FE0C0", glow: "#8FE0C088", label: "Aktarıyor" },
  error:     { core: "#FF9A9A", glow: "#FF9A9A88", label: "Hata" },
  muted:     { core: "#9AA3B5", glow: "#9AA3B555", label: "Sessiz" },
};
