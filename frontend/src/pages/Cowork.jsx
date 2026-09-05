// Cowork — macOS-style desktop: white glass window with Safari-like tabs, Dock, genie minimize.
import React, { useEffect, useRef, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { motion, AnimatePresence, useAnimate } from "framer-motion";
import { X, Minus, Maximize2, Plus } from "lucide-react";
import Dock from "@/components/Dock";
import { PANELS, DEFAULT_TABS } from "@/lib/panels";
import { useOrb } from "@/state/orb";
import { api } from "@/lib/api";

const APPLE = [0.32, 0.72, 0, 1];

export default function Cowork() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("panel");
  const { setOrb } = useOrb();

  const [tabs, setTabs] = useState(() =>
    requested && PANELS[requested] && !DEFAULT_TABS.includes(requested) ? [...DEFAULT_TABS, requested] : DEFAULT_TABS
  );
  const [active, setActive] = useState(requested && PANELS[requested] ? requested : DEFAULT_TABS[0]);
  const [open, setOpen] = useState(true);
  const [minimized, setMinimized] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [scope, animate] = useAnimate();
  const dockRef = useRef(null);
  const animating = useRef(false);

  useEffect(() => { setOrb("idle", { label: "Cowork" }); }, [setOrb]);

  const openTab = useCallback((key) => {
    setTabs((prev) => (prev.includes(key) ? prev : [...prev, key]));
    setActive(key);
    setOpen(true);
    setParams({ panel: key }, { replace: true });
  }, [setParams]);

  useEffect(() => {
    let mounted = true;
    const poll = async () => {
      try {
        const r = await api.pollUIActions();
        if (!mounted) return;
        for (const a of r.actions || []) if (PANELS[a.panel]) openTab(a.panel);
      } catch { /* silent */ }
    };
    const t = setInterval(poll, 5000);
    poll();
    return () => { mounted = false; clearInterval(t); };
  }, [openTab]);

  const closeTab = (key) => {
    const next = tabs.filter((k) => k !== key);
    if (next.length === 0) { setOpen(false); return; }
    setTabs(next);
    if (active === key) setActive(next[0]);
  };

  const genieTarget = () => {
    const win = scope.current?.getBoundingClientRect();
    const icon = dockRef.current?.iconRect(active);
    if (!win || !icon) return { dx: 0, dy: 400 };
    return {
      dx: icon.left + icon.width / 2 - (win.left + win.width / 2),
      dy: icon.top + icon.height / 2 - (win.top + win.height / 2),
    };
  };

  const minimize = async () => {
    if (animating.current) return;
    animating.current = true;
    const { dx, dy } = genieTarget();
    await animate(
      scope.current,
      { x: [0, dx * 0.35, dx], y: [0, dy * 0.45, dy], scaleX: [1, 0.55, 0.05], scaleY: [1, 0.92, 0.04], opacity: [1, 1, 0.25], borderRadius: ["14px", "28px", "60px"] },
      { duration: 0.62, ease: APPLE, times: [0, 0.5, 1] }
    );
    setMinimized(true);
    animating.current = false;
  };

  const restore = async () => {
    if (animating.current) return;
    animating.current = true;
    setMinimized(false);
    await new Promise((r) => requestAnimationFrame(r));
    const { dx, dy } = genieTarget();
    await animate(
      scope.current,
      { x: [dx, dx * 0.35, 0], y: [dy, dy * 0.45, 0], scaleX: [0.05, 0.55, 1], scaleY: [0.04, 0.92, 1], opacity: [0.25, 1, 1], borderRadius: ["60px", "28px", "14px"] },
      { duration: 0.58, ease: APPLE, times: [0, 0.5, 1] }
    );
    animating.current = false;
  };

  const onDockClick = (key) => {
    if (!open) { openTab(key); return; }
    if (minimized) { if (tabs.includes(key)) setActive(key); else openTab(key); restore(); return; }
    openTab(key);
  };

  const ActivePanel = PANELS[active]?.comp;

  return (
    <main className="relative h-full w-full pt-14 overflow-hidden" data-testid="cowork-page">
      <AnimatePresence>
        {open && (
          <motion.div
            key="win"
            ref={scope}
            initial={{ opacity: 0, scale: 0.94, y: 18 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.94, y: 12, transition: { duration: 0.28, ease: APPLE } }}
            transition={{ duration: 0.5, ease: APPLE }}
            style={{ display: minimized ? "none" : "flex", borderRadius: 14 }}
            className={`mac-window absolute flex-col overflow-hidden transition-[inset] duration-500 ${
              maximized ? "inset-x-3 top-[64px] bottom-[96px]" : "inset-x-6 md:inset-x-16 top-[84px] bottom-[120px]"
            }`}
            data-testid="cowork-window"
          >
            <div className="mac-titlebar h-11 shrink-0 flex items-center px-3.5 gap-3 select-none">
              <div className="traffic-group flex items-center gap-2">
                <button aria-label="Kapat" onClick={() => setOpen(false)} className="traffic traffic-close" data-testid="tl-close">
                  <X size={8} strokeWidth={3} color="#4d0000" />
                </button>
                <button aria-label="Simge durumuna küçült" onClick={minimize} className="traffic traffic-min" data-testid="tl-min">
                  <Minus size={8} strokeWidth={3} color="#995700" />
                </button>
                <button aria-label="Tam ekran" onClick={() => setMaximized((v) => !v)} className="traffic traffic-max" data-testid="tl-max">
                  <Maximize2 size={7} strokeWidth={3} color="#006500" />
                </button>
              </div>

              <div className="flex-1 flex items-center gap-1.5 overflow-x-auto no-scrollbar">
                {tabs.map((k) => {
                  const P = PANELS[k];
                  const Icon = P.icon;
                  const isActive = k === active;
                  return (
                    <div
                      key={k}
                      onClick={() => setActive(k)}
                      className={`mac-tab group cursor-pointer flex items-center gap-2 pl-3 pr-2 h-7 rounded-lg text-[12px] font-medium whitespace-nowrap ${isActive ? "active" : ""}`}
                      data-testid={`cowork-tab-${k}`}
                    >
                      <Icon size={12} style={{ color: P.color }} />
                      <span>{P.title}</span>
                      <button
                        onClick={(e) => { e.stopPropagation(); closeTab(k); }}
                        className="ml-1 w-4 h-4 rounded flex items-center justify-center opacity-0 group-hover:opacity-100 hover:bg-black/10 text-[#5c6370]"
                        aria-label="Sekmeyi kapat"
                        data-testid={`cowork-tab-close-${k}`}
                      >
                        <X size={10} />
                      </button>
                    </div>
                  );
                })}
                <button
                  onClick={() => setPickerOpen((v) => !v)}
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-[#5c6370] hover:bg-black/5"
                  data-testid="cowork-add-tab"
                  aria-label="Sekme ekle"
                >
                  <Plus size={13} />
                </button>
              </div>

              <div className="hidden md:block text-[11px] font-mono text-[#8b919d]">jarvis://{active}</div>
            </div>

            {pickerOpen && (
              <div className="relative light-surface">
                <div
                  className="absolute right-3 top-2 bg-white rounded-xl py-1.5 w-60 z-20 shadow-[0_12px_40px_-8px_rgba(0,0,0,0.3)] border border-black/5"
                  data-testid="cowork-picker"
                  onMouseLeave={() => setPickerOpen(false)}
                >
                  {Object.entries(PANELS).map(([k, P]) => {
                    const Icon = P.icon;
                    return (
                      <button
                        key={k}
                        onClick={() => { openTab(k); setPickerOpen(false); }}
                        className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] hover:bg-black/5 text-[#1d1d1f]"
                        data-testid={`cowork-picker-${k}`}
                      >
                        <span className="w-5 h-5 rounded-md flex items-center justify-center" style={{ background: P.color }}>
                          <Icon size={11} color="#fff" />
                        </span>
                        {P.title}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="flex-1 overflow-hidden light-surface">
              {ActivePanel && <ActivePanel />}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {!open && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none" data-testid="cowork-closed">
          <p className="text-sm text-muted">Dock'tan bir uygulama açın</p>
        </div>
      )}

      <Dock
        ref={dockRef}
        openKeys={open ? tabs : []}
        active={open && !minimized ? active : null}
        minimized={open && minimized}
        onClick={onDockClick}
      />
    </main>
  );
}
