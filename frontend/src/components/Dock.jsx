// macOS-style Dock — glass pill with magnifying app icons and running indicators.
import React, { forwardRef, useImperativeHandle, useRef } from "react";
import { PANELS } from "@/lib/panels";

const Dock = forwardRef(function Dock({ openKeys, active, minimized, onClick }, ref) {
  const refs = useRef({});
  useImperativeHandle(ref, () => ({
    iconRect: (key) => refs.current[key]?.getBoundingClientRect(),
  }));

  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20" data-testid="dock">
      <div className="dock flex items-end gap-1.5 px-2.5 pt-2 pb-1.5 rounded-[22px]">
        {Object.entries(PANELS).map(([k, P]) => {
          const Icon = P.icon;
          const isOpen = openKeys.includes(k);
          return (
            <button
              key={k}
              ref={(el) => (refs.current[k] = el)}
              onClick={() => onClick(k)}
              className="dock-icon relative flex flex-col items-center"
              aria-label={P.title}
              data-testid={`dock-${k}`}
            >
              <span className="dock-tip absolute -top-9 px-2.5 py-1 rounded-md text-[11px] text-white bg-black/60 backdrop-blur whitespace-nowrap pointer-events-none">
                {P.title}
              </span>
              <span
                className="w-10 h-10 md:w-11 md:h-11 rounded-[12px] flex items-center justify-center shadow-[inset_0_1px_0_rgba(255,255,255,0.35),0_6px_14px_-6px_rgba(0,0,0,0.6)]"
                style={{ background: `linear-gradient(180deg, ${P.color}ee, ${P.color}aa)` }}
              >
                <Icon size={20} color="#fff" strokeWidth={2} />
              </span>
              <span
                className={`mt-1 w-1 h-1 rounded-full transition-opacity ${isOpen ? "opacity-100" : "opacity-0"} ${
                  active === k ? "bg-white" : minimized || isOpen ? "bg-white/60" : ""
                }`}
              />
            </button>
          );
        })}
      </div>
    </div>
  );
});

export default Dock;
