import { useState } from 'react';
import { Send } from 'lucide-react';
import { apiClient } from '../../api/client';
import { useUI } from '../../contexts/UIContext';
import { motion, AnimatePresence } from 'framer-motion';

interface Msg { id: string; role: 'user' | 'jarvis'; content: string; }

export const FloatingChat = () => {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const { setOrbState, openPanel, orbState } = useUI();

  const handleSend = async () => {
    const text = input.trim();
    if (!text || orbState === 'thinking') return;

    const userMsg: Msg = { id: `${Date.now()}`, role: 'user', content: text };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setOrbState('thinking');

    // Keyword-based panel trigger (placeholder for backend-driven panels)
    const lower = text.toLowerCase();
    if (lower.includes('status') || lower.includes('system') || lower.includes('diagnostic')) {
      openPanel('system');
    }

    try {
      const res = await apiClient.chat(text, sessionId);
      if (res.session_id) setSessionId(res.session_id);
      setOrbState('speaking');

      const jarvisMsg: Msg = { id: `${Date.now()}-j`, role: 'jarvis', content: res.response };
      setMessages(prev => [...prev, jarvisMsg]);

      const speakDuration = Math.min(Math.max(res.response.length * 40, 2000), 7000);
      setTimeout(() => setOrbState('idle'), speakDuration);
    } catch {
      setOrbState('error');
      setTimeout(() => setOrbState('idle'), 3000);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') { e.preventDefault(); handleSend(); }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

      {/* ── Recent messages — last 3, fading ── */}
      <div style={{
        display: 'flex', flexDirection: 'column', gap: '10px',
        padding: '0 12px', minHeight: '80px', justifyContent: 'flex-end',
      }}>
        <AnimatePresence>
          {messages.slice(-3).map((msg, idx, arr) => {
            const age = arr.length - 1 - idx; // 0 = newest
            return (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 12, filter: 'blur(6px)' }}
                animate={{
                  opacity: Math.max(0.15, 1 - age * 0.45),
                  y: 0,
                  filter: 'blur(0px)',
                }}
                exit={{ opacity: 0, scale: 0.97 }}
                transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                style={{
                  alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  padding: msg.role === 'user' ? '8px 16px' : '0 6px',
                  borderRadius: '14px',
                  maxWidth: '80%',
                  fontSize: msg.role === 'jarvis' ? '1.05rem' : '0.95rem',
                  fontWeight: msg.role === 'jarvis' ? 300 : 400,
                  color: 'var(--text-primary)',
                  background: msg.role === 'user'
                    ? 'rgba(255,255,255,0.04)'
                    : 'transparent',
                  border: msg.role === 'user'
                    ? '1px solid rgba(255,255,255,0.06)'
                    : 'none',
                  textShadow: msg.role === 'jarvis'
                    ? '0 0 30px rgba(200,180,255,0.15)'
                    : 'none',
                  letterSpacing: '0.01em',
                  lineHeight: 1.65,
                }}
              >
                {msg.content}
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      {/* ── Input bar — minimal, translucent ── */}
      <div style={{
        display: 'flex', alignItems: 'center',
        padding: '6px 8px',
        borderRadius: '20px',
        background: 'rgba(8, 6, 18, 0.45)',
        backdropFilter: 'blur(24px)',
        WebkitBackdropFilter: 'blur(24px)',
        border: '1px solid rgba(120, 100, 255, 0.07)',
        boxShadow: '0 4px 30px rgba(0,0,0,0.25)',
      }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => { if (orbState === 'idle') setOrbState('listening'); }}
          onBlur={() => { if (orbState === 'listening') setOrbState('idle'); }}
          placeholder="How can I help?"
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            padding: '10px 16px',
            fontSize: '1rem',
            fontWeight: 300,
            color: 'var(--text-primary)',
            letterSpacing: '0.02em',
            fontFamily: 'inherit',
          }}
        />
        <button
          onClick={handleSend}
          disabled={!input.trim()}
          style={{
            width: '36px', height: '36px',
            borderRadius: '50%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: input.trim() ? 'rgba(120, 100, 255, 0.15)' : 'transparent',
            border: 'none', cursor: input.trim() ? 'pointer' : 'default',
            transition: 'all 0.25s ease',
            opacity: input.trim() ? 1 : 0.3,
          }}
        >
          <Send size={17} color="var(--accent-color)" />
        </button>
      </div>
    </div>
  );
};
