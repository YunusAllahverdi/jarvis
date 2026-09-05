import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '../api/client';
import { useDictation } from '../design/useDictation';
import { useSpeech } from '../design/useSpeech';
import { ApprovalTray } from './ApprovalTray';
import { ChatView } from './ChatView';
import { DeskOrb, PHASE_LABEL } from './orb/DeskOrb';
import { SettingsView } from './settings/SettingsView';
import { C, FONT, KEYFRAMES } from './theme';
import { useConversation } from './useConversation';
import { useDeskPrefs } from './useDeskPrefs';
import { useWindows } from './useWindows';
import { CalculatorWindow } from './windows/CalculatorWindow';
import { CodingWindow } from './windows/CodingWindow';
import { FilesWindow } from './windows/FilesWindow';
import { NotesWindow } from './windows/NotesWindow';
import { QuoteCard } from './windows/QuoteCard';
import { TasksWindow } from './windows/TasksWindow';
import { WebWindow } from './windows/WebWindow';

/**
 * Masanın kendisi: ortam, başlık, kip geçişleri, küre ve giriş çubuğu.
 *
 * Dört kip vardır ve hepsi AYNI ağaçta durur; kip değiştiğinde bileşenler
 * sökülüp yeniden kurulmaz. Sökülselerdi küre her geçişte WebGL bağlamını
 * yeniden kurar, masadaki pencereler yerlerini unuturdu — geçişin
 * akıcılığı tam da bunun olmamasından geliyor.
 */

type Mode = 'home' | 'chat' | 'desk' | 'settings';

const MODES: { id: Mode; label: string }[] = [
  { id: 'home', label: 'ANA EKRAN' },
  { id: 'chat', label: 'SOHBET' },
  { id: 'desk', label: 'MASA' },
  { id: 'settings', label: 'AYARLAR' },
];

const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
const DAYS = ['Pazar', 'Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi'];

