// Persistent bottom-right mini orb — tap to talk (dispatches jarvis:talk; navigates to chat if elsewhere).
import React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useOrb, STATE_COLORS } from "@/state/orb";
import Orb from "@/components/Orb";

export default function MiniOrb() {
  const { state, meta } = useOrb();
  const { pathname } = useLocation();
  const nav = useNavigate();
  const c = STATE_COLORS[state] || STATE_COLORS.idle;

  const talk = () => {
    if (pathname === "/chat") window.dispatchEvent(new Event("jarvis:talk"));
    else if (pathname === "/") document.querySelector("[data-testid='home-orb']")?.click();
    else { sessionStorage.setItem("jarvis.autoTalk", "1"); nav("/chat"); }
  };

  return (
    <button
      className="fixed bottom-5 right-5 z-40 flex items-center gap-3 pl-1 pr-4 py-1 rounded-full glass text-left hover:bg-white/10 transition"
      data-testid="mini-orb"
      onClick={talk}
      aria-label="Jarvis ile konuş"
    >
      <Orb size={54} state={state} testId="mini-orb-canvas" />
      <div className="flex flex-col leading-tight">
        <span className="text-[10px] uppercase tracking-[0.2em] text-muted font-mono">J.A.R.V.I.S</span>
        <span className="text-xs" style={{ color: c.core }}>{meta.label || c.label}</span>
      </div>
    </button>
  );
}
