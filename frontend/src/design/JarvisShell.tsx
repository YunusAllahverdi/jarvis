import { useCallback, useEffect, useRef, useState } from 'react';
import { AdminPanel } from './AdminPanel';
import { CodingPanel } from './CodingPanel';
import { InsightPanel, type InsightSection } from './InsightPanel';
import { useSpeech } from './useSpeech';
import { OrbEngine, type OrbMode } from './orb/OrbEngine';
import { apiClient, type ExperienceView, type SystemStatus } from '../api/client';
import {
  MODE_LABELS,
  NAV,
  SHORTCUTS,
  SUGGESTIONS,
  THEMES,
  THEME_NAMES,
  type ThemeName,
} from './data';

/* Tasarım sabit 1536×1024 bir sahne için çizildi; sahne pencereye
 * ölçeklenerek oturtuluyor, böylece yerleşim her ekranda aynı kalıyor. */
const STAGE_W = 1536;
const STAGE_H = 1024;

const PANEL: React.CSSProperties = {
  borderRadius: 15,
  background: 'rgba(14,13,32,0.55)',
  border: '1px solid rgba(140,150,255,0.12)',
  backdropFilter: 'blur(18px)',
};

const MONO = "'JetBrains Mono', ui-monospace, monospace";

interface Turn {
  role: 'user' | 'jarvis';
  text: string;
}

