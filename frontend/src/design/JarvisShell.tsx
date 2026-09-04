/**
 * Jarvis Shell — yeni tasarım
 *
 * Felsefe:
 * - Başlangıçta boş ekran: sadece hafif arka plan ışığı, altta yazı kutusu
 * - Mesaj gelince sohbet listesi yukarı doğru açılır (slide-up)
 * - Orb sağ altta, her zaman canlı, küçük ama var
 * - Sol menü yok — Jarvis'e söyleyince panel açılır
 * - Hover → parlar, tıklamaya gerek yok
 * - Markdown render
 * - Cowork modu ayrı sayfa
 * - iPhone 16 Pro Max + iPad Pro 12.9 responsive
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { OrbEngine, type OrbMode } from './orb/OrbEngine';
import { Markdown } from './Markdown';
import { AdminPanel } from './AdminPanel';
import { NotesPanel } from './NotesPanel';
import { InsightPanel, type InsightSection } from './InsightPanel';
import { CodingPanel } from './CodingPanel';
import { CoworkMode } from './CoworkMode';
import { useSpeech } from './useSpeech';
import { useDictation } from './useDictation';
import { apiClient } from '../api/client';

interface Message {
  id: number;
  role: 'user' | 'jarvis';
  text: string;
  ts: number;
}

let msgId = 0;
const nextId = () => ++msgId;

// Arka plan partikülleri — hafif hareketli ışık noktaları
interface Particle { x: number; y: number; vx: number; vy: number; r: number; alpha: number; }

function makeParticles(n: number): Particle[] {
  return Array.from({ length: n }, () => ({
    x: Math.random(),
    y: Math.random(),
    vx: (Math.random() - 0.5) * 0.00012,
    vy: (Math.random() - 0.5) * 0.00012,
    r: 1 + Math.random() * 2,
    alpha: 0.08 + Math.random() * 0.18,
  }));
}

export const JarvisShell = () => {
  // ── refs ───────────────────────────────────────────────────────────────
  const orbRef    = useRef<HTMLCanvasElement>(null);
  const bgRef     = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<OrbEngine | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef  = useRef<HTMLTextAreaElement>(null);
  const rafRef    = useRef<number>(0);
  const particlesRef = useRef<Particle[]>(makeParticles(55));

  // ── state ──────────────────────────────────────────────────────────────
  const [mode, setMode]         = useState<OrbMode>('idle');
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput]       = useState('');
  const [busy, setBusy]         = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false); // sohbet açık mı
  const [micOn, setMicOn]       = useState(false);

  // Paneller
  const [adminOpen, setAdminOpen]   = useState(false);
  const [notesOpen, setNotesOpen]   = useState(false);
  const [codingOpen, setCodingOpen] = useState(false);
  const [insight, setInsight]       = useState<InsightSection | null>(null);
  const [coworkMode, setCoworkMode] = useState(false);

  // Transcript gösterimi (sesli konuşurken arka planda)
  const [liveTranscript, setLiveTranscript] = useState('');

  const speech = useSpeech();

  // Dictation: transcript input'a yaz, ekranda küçük göster
  const dictation = useDictation(useCallback((text: string) => {
    setInput(text);
    setLiveTranscript(text);
    setTimeout(() => setLiveTranscript(''), 2500);
  }, []));

  // ── arka plan partikülleri ─────────────────────────────────────────────
  useEffect(() => {
    const cv = bgRef.current;
    if (!cv) return;
    const ctx = cv.getContext('2d');
    if (!ctx) return;

    const resize = () => {
      cv.width  = window.innerWidth;
      cv.height = window.innerHeight;
    };
    resize();
    window.addEventListener('resize', resize);

    const draw = () => {
      ctx.clearRect(0, 0, cv.width, cv.height);
      const pts = particlesRef.current;

      // Hafif bağlantı çizgileri
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const dx = (pts[i].x - pts[j].x) * cv.width;
          const dy = (pts[i].y - pts[j].y) * cv.height;
          const d  = Math.sqrt(dx * dx + dy * dy);
          if (d < 110) {
            ctx.beginPath();
            ctx.moveTo(pts[i].x * cv.width, pts[i].y * cv.height);
            ctx.lineTo(pts[j].x * cv.width, pts[j].y * cv.height);
            ctx.strokeStyle = `rgba(100,110,255,${0.04 * (1 - d / 110)})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }

      // Partiküller
      for (const p of pts) {
        ctx.beginPath();
        ctx.arc(p.x * cv.width, p.y * cv.height, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(140,150,255,${p.alpha})`;
        ctx.fill();

        // Hareket
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0) p.x = 1;
        if (p.x > 1) p.x = 0;
        if (p.y < 0) p.y = 1;
        if (p.y > 1) p.y = 0;
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    draw();
    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(rafRef.current);
    };
  }, []);

  // ── orb başlat ─────────────────────────────────────────────────────────
  useEffect(() => {
    const cv = orbRef.current;
    if (!cv) return;
    const eng = new OrbEngine(cv);
    engineRef.current = eng;
    eng.start();
    return () => { eng.destroy(); engineRef.current = null; };
  }, []);

  useEffect(() => { engineRef.current?.setMode(mode); }, [mode]);

  // ── mesaj sonu scroll ──────────────────────────────────────────────────
  useEffect(() => {
    if (chatOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, chatOpen]);

  // ── agent panel açma ───────────────────────────────────────────────────
  const applyAgentPanels = useCallback(async (sid: string | null) => {
    try {
      const { actions } = await apiClient.consumeUiActions(sid);
      const last = actions.at(-1);
      if (!last) return;

      setNotesOpen(false);
      setCodingOpen(false);
      setInsight(null);

      const SECTIONS: Record<string, InsightSection> = {
        memory: 'Bellek', experiences: 'Deneyimler',
        traits: 'Öğrendiklerim', user_model: 'Benim Modelim', system: 'Sistem',
      };

      if (last.panel === 'notes')  { setNotesOpen(true); return; }
      if (last.panel === 'coding') { setCodingOpen(true); return; }
      const sec = SECTIONS[last.panel];
      if (sec) setInsight(sec);
    } catch { /* sohbet etkilenmez */ }
  }, []);

  // ── mesaj gönder ───────────────────────────────────────────────────────
  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;

    setInput('');
    setBusy(true);
    setChatOpen(true);
    setMode('listening');

    const userMsg: Message = { id: nextId(), role: 'user', text, ts: Date.now() };
    setMessages(prev => [...prev, userMsg]);

    try {
      const res = await apiClient.chat(text, sessionId);
      if (res.session_id) setSessionId(res.session_id);

      const jarvisMsg: Message = { id: nextId(), role: 'jarvis', text: res.response, ts: Date.now() };
      setMessages(prev => [...prev, jarvisMsg]);

      setMode('speaking');
      speech.speak(res.response);
      void applyAgentPanels(res.session_id ?? sessionId);

      const dwell = Math.min(Math.max(res.response.length * 35, 2000), 6000);
      setTimeout(() => { setMode('idle'); }, dwell);
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'Hata oluştu';
      setMessages(prev => [...prev, {
        id: nextId(), role: 'jarvis',
        text: `Bağlantı kurulamadı: ${detail}`,
        ts: Date.now(),
      }]);
      setMode('idle');
    } finally {
      setBusy(false);
    }
  }, [input, busy, sessionId, speech, applyAgentPanels]);

  const toggleMic = useCallback(async () => {
    const eng = engineRef.current;
    if (!eng) return;
    const ok = await eng.enableMic();
    setMicOn(ok);
  }, []);

  // Cowork moduna geç
  if (coworkMode) {
    return <CoworkMode onExit={() => setCoworkMode(false)} />;
  }

  const hasMessages = messages.length > 0;

  return (
    <div style={{
      position: 'fixed', inset: 0,
      background: '#06050f',
      overflow: 'hidden',
      fontFamily: 'Sora, Helvetica, sans-serif',
      color: '#e0e4ff',
    }}>
      {/* ── arka plan: hareketli partiküller ── */}
      <canvas
        ref={bgRef}
        style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0 }}
      />

      {/* ── üst bar ── */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0,
        height: 56, zIndex: 10,
        display: 'flex', alignItems: 'center', padding: '0 20px',
        gap: 12,
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: '#8878ff',
            boxShadow: '0 0 10px 3px rgba(136,120,255,0.6)',
          }} />
          <span style={{ fontSize: 11, letterSpacing: '0.4em', color: '#9ba4d4', fontWeight: 500 }}>
            JARVIS
          </span>
        </div>

        <div style={{ flex: 1 }} />

        {/* Cowork butonu */}
        <TopButton
          title="Cowork Modu"
          onClick={() => setCoworkMode(true)}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <rect x="3" y="3" width="8" height="8" rx="2" />
            <rect x="13" y="3" width="8" height="8" rx="2" />
            <rect x="3" y="13" width="8" height="8" rx="2" />
            <rect x="13" y="13" width="8" height="8" rx="2" />
          </svg>
        </TopButton>

        {/* Sesli cevap */}
        {speech.supported && (
          <TopButton
            title={speech.enabled ? 'Sesi kapat' : 'Sesi aç'}
            active={speech.enabled}
            onClick={() => { if (speech.toggle()) speech.speak('Sesli cevap açık.'); }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M4 9.5h3L12 5.5v13l-5-4H4z" />
              {speech.enabled
                ? <path d="M15 9a4 4 0 010 6M18 6a8 8 0 010 12" />
                : <path d="M16 9l4 6M20 9l-4 6" />
              }
            </svg>
          </TopButton>
        )}

        {/* Ayarlar */}
        <TopButton title="Ayarlar" onClick={() => setAdminOpen(true)}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 2v2M12 20v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M2 12h2M20 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
          </svg>
        </TopButton>

        {/* Sohbet geçmişi toggle */}
        {hasMessages && (
          <TopButton
            title={chatOpen ? 'Sohbeti gizle' : 'Sohbeti göster'}
            active={chatOpen}
            onClick={() => setChatOpen(v => !v)}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M4.5 6.5a2.5 2.5 0 012.5-2.5h10a2.5 2.5 0 012.5 2.5v6a2.5 2.5 0 01-2.5 2.5H9l-4.5 3.5z" />
            </svg>
          </TopButton>
        )}
      </div>

      {/* ── orta alan: karşılama veya sohbet ── */}
      <div style={{
        position: 'absolute',
        top: 56,
        bottom: 110,
        left: 0, right: 0,
        zIndex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: chatOpen ? 'flex-end' : 'center',
        overflow: 'hidden',
      }}>

        {/* Karşılama metni — sohbet yoksa veya kapalıysa */}
        {!chatOpen && (
          <div style={{
            textAlign: 'center',
            animation: 'fadeIn 0.6s ease',
            padding: '0 24px',
          }}>
            <div style={{
              fontSize: 'clamp(22px, 4vw, 38px)',
              fontWeight: 200,
              color: 'rgba(220,225,255,0.82)',
              letterSpacing: '0.01em',
              marginBottom: 12,
              textShadow: '0 0 40px rgba(120,110,255,0.35)',
            }}>
              {hasMessages
                ? messages[messages.length - 1].role === 'jarvis'
                  ? messages[messages.length - 1].text.slice(0, 80) + (messages[messages.length - 1].text.length > 80 ? '…' : '')
                  : 'Düşünüyorum…'
                : 'Nasıl yardımcı olabilirim?'
              }
            </div>
            {!hasMessages && (
              <div style={{ fontSize: 13, color: '#4a4f70', marginTop: 8 }}>
                Yazmaya başla veya mikrofona bas
              </div>
            )}
          </div>
        )}

        {/* Sohbet listesi — açıkken göster */}
        {chatOpen && (
          <div style={{
            width: '100%', maxWidth: 720,
            flex: 1, overflowY: 'auto',
            padding: '16px 20px 0',
            display: 'flex', flexDirection: 'column', gap: 12,
            animation: 'slideUp 0.3s ease',
          }}>
            {messages.map(m => (
              <MessageBubble key={m.id} msg={m} />
            ))}
            {busy && <TypingIndicator />}
            <div ref={messagesEndRef} style={{ height: 8 }} />
          </div>
        )}
      </div>

      {/* ── live transcript gösterimi (sesli konuşurken) ── */}
      {liveTranscript && (
        <div style={{
          position: 'absolute', bottom: 120, left: '50%', transform: 'translateX(-50%)',
          zIndex: 20, background: 'rgba(20,18,40,0.85)',
          border: '1px solid rgba(140,150,255,0.2)',
          borderRadius: 10, padding: '6px 14px',
          fontSize: 12, color: '#9ba4d4',
          backdropFilter: 'blur(10px)',
          maxWidth: '60%', textAlign: 'center',
          animation: 'fadeIn 0.2s ease',
        }}>
          🎙 {liveTranscript}
        </div>
      )}

      {/* ── alt: yazı girişi ── */}
      <div style={{
        position: 'absolute', bottom: 0, left: 0, right: 0,
        height: 100, zIndex: 10,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '0 20px 16px',
      }}>
        <div style={{
          width: '100%', maxWidth: 680,
          display: 'flex', alignItems: 'flex-end', gap: 10,
          background: 'rgba(255,255,255,0.04)',
          border: '1px solid rgba(140,150,255,0.18)',
          borderRadius: 18,
          padding: '10px 10px 10px 18px',
          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
          backdropFilter: 'blur(20px)',
          transition: 'border-color 0.2s, box-shadow 0.2s',
        }}
          onFocus={() => {}}
          // CSS ile hover/focus efekti index.css'te
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => {
              setInput(e.target.value);
              // Auto-resize
              e.target.style.height = 'auto';
              e.target.style.height = Math.min(e.target.scrollHeight, 140) + 'px';
            }}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder={busy ? 'Jarvis düşünüyor…' : 'Bir şey sor…'}
            disabled={busy}
            rows={1}
            aria-label="Jarvis'e mesaj"
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              color: '#dfe2ff', fontSize: 15, fontFamily: 'inherit',
              resize: 'none', lineHeight: 1.55, overflowY: 'hidden',
              minHeight: 24, maxHeight: 140,
            }}
          />

          {/* Sağ araçlar */}
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexShrink: 0 }}>
            {/* Mikrofon — bas-konuş */}
            {dictation.supported && (
              <InputBtn
                title={dictation.listening ? 'Dur' : 'Sesle yaz'}
                active={dictation.listening}
                activeColor="rgba(241,121,143,0.25)"
                activeBorder="rgba(241,121,143,0.5)"
                onClick={() => dictation.listening ? dictation.stop() : dictation.start()}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                  <rect x="9" y="3" width="6" height="11" rx="3" />
                  <path d="M5 11a7 7 0 0014 0M12 18v3" />
                </svg>
              </InputBtn>
            )}

            {/* Orb mikrofon (ses görselleştirme) */}
            <InputBtn
              title={micOn ? 'Mikrofonu kapat' : 'Mikrofonu aç'}
              active={micOn}
              activeColor="rgba(100,80,255,0.25)"
              activeBorder="rgba(130,110,255,0.5)"
              onClick={() => void toggleMic()}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M12 2a4 4 0 014 4v4a4 4 0 01-8 0V6a4 4 0 014-4z" />
                <path d="M6 10a6 6 0 0012 0M12 18v3" />
              </svg>
            </InputBtn>

            {/* Gönder */}
            <button
              onClick={() => void send()}
              disabled={busy || !input.trim()}
              aria-label="Gönder"
              style={{
                width: 36, height: 36, borderRadius: 12,
                background: input.trim() && !busy ? 'rgba(100,80,255,0.35)' : 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(140,150,255,0.25)',
                color: '#dfe0ff', cursor: input.trim() && !busy ? 'pointer' : 'default',
                display: 'grid', placeItems: 'center',
                transition: 'background 0.15s',
                opacity: busy || !input.trim() ? 0.4 : 1,
              }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <path d="M4 12h15M14 7l5 5-5 5" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* ── sağ alt: orb ── */}
      <div style={{
        position: 'absolute', bottom: 108, right: 20,
        zIndex: 5,
        width: 72, height: 72,
        filter: 'drop-shadow(0 0 18px rgba(100,80,255,0.4))',
        cursor: 'pointer',
        transition: 'transform 0.3s ease',
      }}
        title="Orb modu değiştir"
        onClick={() => {
          const order: OrbMode[] = ['idle', 'listening', 'speaking'];
          setMode(m => order[(order.indexOf(m) + 1) % order.length]);
        }}
      >
        <canvas
          ref={orbRef}
          style={{ width: '100%', height: '100%', borderRadius: '50%', display: 'block' }}
        />
      </div>

      {/* ── paneller ── */}
      {adminOpen  && <AdminPanel onClose={() => setAdminOpen(false)} />}
      {notesOpen  && <NotesPanel onClose={() => setNotesOpen(false)} />}
      {codingOpen && <CodingPanel sessionId={sessionId} onClose={() => setCodingOpen(false)} />}
      {insight    && <InsightPanel section={insight} onClose={() => setInsight(null)} />}

      {/* ── animasyonlar ve global stiller ── */}
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes slideUp {
          from { opacity: 0; transform: translateY(24px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes blink {
          0%, 80%, 100% { opacity: 0.25; transform: scale(0.75); }
          40%            { opacity: 1;    transform: scale(1); }
        }

        /* Markdown stiller */
        .md { color: #d8dcff; font-size: 13.5px; line-height: 1.7; }
        .md p { margin: 0 0 8px; }
        .md p:last-child { margin-bottom: 0; }
        .md strong { color: #e8ecff; font-weight: 600; }
        .md em { color: #c8d0f8; font-style: italic; }
        .md code {
          font-family: 'JetBrains Mono', monospace;
          font-size: 12.5px;
          background: rgba(100,110,255,0.14);
          border: 1px solid rgba(100,110,255,0.2);
          border-radius: 5px;
          padding: 1px 6px;
          color: #b8c4ff;
        }
        .md pre {
          background: rgba(10,9,24,0.8);
          border: 1px solid rgba(100,110,255,0.18);
          border-radius: 10px;
          padding: 14px 16px;
          overflow-x: auto;
          margin: 8px 0;
        }
        .md pre code {
          background: none; border: none; padding: 0;
          font-size: 12.5px; color: #c8d4ff;
        }
        .md h1 { font-size: 18px; font-weight: 500; margin: 0 0 10px; color: #eef0ff; }
        .md h2 { font-size: 15px; font-weight: 500; margin: 0 0 8px; color: #e0e4ff; }
        .md h3 { font-size: 13.5px; font-weight: 600; margin: 0 0 6px; color: #d8dcff; }
        .md ul, .md ol { padding-left: 20px; margin: 6px 0; }
        .md li { margin: 3px 0; }
        .md blockquote {
          border-left: 3px solid rgba(100,110,255,0.4);
          margin: 8px 0; padding: 6px 14px;
          color: #a0a8d0; font-style: italic;
          background: rgba(100,110,255,0.06);
          border-radius: 0 8px 8px 0;
        }
        .md hr {
          border: none;
          border-top: 1px solid rgba(100,110,255,0.2);
          margin: 12px 0;
        }
        .md a { color: #8ca4ff; text-decoration: underline; text-decoration-color: rgba(140,164,255,0.4); }
        .md a:hover { color: #b4c8ff; }

        /* Input alanı focus efekti */
        textarea:focus { outline: none; }
      `}</style>
    </div>
  );
};

// ── Alt bileşenler ─────────────────────────────────────────────────────────

const MessageBubble = ({ msg }: { msg: Message }) => {
  const isUser = msg.role === 'user';
  return (
    <div style={{
      display: 'flex',
      flexDirection: isUser ? 'row-reverse' : 'row',
      gap: 10, alignItems: 'flex-end',
      animation: 'fadeIn 0.25s ease',
    }}>
      {/* Avatar */}
      {!isUser && (
        <div style={{
          width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
          background: 'linear-gradient(135deg, rgba(80,90,255,0.35), rgba(130,80,255,0.35))',
          border: '1px solid rgba(120,130,255,0.3)',
          display: 'grid', placeItems: 'center',
          fontSize: 10, color: '#9ba4d4', fontWeight: 500,
        }}>J</div>
      )}

      {/* Baloncuk */}
      <div style={{
        maxWidth: 'min(68%, 520px)',
        padding: isUser ? '9px 14px' : '11px 15px',
        borderRadius: isUser
          ? '16px 16px 4px 16px'
          : '16px 16px 16px 4px',
        background: isUser
          ? 'rgba(90,70,255,0.28)'
          : 'rgba(255,255,255,0.055)',
        border: `1px solid ${isUser ? 'rgba(110,90,255,0.35)' : 'rgba(255,255,255,0.08)'}`,
        backdropFilter: 'blur(8px)',
        fontSize: 13.5, lineHeight: 1.65, color: '#dde1ff',
        cursor: 'default',
        transition: 'background 0.15s',
      }}
        onMouseEnter={e => {
          (e.currentTarget as HTMLDivElement).style.background = isUser
            ? 'rgba(90,70,255,0.38)'
            : 'rgba(255,255,255,0.085)';
        }}
        onMouseLeave={e => {
          (e.currentTarget as HTMLDivElement).style.background = isUser
            ? 'rgba(90,70,255,0.28)'
            : 'rgba(255,255,255,0.055)';
        }}
      >
        {msg.role === 'jarvis'
          ? <Markdown text={msg.text} />
          : <span>{msg.text}</span>
        }
      </div>
    </div>
  );
};

const TypingIndicator = () => (
  <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', animation: 'fadeIn 0.2s ease' }}>
    <div style={{
      width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
      background: 'linear-gradient(135deg, rgba(80,90,255,0.35), rgba(130,80,255,0.35))',
      border: '1px solid rgba(120,130,255,0.3)',
      display: 'grid', placeItems: 'center',
      fontSize: 10, color: '#9ba4d4',
    }}>J</div>
    <div style={{
      padding: '12px 16px', borderRadius: '16px 16px 16px 4px',
      background: 'rgba(255,255,255,0.055)', border: '1px solid rgba(255,255,255,0.08)',
      display: 'flex', gap: 5, alignItems: 'center',
    }}>
      {[0, 1, 2].map(i => (
        <div key={i} style={{
          width: 6, height: 6, borderRadius: '50%', background: '#7c6cff',
          animation: `blink 1.3s ease-in-out ${i * 0.22}s infinite`,
        }} />
      ))}
    </div>
  </div>
);

interface TopButtonProps {
  title: string;
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}
const TopButton = ({ title, active, onClick, children }: TopButtonProps) => (
  <button
    title={title}
    aria-label={title}
    onClick={onClick}
    style={{
      width: 34, height: 34, borderRadius: 9,
      background: active ? 'rgba(100,80,255,0.22)' : 'transparent',
      border: `1px solid ${active ? 'rgba(120,100,255,0.4)' : 'rgba(140,150,255,0.10)'}`,
      color: active ? '#cfc4ff' : '#6870a0',
      cursor: 'pointer', display: 'grid', placeItems: 'center',
      transition: 'background 0.15s, color 0.15s, border-color 0.15s',
    }}
    onMouseEnter={e => {
      const b = e.currentTarget;
      b.style.background = active ? 'rgba(100,80,255,0.32)' : 'rgba(255,255,255,0.06)';
      b.style.color = '#c0caff';
      b.style.borderColor = 'rgba(140,150,255,0.25)';
    }}
    onMouseLeave={e => {
      const b = e.currentTarget;
      b.style.background = active ? 'rgba(100,80,255,0.22)' : 'transparent';
      b.style.color = active ? '#cfc4ff' : '#6870a0';
      b.style.borderColor = active ? 'rgba(120,100,255,0.4)' : 'rgba(140,150,255,0.10)';
    }}
  >
    {children}
  </button>
);

interface InputBtnProps {
  title: string;
  active?: boolean;
  activeColor?: string;
  activeBorder?: string;
  onClick: () => void;
  children: React.ReactNode;
}
const InputBtn = ({ title, active, activeColor, activeBorder, onClick, children }: InputBtnProps) => (
  <button
    title={title}
    aria-label={title}
    onClick={onClick}
    style={{
      width: 34, height: 34, borderRadius: 10,
      background: active ? (activeColor ?? 'rgba(100,80,255,0.2)') : 'transparent',
      border: `1px solid ${active ? (activeBorder ?? 'rgba(120,100,255,0.4)') : 'rgba(140,150,255,0.12)'}`,
      color: active ? '#e8e0ff' : '#5a6090',
      cursor: 'pointer', display: 'grid', placeItems: 'center',
      transition: 'background 0.15s, color 0.15s',
    }}
    onMouseEnter={e => {
      const b = e.currentTarget;
      if (!active) { b.style.background = 'rgba(255,255,255,0.06)'; b.style.color = '#b0baee'; }
    }}
    onMouseLeave={e => {
      const b = e.currentTarget;
      if (!active) { b.style.background = 'transparent'; b.style.color = '#5a6090'; }
    }}
  >
    {children}
  </button>
);