export const Desk = () => {
  const [mode, setMode] = useState<Mode>('home');
  const [draft, setDraft] = useState('');
  const [now, setNow] = useState(() => new Date());
  const [menuOpen, setMenuOpen] = useState(false);
  const [modelMissing, setModelMissing] = useState(false);
  // Ajan bir not yazdığında pencerelerin tazelenmesi için artan sayaç.
  const [dataVersion, setDataVersion] = useState(0);

  const { prefs, update } = useDeskPrefs();
  const windows = useWindows();
  const chat = useConversation();
  const speech = useSpeech();
  const inputRef = useRef<HTMLInputElement | null>(null);

  const dictation = useDictation(
    useCallback((text: string) => setDraft((current) => (current ? `${current} ${text}` : text)), []),
  );

  /* Saat 20 saniyede bir güncellenir. Saniyede bir, ekranda hiçbir şeyin
     değişmediği 19 render demek olurdu. */
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 20000);
    return () => window.clearInterval(id);
  }, []);

  const checkModel = useCallback(() => {
    void apiClient
      .getLlmConfig()
      .then((config) => setModelMissing(!config.model?.trim()))
      // Sunucuya ulaşılamıyorsa "model yok" demek YANLIŞ teşhis olurdu;
      // kullanıcı olmayan bir ayarı düzeltmeye çalışırdı.
      .catch(() => setModelMissing(false));
  }, []);

  useEffect(() => { checkModel(); }, [checkModel]);

  /* Ajanın panel açma istekleri.
   *
   * Okuma TÜKETİR: aksiyon sunucuda kalsaydı her yoklamada pencere
   * yeniden açılır ve kullanıcının kapattığı pencere geri gelirdi. */
  useEffect(() => {
    const id = window.setInterval(() => {
      void apiClient
        .consumeUiActions(chat.sessionId)
        .then((result) => {
          if (result.actions.length === 0) return;
          setMode('desk');
          result.actions.forEach((action) => {
            if (action.panel === 'notes') windows.open('notlar');
            if (action.panel === 'coding') windows.open('kodlama');
          });
          setDataVersion((value) => value + 1);
        })
        .catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(id);
  }, [chat.sessionId, windows]);

  const send = async () => {
    const text = draft.trim();
    if (!text || chat.busy) return;
    setDraft('');
    setMode('chat');
    const reply = await chat.send(text);
    // Not yazılmış olabilir; pencereler tazelensin.
    setDataVersion((value) => value + 1);
    if (reply && prefs.voice) speech.speak(reply);
  };

  const toggleVoice = () => {
    const enabled = speech.toggle();
    update('voice', enabled);
    if (enabled) speech.speak('Ses açık.');
  };

  const orbGeometry = {
    home: { left: '50%', top: '42%', size: prefs.orbSize },
    chat: { left: 'calc(50% - min(350px,32vw) - 48px)', top: 'calc(100% - 110px)', size: 66 },
    desk: { left: 'calc(100% - 150px)', top: 'calc(100% - 190px)', size: 196 },
    settings: { left: 'calc(100% - 130px)', top: 'calc(100% - 130px)', size: 128 },
  }[mode];

  return (
    <div
      style={{
        position: 'relative', width: '100%', height: '100vh', minHeight: 420,
        fontFamily: FONT, color: C.text, background: '#05060a', overflow: 'hidden',
      }}
    >
      <style>{KEYFRAMES}</style>

      {/* ortam */}
      <div style={{ position: 'absolute', inset: 0, background: 'radial-gradient(120% 90% at 18% 0%, #1a2030 0%, #0b0e15 42%, #05060a 78%)' }} />
      <div style={{ position: 'absolute', left: '-18%', top: '-46%', width: '90%', height: '120%', borderRadius: '50%', background: 'radial-gradient(circle at 60% 60%, rgba(150,175,215,.20), rgba(150,175,215,0) 62%)' }} />
      <div style={{ position: 'absolute', right: '-6%', top: '8%', width: '70%', height: '78%', background: 'linear-gradient(118deg, rgba(255,255,255,0) 42%, rgba(255,255,255,.16) 49%, rgba(255,255,255,0) 55%)', filter: 'blur(2px)' }} />
      <div style={{ position: 'absolute', right: '2%', top: 0, width: '44%', height: '60%', background: 'linear-gradient(120deg, rgba(255,120,60,0) 44%, rgba(255,170,90,.30) 49%, rgba(120,200,255,.22) 52%, rgba(160,120,255,0) 58%)', filter: 'blur(6px)', opacity: 0.55 }} />
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: '38%', background: 'linear-gradient(180deg, rgba(5,6,10,0), rgba(9,11,17,.85) 40%, rgba(12,15,22,.95))' }} />

      {mode === 'desk' && prefs.grid ? (
        <div
          style={{
            position: 'absolute', inset: 0, opacity: 0.5,
            backgroundImage:
              'linear-gradient(rgba(255,255,255,.055) 1px, transparent 1px),linear-gradient(90deg, rgba(255,255,255,.055) 1px, transparent 1px)',
            backgroundSize: '76px 76px',
            maskImage: 'radial-gradient(130% 100% at 50% 45%, #000 20%, transparent 78%)',
            WebkitMaskImage: 'radial-gradient(130% 100% at 50% 45%, #000 20%, transparent 78%)',
          }}
        />
      ) : null}

      {/* başlık */}
      <div style={{ position: 'absolute', left: 34, top: 26, zIndex: 60, display: 'flex', alignItems: 'flex-start', gap: 14 }}>
        <div>
          <div style={{ fontSize: 19, letterSpacing: '.42em', color: '#e9edf6' }}>J.A.R.V.I.S</div>
          <div style={{ marginTop: 8, display: 'flex', gap: 14, fontSize: 11.5, letterSpacing: '.24em', color: 'rgba(232,236,244,.42)' }}>
            <span>Focus</span><span>·</span><span>Build</span><span>·</span><span>Execute</span>
          </div>
        </div>
        <button
          onClick={() => setMenuOpen((open) => !open)}
          aria-label="Hızlı ayarlar"
          style={{
            width: 30, height: 30, marginTop: -3, borderRadius: 9, cursor: 'pointer',
            border: '1px solid rgba(255,255,255,.10)', background: 'rgba(255,255,255,.045)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <span style={{ width: 13, height: 13, borderRadius: '50%', border: '1.4px solid rgba(232,236,244,.62)', position: 'relative' }}>
            <span style={{ position: 'absolute', inset: 3.4, borderRadius: '50%', background: 'rgba(232,236,244,.62)' }} />
          </span>
        </button>
      </div>

      <div style={{ position: 'absolute', right: 36, top: 24, zIndex: 60, textAlign: 'right' }}>
        <div style={{ fontSize: 30, fontWeight: 300, letterSpacing: '.04em', color: 'rgba(233,237,246,.86)' }}>
          {pad(now.getHours())}:{pad(now.getMinutes())}
        </div>
        <div style={{ marginTop: 4, fontSize: 11.5, letterSpacing: '.14em', color: 'rgba(232,236,244,.40)' }}>
          {now.getDate()} {MONTHS[now.getMonth()]} {now.getFullYear()}
        </div>
        <div style={{ marginTop: 2, fontSize: 11.5, letterSpacing: '.14em', color: 'rgba(232,236,244,.40)' }}>
          {DAYS[now.getDay()]}
        </div>
      </div>

      {/* hızlı ayarlar */}
      {menuOpen ? (
        <div
          style={{
            position: 'absolute', left: 34, top: 104, zIndex: 120, width: 268, padding: 16,
            borderRadius: 16, border: '1px solid rgba(255,255,255,.10)',
            background: 'rgba(16,19,27,.86)', backdropFilter: 'blur(26px)',
            boxShadow: '0 30px 70px rgba(0,0,0,.55)', animation: 'deskFadeUp .18s ease both',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <span style={{ fontSize: 12, letterSpacing: '.2em', color: C.dim }}>AYARLAR</span>
            <button onClick={() => setMenuOpen(false)} aria-label="Kapat" style={{ background: 'transparent', border: 'none', color: 'rgba(232,236,244,.45)', fontSize: 15, cursor: 'pointer' }}>×</button>
          </div>
          <MenuRow label="Masa ızgarası" value={prefs.grid ? 'AÇIK' : 'KAPALI'} onClick={() => update('grid', !prefs.grid)} />
          <MenuRow label="Küre animasyonu" value={prefs.orbAnimated ? 'AÇIK' : 'KAPALI'} onClick={() => update('orbAnimated', !prefs.orbAnimated)} />
          <MenuRow
            label="Sesli yanıt"
            value={!speech.supported ? 'YOK' : prefs.voice ? 'AÇIK' : 'KAPALI'}
            onClick={() => speech.supported && toggleVoice()}
          />
          <MenuRow label="Masayı sıfırla" value="↺" onClick={() => { windows.reset(); setMenuOpen(false); }} />
          <MenuRow label="Tüm ayarlar" value="→" onClick={() => { setMode('settings'); setMenuOpen(false); }} />
        </div>
      ) : null}

      {/* masa */}
      {mode === 'desk' ? (
        <div style={{ position: 'absolute', inset: 0, zIndex: 30, overflow: 'auto' }}>
          <div style={{ position: 'relative', width: '100%', height: '100%', minWidth: 1560, minHeight: 900 }}>
            <NotesWindow win={windows.view('notlar')} refreshKey={dataVersion} />
            <WebWindow win={windows.view('web')} />
            <CalculatorWindow win={windows.view('hesap')} />
            <FilesWindow win={windows.view('dosyalar')} />
            <TasksWindow win={windows.view('gorevler')} refreshKey={dataVersion} />
            <CodingWindow win={windows.view('kodlama')} sessionId={chat.sessionId} />
            <QuoteCard win={windows.view('quote')} />
          </div>
        </div>
      ) : null}

      {mode === 'desk' && windows.hidden.length > 0 ? (
        <div style={{ position: 'absolute', left: 34, bottom: 26, zIndex: 75, display: 'flex', flexWrap: 'wrap', gap: 8, maxWidth: 420 }}>
          {windows.hidden.map((item) => (
            <button
              key={item.key}
              onClick={item.restore}
              style={{
                padding: '7px 13px', borderRadius: 20, cursor: 'pointer',
                border: '1px solid rgba(255,255,255,.10)', background: 'rgba(255,255,255,.05)',
                fontSize: 11.5, letterSpacing: '.06em', color: 'rgba(232,236,244,.72)',
                fontFamily: 'inherit',
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}

      {mode === 'chat' ? <ChatView entries={chat.entries} busy={chat.busy} /> : null}

      {mode === 'settings' ? (
        <SettingsView
          prefs={prefs}
          setPref={update}
          onProviderChanged={checkModel}
        />
      ) : null}

      {/* Onay tepsisi her kipte görünür: ajan hangi ekranda olursanız
          olun bir şey isteyebilir ve istek görünmezse hiç çalışmaz. */}
      <ApprovalTray
        sessionId={chat.sessionId}
        onResolved={() => setDataVersion((value) => value + 1)}
      />

      <DeskOrb
        phase={chat.phase}
        size={orbGeometry.size}
        left={orbGeometry.left}
        top={orbGeometry.top}
        animated={prefs.orbAnimated}
        onClick={() => inputRef.current?.focus()}
      />

      {/* model yoksa: kabuğun içinde, tek bir adım */}
      {modelMissing && mode === 'home' ? (
        <div
          style={{
            position: 'absolute', left: '50%', bottom: 210, zIndex: 70,
            transform: 'translateX(-50%)', width: 'min(560px,72vw)', padding: '18px 22px',
            borderRadius: 16, border: '1px solid rgba(255,255,255,.10)',
            background: 'rgba(16,19,27,.86)', backdropFilter: 'blur(26px)',
            textAlign: 'center',
          }}
        >
          <div style={{ fontSize: 14, color: C.textBright }}>Son bir adım: bir model bağlayın</div>
          <div style={{ marginTop: 8, fontSize: 12.5, lineHeight: 1.6, color: C.dim }}>
            Jarvis'in konuşabilmesi için bir sağlayıcı ve model gerekiyor.
          </div>
          <button
            onClick={() => setMode('settings')}
            style={{
              marginTop: 14, padding: '9px 18px', borderRadius: 10, cursor: 'pointer',
              border: '1px solid rgba(170,150,255,.45)', background: 'rgba(124,92,255,.28)',
              color: '#dfe0ff', fontSize: 12.5, fontFamily: 'inherit',
            }}
          >
            Ayarları aç
          </button>
        </div>
      ) : null}

      {/* giriş çubuğu */}
      <div
        style={{
          position: 'absolute', left: '50%', bottom: mode === 'home' ? 84 : 40, zIndex: 80,
          width: 'min(700px,64vw)', transform: 'translateX(-50%)', transition: 'bottom .5s ease',
        }}
      >
        <div
          style={{
            height: 60, borderRadius: 32, border: '1px solid rgba(255,255,255,.13)',
            background: 'rgba(255,255,255,.055)', backdropFilter: 'blur(26px)',
            boxShadow: '0 24px 60px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.10)',
            display: 'flex', alignItems: 'center', gap: 12, padding: '0 10px 0 20px',
          }}
        >
          <button
            onClick={() => setMode('settings')}
            aria-label="Ayarlar"
            style={{ background: 'transparent', border: 'none', fontSize: 21, fontWeight: 200, color: 'rgba(232,236,244,.62)', cursor: 'pointer', padding: 0 }}
          >
            +
          </button>

          <input
            ref={inputRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') void send(); }}
            onFocus={() => { if (chat.phase === 'idle') chat.setPhase('listening'); }}
            onBlur={() => { if (chat.phase === 'listening') chat.setPhase('idle'); }}
            placeholder={chat.busy ? 'Yanıt bekleniyor...' : 'Bir şey yazın...'}
            disabled={chat.busy}
            style={{
              flex: 1, height: '100%', border: 'none', outline: 'none', background: 'transparent',
              fontSize: 15, color: C.textBright, fontFamily: 'inherit',
            }}
          />

          {dictation.supported ? (
            <button
              // Bas-konuş: düğme BASILI tutulduğu sürece dinler. Aç/kapa
              // olsaydı, kapatmayı unutan kullanıcının mikrofonu açık
              // kalırdı ve bunu gösteren tek işaret küçük bir simge olurdu.
              onPointerDown={dictation.start}
              onPointerUp={dictation.stop}
              onPointerLeave={dictation.stop}
              title={dictation.error ?? 'Basılı tutup konuşun'}
              aria-label="Bas-konuş"
              style={{
                width: 36, height: 36, flex: 'none', borderRadius: '50%', cursor: 'pointer',
                border: `1px solid ${dictation.listening ? 'rgba(120,190,255,.55)' : 'rgba(255,255,255,.14)'}`,
                background: dictation.listening ? 'rgba(120,190,255,.22)' : 'rgba(255,255,255,.05)',
                color: 'rgba(232,236,244,.80)', fontSize: 14,
              }}
            >
              ●
            </button>
          ) : null}

          <button
            onClick={() => void send()}
            disabled={chat.busy || !draft.trim()}
            aria-label="Gönder"
            style={{
              width: 40, height: 40, flex: 'none', borderRadius: '50%',
              cursor: chat.busy || !draft.trim() ? 'default' : 'pointer',
              border: '1px solid rgba(255,255,255,.14)', background: 'rgba(255,255,255,.07)',
              color: 'rgba(232,236,244,.80)', fontSize: 15,
              opacity: chat.busy || !draft.trim() ? 0.45 : 1,
            }}
          >
            ↑
          </button>
        </div>

        <div style={{ marginTop: 14, display: 'flex', justifyContent: 'center', gap: 10 }}>
          {MODES.map((item) => (
            <button
              key={item.id}
              onClick={() => setMode(item.id)}
              style={{
                padding: '6px 15px', borderRadius: 20, fontSize: 11.5, letterSpacing: '.12em',
                cursor: 'pointer', fontFamily: 'inherit',
                border: `1px solid ${mode === item.id ? 'rgba(255,255,255,.16)' : 'rgba(255,255,255,.07)'}`,
                background: mode === item.id ? 'rgba(255,255,255,.10)' : 'transparent',
                color: mode === item.id ? C.textBright : 'rgba(232,236,244,.45)',
              }}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div style={{ marginTop: 10, textAlign: 'center', fontSize: 10, letterSpacing: '.18em', color: 'rgba(232,236,244,.22)' }}>
          {PHASE_LABEL[chat.phase]}
        </div>
      </div>
    </div>
  );
};

const MenuRow = ({
  label,
  value,
  onClick,
}: {
  label: string;
  value: string;
  onClick: () => void;
}) => (
  <button
    onClick={onClick}
    style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%',
      padding: '9px 8px', borderRadius: 10, border: 'none', background: 'transparent',
      cursor: 'pointer', fontFamily: 'inherit',
    }}
  >
    <span style={{ fontSize: 13.5, color: 'rgba(232,236,244,.82)' }}>{label}</span>
    <span style={{ fontSize: 11, letterSpacing: '.1em', color: 'rgba(232,236,244,.45)' }}>{value}</span>
  </button>
);

const pad = (value: number) => (value < 10 ? `0${value}` : String(value));
