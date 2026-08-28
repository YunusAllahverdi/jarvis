import { useMemo } from 'react';
import { useTheme } from '../../contexts/ThemeContext';
import { motion } from 'framer-motion';

export const AmbientBackground = () => {
  const { currentTheme } = useTheme();

  // Very sparse, very small, very dim particles
  const particles = useMemo(() =>
    Array.from({ length: 18 }).map((_, i) => ({
      id: i,
      size: Math.random() * 2.0 + 0.5,           // 0.5 – 2.5 px
      x: Math.random() * 100,
      y: Math.random() * 100,
      duration: Math.random() * 40 + 25,           // 25 – 65 s (very slow)
      delay: Math.random() * 15,
      maxOpacity: Math.random() * 0.25 + 0.05,     // 0.05 – 0.30
    })),
  [currentTheme.backgroundType]);

  return (
    <div style={{
      position: 'fixed', inset: 0,
      zIndex: 0,
      background: 'var(--bg-color)',
      overflow: 'hidden',
    }}>
      {/* ── Nebula glow 1 — upper-left, very dim ── */}
      <motion.div
        animate={{ scale: [1, 1.06, 1], opacity: [0.12, 0.20, 0.12] }}
        transition={{ duration: 25, repeat: Infinity, ease: 'easeInOut' }}
        style={{
          position: 'absolute',
          top: '5%', left: '10%',
          width: '55vw', height: '55vw',
          background: `radial-gradient(circle, ${currentTheme.orb.glowColor}22 0%, transparent 65%)`,
          filter: 'blur(100px)',
          transform: 'translate(-30%, -30%)',
        }}
      />

      {/* ── Nebula glow 2 — lower-right, barely visible ── */}
      <motion.div
        animate={{ scale: [1, 1.08, 1], opacity: [0.08, 0.15, 0.08] }}
        transition={{ duration: 35, repeat: Infinity, ease: 'easeInOut', delay: 5 }}
        style={{
          position: 'absolute',
          top: '55%', left: '65%',
          width: '50vw', height: '50vw',
          background: `radial-gradient(circle, ${currentTheme.orb.coreColor}18 0%, transparent 65%)`,
          filter: 'blur(120px)',
          transform: 'translate(-30%, -20%)',
        }}
      />

      {/* ── Nebula glow 3 — center, very faint to ground the orb ── */}
      <motion.div
        animate={{ opacity: [0.06, 0.12, 0.06] }}
        transition={{ duration: 20, repeat: Infinity, ease: 'easeInOut', delay: 8 }}
        style={{
          position: 'absolute',
          top: '35%', left: '50%',
          width: '40vw', height: '40vw',
          background: `radial-gradient(circle, ${currentTheme.orb.accentColor}12 0%, transparent 60%)`,
          filter: 'blur(100px)',
          transform: 'translate(-50%, -40%)',
        }}
      />

      {/* ── Horizon / ground surface hint ── */}
      <div style={{
        position: 'absolute',
        bottom: 0, left: 0, right: 0,
        height: '30vh',
        background: `linear-gradient(to top,
          ${currentTheme.orb.glowColor}06 0%,
          transparent 100%)`,
        pointerEvents: 'none',
      }} />

      {/* ── Sparse floating particles ── */}
      {particles.map((p) => (
        <motion.div
          key={p.id}
          animate={{
            y: [`${p.y}vh`, `${p.y - 12}vh`],
            x: [`${p.x}vw`, `${p.x + (Math.random() * 4 - 2)}vw`],
            opacity: [0, p.maxOpacity, 0],
          }}
          transition={{
            duration: p.duration,
            repeat: Infinity,
            delay: p.delay,
            ease: 'linear',
          }}
          style={{
            position: 'absolute',
            width: p.size,
            height: p.size,
            borderRadius: '50%',
            backgroundColor: currentTheme.orb.glowColor,
            boxShadow: `0 0 ${p.size * 3}px ${currentTheme.orb.glowColor}40`,
          }}
        />
      ))}

      {/* ── Vignette ── */}
      <div style={{
        position: 'absolute', inset: 0,
        background: 'radial-gradient(ellipse at 50% 45%, transparent 40%, rgba(0,0,0,0.4) 100%)',
        pointerEvents: 'none',
      }} />
    </div>
  );
};
