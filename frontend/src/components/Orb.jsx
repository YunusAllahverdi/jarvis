// 3D liquid-glass orb — volumetric shading, pastel aurora inside, soft wobble. Safari-safe (no ctx.filter).
import React, { useEffect, useRef } from "react";
import { STATE_COLORS } from "@/state/orb";

const AURORA = ["#7fb0ff", "#c9a8ff", "#8ff0d6", "#ffb6e1", "#7ee8ff"];

function blobPath(ctx, cx, cy, R, t, amp) {
  const N = 120;
  ctx.beginPath();
  for (let i = 0; i <= N; i++) {
    const a = (i / N) * Math.PI * 2;
    const w = 1 + amp * (Math.sin(a * 3 + t * 0.8) * 0.55 + Math.sin(a * 5 - t * 1.25) * 0.3 + Math.sin(a * 2 + t * 0.45) * 0.45);
    const x = cx + Math.cos(a) * R * w;
    const y = cy + Math.sin(a) * R * w;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.closePath();
}

export default function Orb({ size = 320, state = "idle", className = "", testId = "orb", onClick, interactive = false }) {
  const canvasRef = useRef(null);
  const raf = useRef(0);
  const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    c.width = size * dpr;
    c.height = size * dpr;
    const ctx = c.getContext("2d");
    ctx.scale(dpr, dpr);

    let t = 0;
    const colors = STATE_COLORS[state] || STATE_COLORS.idle;
    const speed = state === "streaming" ? 0.045 : state === "thinking" ? 0.032 : state === "listening" ? 0.03 : 0.014;
    const amp = state === "thinking" ? 0.035 : state === "streaming" ? 0.045 : state === "listening" ? 0.04 : 0.022;
    const blobs = AURORA.map((col, i) => ({ col, fx: 0.6 + i * 0.17, fy: 0.45 + i * 0.13, px: i * 1.7, py: i * 0.9, r: 0.5 + (i % 3) * 0.12 }));

    const draw = () => {
      const w = size, cx = w / 2, cy = w / 2 - w * 0.02, R = w * 0.34;
      const lx = cx - R * 0.34, ly = cy - R * 0.42; // light position (kept inside the sphere)
      ctx.clearRect(0, 0, w, w);

      // Floor shadow / glow beneath (makes it float)
      ctx.save();
      ctx.translate(cx, cy + R * 1.28);
      ctx.scale(1, 0.28);
      const sh = ctx.createRadialGradient(0, 0, 0, 0, 0, R * 1.1);
      sh.addColorStop(0, colors.core + "55");
      sh.addColorStop(0.5, colors.core + "1a");
      sh.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = sh;
      ctx.fillRect(-R * 1.5, -R * 1.5, R * 3, R * 3);
      ctx.restore();

      // Outer bloom
      const bloom = ctx.createRadialGradient(cx, cy, R * 0.85, cx, cy, R * 1.6);
      bloom.addColorStop(0, colors.core + "2e");
      bloom.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = bloom;
      ctx.fillRect(0, 0, w, w);

      ctx.save();
      blobPath(ctx, cx, cy, R, t, amp);
      ctx.clip();

      // Base sphere shading: lit near light, deep at far side
      const base = ctx.createRadialGradient(lx, ly, R * 0.05, cx + R * 0.15, cy + R * 0.2, R * 1.25);
      base.addColorStop(0, "rgba(96,126,215,0.95)");
      base.addColorStop(0.35, "rgba(52,70,150,0.95)");
      base.addColorStop(0.75, "rgba(20,28,74,0.98)");
      base.addColorStop(1, "rgba(8,12,36,1)");
      ctx.fillStyle = base;
      ctx.fillRect(0, 0, w, w);

      // Aurora flowing inside (additive)
      ctx.globalCompositeOperation = "lighter";
      blobs.forEach((b, i) => {
        const bx = cx + Math.sin(t * b.fx + b.px) * R * 0.5;
        const by = cy + Math.cos(t * b.fy + b.py) * R * 0.5;
        const br = R * b.r * (1 + Math.sin(t * 0.7 + i) * 0.12);
        const g = ctx.createRadialGradient(bx, by, 0, bx, by, br);
        g.addColorStop(0, b.col + "8c");
        g.addColorStop(0.5, b.col + "30");
        g.addColorStop(1, b.col + "00");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, w);
      });
      const pulse = 0.5 + Math.sin(t * 1.6) * 0.5;
      const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * (0.45 + pulse * 0.15));
      core.addColorStop(0, colors.core + (state === "idle" ? "50" : "90"));
      core.addColorStop(1, colors.core + "00");
      ctx.fillStyle = core;
      ctx.fillRect(0, 0, w, w);
      ctx.globalCompositeOperation = "source-over";

      // Fresnel back-light on the far rim (soft, colored)
      const fres = ctx.createRadialGradient(cx + R * 0.35, cy + R * 0.45, R * 0.55, cx + R * 0.35, cy + R * 0.45, R * 1.25);
      fres.addColorStop(0, "rgba(255,255,255,0)");
      fres.addColorStop(0.72, "rgba(255,255,255,0)");
      fres.addColorStop(0.9, colors.core + "66");
      fres.addColorStop(1, colors.core + "aa");
      ctx.fillStyle = fres;
      ctx.fillRect(0, 0, w, w);

      // Broad soft highlight
      const soft = ctx.createRadialGradient(lx, ly, 0, lx, ly, R * 0.7);
      soft.addColorStop(0, "rgba(255,255,255,0.22)");
      soft.addColorStop(0.5, "rgba(255,255,255,0.06)");
      soft.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = soft;
      ctx.fillRect(0, 0, w, w);

      // Limb darkening — the key 3D cue
      const limb = ctx.createRadialGradient(cx - R * 0.1, cy - R * 0.1, R * 0.55, cx, cy, R * 1.02);
      limb.addColorStop(0, "rgba(6,10,30,0)");
      limb.addColorStop(0.75, "rgba(6,10,30,0.18)");
      limb.addColorStop(1, "rgba(6,10,30,0.8)");
      ctx.fillStyle = limb;
      ctx.fillRect(0, 0, w, w);

      // Sharp specular (elongated)
      ctx.save();
      ctx.translate(lx + R * 0.05, ly - R * 0.02);
      ctx.rotate(-0.6);
      ctx.scale(1.7, 0.75);
      const spec = ctx.createRadialGradient(0, 0, 0, 0, 0, R * 0.2);
      spec.addColorStop(0, "rgba(255,255,255,0.85)");
      spec.addColorStop(0.35, "rgba(255,255,255,0.45)");
      spec.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = spec;
      ctx.fillRect(-R, -R, R * 2, R * 2);
      ctx.restore();

      // Tiny secondary glint bottom-right (reflection of environment)
      const g2 = ctx.createRadialGradient(cx + R * 0.48, cy + R * 0.5, 0, cx + R * 0.48, cy + R * 0.5, R * 0.16);
      g2.addColorStop(0, "rgba(255,255,255,0.45)");
      g2.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = g2;
      ctx.fillRect(0, 0, w, w);
      ctx.restore();

      t += reduce ? 0 : speed;
      raf.current = requestAnimationFrame(draw);
    };
    raf.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf.current);
  }, [size, state, reduce]);

  return (
    <div
      className={`relative ${interactive ? "orb-interactive" : ""} ${className}`}
      data-testid={testId}
      data-state={state}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      aria-label={onClick ? "Jarvis ile konuş" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => (e.key === "Enter" || e.key === " ") && onClick(e) : undefined}
    >
      <canvas ref={canvasRef} style={{ width: size, height: size }} className={reduce ? "" : "orb-breath"} aria-hidden="true" />
    </div>
  );
}
