/**
 * Cowork Modu — proje masası.
 * Jarvis küçük orb olarak sol altta durur, ana alan çalışma yüzeyi.
 * Notlar, kodlama ve sohbet yan yana.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { OrbEngine } from './orb/OrbEngine';
import { Markdown } from './Markdown';
import { apiClient } from '../api/client';
import { useSpeech } from './useSpeech';
import { useDictation } from './useDictation';
import { AdminPanel } from './AdminPanel';

interface Message { role: 'user' | 'jarvis'; text: string; ts: number; }

interface Props { onExit: () => void; }

export const CoworkMode = ({ onExit }: Props) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<OrbEngine | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [adminOpen, setAdminOpen] = useState(false);

  const speech = useSpeech();
  const dictation = useDictation(useCallback((t: string) => setInput(t), []));

  // Orb — küçük boyut
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const eng = new OrbEngine(cv);
    engineRef.current = eng;
    eng.start();
    return () => { eng.destroy(); engineRef.current = null; };
  }, []);

  // Mesaj listesi en alta scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    setBusy(true);
    engineRef.current?.setMode('listening');
    setMessages(prev => [...prev, { role: 'user', text, ts: Date.now() }]);
    try {
      const res = await apiClient.chat(text, sessionId);
      if (res.session_id) setSessionId(res.session_id);
      setMessages(prev => [...prev, { role: 'jarvis', text: res.response, ts: Date.now() }]);
      engineRef.current?.setMode('speaking');
      speech.speak(res.response);
      setTimeout(() => engineRef.current?.setMode('idle'), 3000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Hata';
      setMessages(prev => [...prev, { role: 'jarvis', text: `Hata: ${msg}`, ts: Date.now() }]);
      engineRef.current?.setMode('idle');
    } finally {
      setBusy(false);
    }
  }, [input, busy, sessionId, speech]);

  return (
    <div style={{
      position: 'fixed', inset: 0,
      background: '#07060f',
      display: 'flex', flexDirection: 'column',
      fontFamily: 'Sora, Helvetica, sans-serif',
      color: '#e0e4ff',
    }}>
      {/* Üst bar */}
      <div style={{
        height: 52, borderBottom: '1px solid rgba(140,150,255,0.10)',
        display: 'flex', alignItems: 'center', gap: 12, padding: '0 20px',
        background: 'rgba(10,9,24,0.95)',
        flexShrink: 0,
      }}>
        {/* Orb küçük */}
        <canvas
          ref={canvasRef}
          style={{ width: 32, height: 32, borderRadius: '50%', flexShrink: 0 }}
        />
        <span style={{ fontSize: 12, letterSpacing: '0.3em', color: '#9ba4d4', fontWeight: 500 }}>
          JARVIS · COWORK
        </span>
        <div style={{ flex: 1 }} />
        {/* Araçlar */}
        <button
          onClick={() => setAdminOpen(true)}
          title="Ayarlar"
          style={iconBtn}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3M4.22 19.78l2.12-2.12M17.66 6.34l2.12-2.12" />
          </svg>
        </button>
        <button
          onClick={onExit}
          title="Normal moda dön"
          style={{ ...iconBtn, color: '#f07070' }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Ana içerik */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Sohbet paneli */}
        <div style={{
          width: '100%', maxWidth: 680,
          display: 'flex', flexDirection: 'column',
          borderRight: '1px solid rgba(140,150,255,0.08)',
        }}>
          {/* Mesajlar */}
          <div style={{
            flex: 1, overflowY: 'auto', padding: '20px 24px',
            display: 'flex', flexDirection: 'column', gap: 16,
          }}>
            {messages.length === 0 && (
              <div style={{ color: '#555a7a', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
                Proje hakkında bir şey sor, kod yaz, not al…
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} style={{
                display: 'flex',
                flexDirection: m.role === 'user' ? 'row-reverse' : 'row',
                gap: 10, alignItems: 'flex-start',
              }}>
                {m.role === 'jarvis' && (
                  <div style={{
                    width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                    background: 'rgba(90,100,255,0.25)',
                    border: '1px solid rgba(120,130,255,0.3)',
                    display: 'grid', placeItems: 'center', fontSize: 10, color: '#9ba4d4',
                  }}>J</div>
                )}
                <div style={{
                  maxWidth: '78%', padding: '10px 14px',
                  borderRadius: m.role === 'user' ? '14px 14px 4px 14px' : '14px 14px 14px 4px',
                  background: m.role === 'user'
                    ? 'rgba(100,80,255,0.22)'
                    : 'rgba(255,255,255,0.05)',
                  border: `1px solid ${m.role === 'user' ? 'rgba(120,100,255,0.3)' : 'rgba(255,255,255,0.07)'}`,
                  fontSize: 13.5, lineHeight: 1.65,
                }}>
                  {m.role === 'jarvis'
                    ? <Markdown text={m.text} />
                    : <span>{m.text}</span>
                  }
                </div>
              </div>
            ))}
            {busy && (
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <div style={{
                  width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
                  background: 'rgba(90,100,255,0.25)', border: '1px solid rgba(120,130,255,0.3)',
                  display: 'grid', placeItems: 'center', fontSize: 10, color: '#9ba4d4',
                }}>J</div>
                <div style={{
                  padding: '12px 16px', borderRadius: '14px 14px 14px 4px',
                  background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.07)',
                  display: 'flex', gap: 6, alignItems: 'center',
                }}>
                  {[0, 1, 2].map(i => (
                    <div key={i} style={{
                      width: 6, height: 6, borderRadius: '50%',
                      background: '#7c6cff',
                      animation: `pulse 1.2s ease-in-out ${i * 0.2}s infinite`,
                    }} />
                  ))}
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div style={{
            padding: '12px 16px',
            borderTop: '1px solid rgba(140,150,255,0.08)',
            display: 'flex', gap: 8,
          }}>
            <div style={{
              flex: 1, display: 'flex', alignItems: 'flex-end', gap: 8,
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(140,150,255,0.15)',
              borderRadius: 12, padding: '8px 12px',
            }}>
              <textarea
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
                placeholder={busy ? 'Jarvis düşünüyor…' : 'Mesajınızı yazın (Enter = gönder)'}
                disabled={busy}
                rows={1}
                style={{
                  flex: 1, background: 'transparent', border: 'none', outline: 'none',
                  color: '#dfe2ff', fontSize: 13.5, fontFamily: 'inherit',
                  resize: 'none', lineHeight: 1.5, maxHeight: 120, overflowY: 'auto',
                }}
              />
            </div>
            {dictation.supported && (
              <button
                onClick={() => dictation.listening ? dictation.stop() : dictation.start()}
                style={{
                  ...iconBtn,
                  background: dictation.listening ? 'rgba(241,121,143,0.2)' : 'rgba(255,255,255,0.04)',
                  border: `1px solid ${dictation.listening ? 'rgba(241,121,143,0.5)' : 'rgba(140,150,255,0.15)'}`,
                  borderRadius: 10, color: dictation.listening ? '#ffd9e1' : '#9ba4d4',
                  width: 40, height: 40,
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                  <rect x="9" y="3" width="6" height="11" rx="3" />
                  <path d="M5 11a7 7 0 0014 0M12 18v3" />
                </svg>
              </button>
            )}
            <button
              onClick={() => void send()}
              disabled={busy || !input.trim()}
              style={{
                ...iconBtn,
                background: input.trim() && !busy ? 'rgba(100,80,255,0.3)' : 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(140,150,255,0.2)',
                borderRadius: 10, width: 40, height: 40,
                opacity: busy || !input.trim() ? 0.4 : 1,
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M4 12h15M14 7l5 5-5 5" />
              </svg>
            </button>
          </div>
        </div>

        {/* Sağ panel — gelecekte notlar/kodlama buraya */}
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#2a2d4a', fontSize: 13, flexDirection: 'column', gap: 8,
          padding: 32,
        }}>
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity={0.3}>
            <rect x="3" y="3" width="18" height="18" rx="3" />
            <path d="M8 12h8M8 8h5M8 16h3" />
          </svg>
          <span style={{ opacity: 0.3 }}>Notlar ve kodlama paneli yakında</span>
        </div>
      </div>

      {adminOpen && <AdminPanel onClose={() => setAdminOpen(false)} />}

      <style>{`
        @keyframes pulse {
          0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
          40% { opacity: 1; transform: scale(1); }
        }
      `}</style>
    </div>
  );
};

const iconBtn: React.CSSProperties = {
  width: 34, height: 34, borderRadius: 8,
  background: 'transparent', border: 'none',
  color: '#8b94c8', cursor: 'pointer',
  display: 'grid', placeItems: 'center',
  transition: 'background 0.15s, color 0.15s',
};
