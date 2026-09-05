// Top navigation bar — subtle spatial header for J.A.R.V.I.S OS
import React, { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { api } from "@/lib/api";
import { Command } from "lucide-react";

const NAV = [
  { to: "/",       label: "Ana Ekran", testId: "nav-home" },
  { to: "/chat",   label: "Sohbet",    testId: "nav-chat" },
  { to: "/cowork", label: "Cowork",    testId: "nav-cowork" },
];

export default function TopBar() {
  const { pathname } = useLocation();
  const [health, setHealth] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.health().then((h) => !cancelled && setHealth(h)).catch(() => {});
    const t = setInterval(() => {
      api.health().then((h) => !cancelled && setHealth(h)).catch(() => {});
    }, 30000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  return (
    <header
      className="fixed top-0 left-0 right-0 z-30 h-14 flex items-center justify-between px-6 border-b hairline glass-soft"
      data-testid="top-bar"
    >
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: "var(--electric)", boxShadow: "0 0 10px rgba(138,180,255,0.6)" }} />
          <span className="font-display text-sm tracking-[0.28em] font-medium">J.A.R.V.I.S</span>
          <span className="text-[10px] font-mono text-muted ml-1">v0.2</span>
        </div>
        <nav className="hidden md:flex items-center gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              data-testid={n.testId}
              className={({ isActive }) =>
                `px-3 py-1.5 rounded-md text-xs tracking-wide transition ${
                  isActive || pathname === n.to
                    ? "text-white bg-white/5 border border-white/10"
                    : "text-secondary hover:text-white hover:bg-white/5"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <div className="flex items-center gap-3">
        {health && (
          <span className="pill font-mono" data-testid="provider-pill">
            {health.provider} · {health.model}
          </span>
        )}
        <span
          className="pill flex items-center gap-1.5"
          data-testid="health-pill"
          style={{ borderColor: health?.status === "ok" ? "rgba(143,224,192,0.45)" : "rgba(255,154,154,0.45)" }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: health?.status === "ok" ? "#8FE0C0" : "#FF9A9A" }}
          />
          {health?.status === "ok" ? "çevrimiçi" : "çevrimdışı"}
        </span>
        <button
          className="pill flex items-center gap-1.5 hover:text-white"
          onClick={() => {
            window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }));
          }}
          data-testid="open-palette"
        >
          <Command size={12} /> K
        </button>
      </div>
    </header>
  );
}