export const JarvisShell = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const barsRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<OrbEngine | null>(null);

  const [mode, setMode] = useState<OrbMode>('idle');
  const [theme, setTheme] = useState<ThemeName>('Gezegen');
  const [nav, setNav] = useState('Sohbet');
  const [micOn, setMicOn] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [codingOpen, setCodingOpen] = useState(false);
  const [insight, setInsight] = useState<InsightSection | null>(null);

  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turn, setTurn] = useState<Turn | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string>(MODE_LABELS.idle);

  /* Sabit örneklerin yerini alan gerçek veriler. Okunamazlarsa null kalır
   * ve ilgili panel "—" gösterir; uydurma bir değer ASLA konmaz. */
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [activities, setActivities] = useState<ExperienceView[]>([]);

  const speech = useSpeech();

  /* ── orb motoru ───────────────────────────────────────── */

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const engine = new OrbEngine(canvas, barsRef.current);
    engineRef.current = engine;
    engine.start();
    return () => {
      engine.destroy();
      engineRef.current = null;
    };
  }, []);

  useEffect(() => { engineRef.current?.setMode(mode); }, [mode]);
  useEffect(() => { engineRef.current?.setTheme(theme); }, [theme]);

  /* Sahneyi pencereye sığdır. */
  useEffect(() => {
    const fit = () => {
      const st = stageRef.current;
      if (!st) return;
      const s = Math.min(window.innerWidth / STAGE_W, window.innerHeight / STAGE_H);
      st.style.transform = `translate(-50%, -50%) scale(${s.toFixed(4)})`;
    };
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, []);

  /* ── canlı veriler ────────────────────────────────────── */

  /* Sistem durumu düzenli olarak tazelenir; anlık bir ölçüm tek seferlik
   * gösterildiğinde panel dakikalar önceki değeri gösterirdi. Hata sessizce
   * yutulur: kaynak okunamıyorsa panel "—" gösterir, sohbet etkilenmez. */
  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      apiClient
        .getSystemStatus()
        .then((value) => { if (!cancelled) setSystem(value); })
        .catch(() => { if (!cancelled) setSystem(null); });
    };
    refresh();
    const timer = window.setInterval(refresh, 10_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const refreshActivities = useCallback(() => {
    apiClient
      .getExperiences(3)
      .then((value) => setActivities(value.experiences))
      .catch(() => setActivities([]));
  }, []);

  useEffect(() => { refreshActivities(); }, [refreshActivities]);

  /* ── chat ─────────────────────────────────────────────── */

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;

    setInput('');
    setBusy(true);
    setTurn({ role: 'user', text });
    setStatus(MODE_LABELS.thinking);
    setMode('listening');

    try {
      const res = await apiClient.chat(text, sessionId);
      if (res.session_id) setSessionId(res.session_id);
      setTurn({ role: 'jarvis', text: res.response });
      setStatus(MODE_LABELS.speaking);
      setMode('speaking');
      // Ses kapalıysa bu çağrı hiçbir şey yapmaz; kontrol hook'un içindedir.
      speech.speak(res.response);
      // Bu tur bir deneyim ürettiyse aktivite listesi artık eskimiştir.
      refreshActivities();
      // Cevap uzunluğuna göre "konuşma" süresi; sonra dinlenmeye dön.
      const dwell = Math.min(Math.max(res.response.length * 40, 2000), 7000);
      window.setTimeout(() => {
        setMode('idle');
        setStatus(MODE_LABELS.idle);
      }, dwell);
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'Bilinmeyen hata';
      setTurn({ role: 'jarvis', text: `Bağlantı kurulamadı: ${detail}` });
      setStatus(MODE_LABELS.error);
      setMode('idle');
    } finally {
      setBusy(false);
    }
  }, [input, busy, sessionId, speech, refreshActivities]);

  /* Gezinme: her başlık artık gerçekten bir şey açar.
   *
   * "Sohbet" bir ekran açmaz çünkü sohbet zaten kabuğun kendisidir; onu bir
   * pencerenin içine koymak, ana yüzeyi ikinci plana atmak olurdu. Açık bir
   * panel varsa kapatılır — böylece "Sohbet" her zaman kabuğa dönüş anlamına
   * gelir. */
  const openNav = useCallback((label: string) => {
    setNav(label);
    setCodingOpen(false);
    setInsight(null);

    if (label === 'Ajanlar') {
      setCodingOpen(true);
      return;
    }
    if (label !== 'Sohbet') setInsight(label as InsightSection);
  }, []);

  const toggleMic = useCallback(async () => {
    const engine = engineRef.current;
    if (!engine) return;
    const ok = await engine.enableMic();
    setMicOn(ok);
  }, []);

  const cycleMode = useCallback(() => {
    const order: OrbMode[] = ['idle', 'listening', 'speaking'];
    setMode((m) => {
      const next = order[(order.indexOf(m) + 1) % order.length];
      setStatus(MODE_LABELS[next]);
      return next;
    });
  }, []);

  const micLabel = micOn
    ? 'Mikrofon açık'
    : engineRef.current?.isMicDenied()
      ? 'Mikrofon reddedildi'
      : 'Mikrofonu aç';

  /* ── görünüm ──────────────────────────────────────────── */

  return (
    <div style={{ position: 'fixed', inset: 0, width: '100vw', height: '100vh', background: '#04030c', overflow: 'hidden' }}>
      <div
        ref={stageRef}
        style={{
          position: 'absolute', top: '50%', left: '50%',
          width: STAGE_W, height: STAGE_H,
          transform: 'translate(-50%, -50%)', transformOrigin: 'center center',
          background: '#04030c',
          fontFamily: 'Sora, Helvetica, sans-serif',
          color: '#e6e8ff', overflow: 'hidden',
        }}
      >
        <canvas
          ref={canvasRef}
          onClick={cycleMode}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', display: 'block', cursor: 'pointer' }}
        />

        {/* kenarları karartan vinyet */}
        <div style={{
          position: 'absolute', inset: 0, pointerEvents: 'none',
          background: 'radial-gradient(120% 90% at 50% 45%, rgba(4,3,12,0) 40%, rgba(4,3,12,0.55) 100%)',
        }} />

        {/* ── marka ── */}
        <div style={{ position: 'absolute', top: 30, left: 34, display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 11, height: 11, borderRadius: '50%', background: '#a78bfa', boxShadow: '0 0 14px 4px rgba(167,139,250,0.7)' }} />
          <div style={{ fontSize: 13, letterSpacing: '0.42em', fontWeight: 500, color: '#dfe2ff' }}>JARVIS</div>
        </div>

        {/* ── sağ üst ── */}
        <div style={{ position: 'absolute', top: 26, right: 30, display: 'flex', alignItems: 'center', gap: 20 }}>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 16, opacity: 0.65 }}>
            {[5, 9, 16, 9, 5].map((h, i) => (
              <div key={i} style={{ width: 2, height: h, background: h === 16 ? '#c9d3ff' : '#8fa2ff' }} />
            ))}
          </div>
          <button
            onClick={() => setAdminOpen(true)}
            aria-label="Sağlayıcı ayarları"
            style={{
              width: 30, height: 30, borderRadius: 9, display: 'grid', placeItems: 'center',
              cursor: 'pointer', color: '#aab4e8', background: 'transparent', border: 'none',
            }}
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
              <circle cx="12" cy="12" r="3.2" /><circle cx="12" cy="12" r="8.4" />
            </svg>
          </button>
        </div>

        {/* ── sol: arama + gezinme ── */}
        <div style={{ position: 'absolute', top: 88, left: 22, width: 224, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {/* Arama kutusu belleği açar; daha önce hiçbir şeye bağlı değildi. */}
          <button
            onClick={() => openNav('Bellek')}
            aria-label="Bellekte ara"
            title="Bellekte ara"
            style={{ ...PANEL, borderRadius: 13, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 14px', height: 44, color: '#94a0d8', cursor: 'pointer', width: '100%', fontFamily: 'inherit' }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
              <rect x="3.5" y="4.5" width="17" height="13" rx="3.5" /><path d="M8 20.5l3-3" />
            </svg>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
              <circle cx="11" cy="11" r="6.5" /><path d="M16 16l4 4" />
            </svg>
          </button>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '6px 0' }}>
            {NAV.map((item) => {
              const active = nav === item.label;
              return (
                <div
                  key={item.label}
                  onClick={() => openNav(item.label)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12, height: 44,
                    padding: '0 14px', borderRadius: 12, cursor: 'pointer', transition: 'background .18s',
                    background: active ? 'rgba(112,92,255,0.20)' : undefined,
                    border: active ? '1px solid rgba(150,130,255,0.32)' : '1px solid transparent',
                    color: active ? '#cfc4ff' : '#9aa4cc',
                  }}
                >
                  <div style={{ width: 18, height: 18, display: 'grid', placeItems: 'center' }}>
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round">
                      <path d={item.path} />
                    </svg>
                  </div>
                  <div style={{ flex: 1, fontSize: 13.5, fontWeight: 400 }}>{item.label}</div>
                  {item.badge && (
                    <div style={{ fontSize: 10, padding: '3px 7px', borderRadius: 6, background: 'rgba(140,150,255,0.10)', color: '#8b96c8', fontFamily: MONO }}>
                      {item.badge}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* ── sol alt: sistem durumu ──
            Değerler artık ölçülüyor (/api/system/status, 10 saniyede bir).
            Okunamıyorsa "—" gösterilir; uydurma bir sayı ASLA konmaz. */}
        <div
          onClick={() => openNav('Sistem')}
          style={{ ...PANEL, position: 'absolute', left: 22, bottom: 96, width: 224, padding: '16px 16px 14px', cursor: 'pointer' }}
        >
          <div style={{ fontSize: 12.5, fontWeight: 500, color: '#dfe2ff' }}>Sistem Durumu</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginTop: 9 }}>
            <div style={{
              width: 7, height: 7, borderRadius: '50%',
              background: system ? '#4ade9b' : '#8b96c8',
              boxShadow: system ? '0 0 9px 2px rgba(74,222,155,0.45)' : undefined,
            }} />
            <div style={{ fontSize: 11.5, color: system ? '#8fd9b6' : '#8b96c8' }}>
              {system ? (system.is_local ? 'Bu makine' : 'Sunucu') : 'Ölçülemiyor'}
            </div>
          </div>
          <div style={{ height: 1, background: 'rgba(140,150,255,0.10)', margin: '14px 0 12px' }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 9, fontFamily: MONO, fontSize: 11 }}>
            {[
              ['CPU', system ? `${system.cpu_percent.toFixed(0)}%` : '—'],
              ['Bellek', system ? `${system.memory_percent.toFixed(0)}%` : '—'],
              ['Disk', system ? `${system.disk_percent.toFixed(0)}%` : '—'],
            ].map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', color: '#939ec9' }}>
                <span>{k}</span><span style={{ color: '#d7dcff' }}>{v}</span>
              </div>
            ))}
          </div>
          {/* Bellek doluluğu. Önceki rastgele çizgi kaldırıldı: ölçüm gibi
              görünen ama hiçbir şey ölçmeyen bir grafikti. */}
          <div style={{ marginTop: 14, height: 5, borderRadius: 3, background: 'rgba(140,150,255,0.12)', overflow: 'hidden' }}>
            <div style={{
              width: `${system ? Math.min(system.memory_percent, 100) : 0}%`,
              height: '100%', borderRadius: 3,
              background: 'linear-gradient(90deg, #7c6cff, #b7c4ff)',
              transition: 'width .5s ease',
            }} />
          </div>
        </div>

        {/* ── sol alt: kontroller ── */}
        <div style={{ position: 'absolute', left: 22, bottom: 26, display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* Sağlayıcı ayarları — daha önce hiçbir şey yapmayan kaydırıcı ikonu. */}
          <button
            onClick={() => setAdminOpen(true)}
            title="Sağlayıcı ayarları"
            aria-label="Sağlayıcı ayarları"
            style={{ width: 40, height: 40, borderRadius: 12, display: 'grid', placeItems: 'center', background: 'rgba(14,13,32,0.6)', border: '1px solid rgba(140,150,255,0.12)', color: '#aab4e8', cursor: 'pointer' }}
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
              <path d="M4 8h16M4 16h16" /><circle cx="9" cy="8" r="2" /><circle cx="15" cy="16" r="2" />
            </svg>
          </button>

          {/* Sesli cevap. Tarayıcı desteklemiyorsa düğme hiç çizilmez:
              basıldığında hiçbir şey yapmayan bir düğme, kırık bir düğmedir. */}
          {speech.supported && (
            <button
              onClick={() => {
                // Açılışta kısa bir onay: kullanıcı sesin gerçekten çalıştığını
                // bir cevabı beklemeden duyar. `toggle` yeni durumu döndürdüğü
                // için burada React state'inin güncellenmesini beklemek gerekmez.
                if (speech.toggle()) speech.speak('Sesli cevap açık.');
              }}
              title={speech.enabled ? 'Sesli cevabı kapat' : 'Sesli cevabı aç'}
              aria-label={speech.enabled ? 'Sesli cevabı kapat' : 'Sesli cevabı aç'}
              aria-pressed={speech.enabled}
              style={{
                width: 40, height: 40, borderRadius: 12, display: 'grid', placeItems: 'center', cursor: 'pointer',
                background: speech.enabled ? 'rgba(124,92,255,0.28)' : 'rgba(14,13,32,0.6)',
                border: `1px solid ${speech.enabled ? 'rgba(180,160,255,0.65)' : 'rgba(140,150,255,0.12)'}`,
                color: speech.enabled ? '#e6e2ff' : '#aab4e8',
              }}
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 9.5h3.2L12 5.5v13l-4.8-4H4z" />
                {speech.enabled ? (
                  <path d="M15.6 9a4.2 4.2 0 010 6M18 6.6a7.6 7.6 0 010 10.8" />
                ) : (
                  <path d="M16.5 9.8l4 4.4M20.5 9.8l-4 4.4" />
                )}
              </svg>
            </button>
          )}
          <div
            onClick={toggleMic}
            title={micLabel}
            style={{
              width: 40, height: 40, borderRadius: 12, display: 'grid', placeItems: 'center', cursor: 'pointer',
              background: micOn ? 'rgba(124,92,255,0.28)' : 'rgba(14,13,32,0.6)',
              border: `1px solid ${micOn ? 'rgba(180,160,255,0.65)' : 'rgba(140,150,255,0.12)'}`,
              color: micOn ? '#e6e2ff' : '#aab4e8',
            }}
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
              <rect x="9.2" y="3.2" width="5.6" height="10.4" rx="2.8" />
              <path d="M5.6 11.4a6.4 6.4 0 0012.8 0M12 17.8V21" />
            </svg>
          </div>
          <div
            onClick={cycleMode}
            style={{ width: 40, height: 40, borderRadius: '50%', display: 'grid', placeItems: 'center', background: 'rgba(124,92,255,0.30)', border: '1px solid rgba(170,150,255,0.55)', boxShadow: '0 0 22px 4px rgba(124,92,255,0.35)', cursor: 'pointer' }}
          >
            <div style={{ width: 13, height: 13, borderRadius: '50%', background: '#dfe0ff', boxShadow: '0 0 12px 3px rgba(200,190,255,0.8)' }} />
          </div>
        </div>

        {/* ── üst orta: durum çubuğu ── */}
        <div style={{
          ...PANEL, position: 'absolute', top: 30, left: '50%', transform: 'translateX(-50%)',
          width: 430, padding: '14px 20px', display: 'flex', alignItems: 'center', gap: 16,
          borderRadius: 16, border: '1px solid rgba(140,150,255,0.14)',
          backdropFilter: 'blur(20px)', boxShadow: '0 18px 50px -20px rgba(0,0,0,0.8)',
        }}>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2.5, height: 15, color: '#a5b0ff' }}>
            {[[6, 0.6], [12, 1], [8, 0.8], [15, 1]].map(([h, o], i) => (
              <div key={i} style={{ width: 2, height: h, background: 'currentColor', opacity: o }} />
            ))}
          </div>
          <div style={{ fontSize: 13.5, color: '#cfd5ff', whiteSpace: 'nowrap' }}>{status}</div>
          <div ref={barsRef} style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2, height: 30 }}>
            {Array.from({ length: 54 }, (_, i) => (
              <div key={i} style={{ width: 2, height: 26, borderRadius: 1, background: 'linear-gradient(180deg, #b7c4ff, #7c6cff)', transform: 'scaleY(0.12)', opacity: 0.5 }} />
            ))}
          </div>
          <div style={{ width: 7, height: 7, borderRadius: '50%', background: '#a78bfa', boxShadow: '0 0 10px 3px rgba(167,139,250,0.6)' }} />
        </div>

        {/* ── alt orta: konuşma ──
            Tasarımda burada sabit bir metin vardı; sohbetin çalışabilmesi
            için son cevabı gösteren bir alan ve bir metin girişi eklendi. */}
        <div style={{ position: 'absolute', bottom: 118, left: '50%', transform: 'translateX(-50%)', textAlign: 'center', width: 720 }}>
          <div style={{
            fontSize: 21, fontWeight: 300, letterSpacing: '0.01em',
            color: 'rgba(220,225,255,0.86)', textShadow: '0 0 30px rgba(120,110,255,0.5)',
            minHeight: 62, display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: '0 24px', lineHeight: 1.45,
          }}>
            {turn ? turn.text : 'Nasıl yardımcı olabilirim?'}
          </div>

          <div style={{
            ...PANEL, display: 'flex', alignItems: 'center', gap: 12,
            margin: '20px auto 0', width: 520, height: 48, padding: '0 8px 0 18px', borderRadius: 14,
          }}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void send(); } }}
              placeholder={busy ? 'Jarvis düşünüyor...' : 'Bir şey sorun'}
              disabled={busy}
              aria-label="Jarvis'e mesaj"
              style={{
                flex: 1, background: 'transparent', border: 'none', outline: 'none',
                color: '#dfe2ff', fontSize: 14, fontFamily: 'inherit',
              }}
            />
            <button
              onClick={() => void send()}
              disabled={busy || !input.trim()}
              aria-label="Gönder"
              style={{
                width: 34, height: 34, borderRadius: 10, display: 'grid', placeItems: 'center',
                background: input.trim() && !busy ? 'rgba(124,92,255,0.30)' : 'rgba(140,150,255,0.08)',
                border: '1px solid rgba(170,150,255,0.35)',
                color: '#dfe0ff', cursor: input.trim() && !busy ? 'pointer' : 'default',
              }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                <path d="M4 12h15M14 7l5 5-5 5" />
              </svg>
            </button>
          </div>
        </div>

        {/* ── sağ: kısayollar / aktiviteler / öneriler ── */}
        <div style={{ position: 'absolute', top: 88, right: 22, width: 292, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ ...PANEL, padding: 18 }}>
            <div style={{ fontSize: 12.5, fontWeight: 500, color: '#dfe2ff', marginBottom: 16 }}>Kısa Yollar</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
              {SHORTCUTS.map((s) => (
                <button
                  key={s.label}
                  onClick={() => s.section ? openNav(s.section) : setInput(s.prompt ?? s.label)}
                  title={s.section ? `${s.section} ekranını aç` : 'Sohbete yaz'}
                  style={{
                    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8,
                    cursor: 'pointer', background: 'transparent', border: 'none', padding: 0,
                    fontFamily: 'inherit',
                  }}
                >
                  <div style={{ width: '100%', aspectRatio: '1', borderRadius: 11, display: 'grid', placeItems: 'center', background: 'rgba(140,150,255,0.06)', border: '1px solid rgba(140,150,255,0.14)', color: '#b9c2f0' }}>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round">
                      <path d={s.path} />
                    </svg>
                  </div>
                  <div style={{ fontSize: 10.5, color: '#8f9ac6' }}>{s.label}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Aktiviteler artık gerçek deneyimlerden geliyor (/api/experiences).
              Hiç kayıt yoksa bu açıkça söylenir — sahte üç satır göstermek,
              olmayan bir geçmişi varmış gibi sunmak olurdu. */}
          <div style={{ ...PANEL, padding: 18 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <div style={{ fontSize: 12.5, fontWeight: 500, color: '#dfe2ff' }}>Son Aktiviteler</div>
              <div style={{ width: 14, height: 1, background: 'rgba(150,150,255,0.4)' }} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {activities.length === 0 ? (
                <div style={{ fontSize: 12, color: '#8b96c8', lineHeight: 1.6 }}>
                  Henüz kaydedilmiş bir etkileşim yok.
                </div>
              ) : (
                activities.map((item) => (
                  <div key={item.id} style={{ display: 'flex', gap: 11 }}>
                    <div style={{ marginTop: 3, width: 11, height: 11, borderRadius: '50%', border: '1.4px solid rgba(150,140,255,0.75)', display: 'grid', placeItems: 'center', flex: 'none' }}>
                      <div style={{ width: 4, height: 4, borderRadius: '50%', background: 'rgba(190,180,255,0.9)' }} />
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 0 }}>
                      <div style={{ fontSize: 11, color: '#9aa4cf', fontFamily: MONO }}>
                        {new Date(item.occurred_at).toLocaleString('tr-TR')}
                      </div>
                      <div style={{
                        fontSize: 12.5, color: '#d3d8ff', fontWeight: 300,
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }}>
                        {item.user_message}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
            <button
              onClick={() => openNav('Deneyimler')}
              style={{
                marginTop: 18, width: '100%', height: 38, borderRadius: 11,
                border: '1px solid rgba(140,150,255,0.16)', background: 'transparent',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9,
                fontSize: 12, color: '#c3cbf6', cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              <span>Tüm Aktiviteler</span>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
                <path d="M4 12h15M14 7l5 5-5 5" />
              </svg>
            </button>
          </div>

          <div style={{ ...PANEL, padding: 18 }}>
            <div style={{ fontSize: 12.5, fontWeight: 500, color: '#dfe2ff', marginBottom: 15 }}>Önerilenler</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {SUGGESTIONS.map((s) => (
                <div
                  key={s.label}
                  onClick={() => setInput(s.label)}
                  style={{ display: 'flex', alignItems: 'center', gap: 11, cursor: 'pointer', color: '#aeb7e2' }}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round">
                    <path d={s.path} />
                  </svg>
                  <div style={{ fontSize: 12.5, fontWeight: 300 }}>{s.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── sağ alt: tema ── */}
        <div style={{ ...PANEL, position: 'absolute', right: 22, bottom: 26, width: 330, padding: '15px 16px 16px', background: 'rgba(14,13,32,0.6)' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontSize: 12.5, fontWeight: 500, color: '#dfe2ff' }}>Tema</div>
              <div style={{ fontSize: 11, color: '#8b96c4', marginTop: 3 }}>{theme} · {THEMES[theme].sub}</div>
            </div>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="rgba(160,168,210,0.8)" strokeWidth="1.4" strokeLinecap="round">
              <path d="M6 14l6-6 6 6" />
            </svg>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 9, marginTop: 13 }}>
            {THEME_NAMES.map((name) => (
              <div key={name} onClick={() => setTheme(name)} style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                <div style={{
                  aspectRatio: '1/0.72', borderRadius: 9, overflow: 'hidden', cursor: 'pointer',
                  border: `1px solid ${theme === name ? 'rgba(200,190,255,0.85)' : 'rgba(140,150,255,0.16)'}`,
                }}>
                  <svg width="100%" height="100%" viewBox="0 0 60 44" preserveAspectRatio="none" style={{ display: 'block' }}>
                    <rect width="60" height="44" fill={THEMES[name].bg} />
                    <path d="M-6 44L18 8M8 44L32 8M22 44L46 8M36 44L60 8M50 44L74 8" stroke="rgba(255,255,255,0.09)" strokeWidth="3" />
                    <circle cx="30" cy="24" r="9" fill="rgba(255,255,255,0.13)" />
                  </svg>
                </div>
                <div style={{ fontSize: 10, textAlign: 'center', color: '#98a2cd' }}>{name}</div>
              </div>
            ))}
          </div>
        </div>

        {adminOpen && <AdminPanel onClose={() => setAdminOpen(false)} />}
        {codingOpen && (
          <CodingPanel sessionId={sessionId} onClose={() => setCodingOpen(false)} />
        )}
        {insight && (
          <InsightPanel section={insight} onClose={() => setInsight(null)} />
        )}
      </div>
    </div>
  );
};
