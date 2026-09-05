import { useState, type ComponentType } from 'react';
import { C } from '../theme';
import type { DeskPrefs } from '../useDeskPrefs';
import {
  AboutSection, AppearanceSection, AutomationSection, ConversationSection,
  IntegrationsSection, MemorySection, OverviewSection, ProviderSection,
  SecuritySection, ToolsSection, VoiceSection, type SectionProps,
} from './sections';

/**
 * Kontrol merkezi: solda gezinti, sağda bölüm.
 *
 * Kayıt tablosu (`SECTIONS`) tek doğruluk kaynağıdır: gezintideki bir
 * madde ile onu gösteren bileşen aynı satırda tanımlanır. İkisi ayrı
 * listelerde durursa, bir bölüm eklendiğinde gezintiye konması unutulur
 * ve erişilemez bir sayfa olarak kalırdı.
 */

type SectionId =
  | 'overview' | 'providers' | 'appearance' | 'voice'
  | 'memory' | 'conversation' | 'tools' | 'security'
  | 'integrations' | 'automation' | 'about';

interface SectionDef {
  id: SectionId;
  label: string;
  Component: ComponentType<SectionProps>;
}

const NAV: { title: string; items: SectionDef[] }[] = [
  {
    title: 'GENEL',
    items: [
      { id: 'overview', label: 'Genel bakış', Component: OverviewSection },
      { id: 'appearance', label: 'Görünüm', Component: AppearanceSection },
      { id: 'voice', label: 'Ses', Component: VoiceSection },
    ],
  },
  {
    title: 'YAPAY ZEKÂ',
    items: [
      { id: 'providers', label: 'Sağlayıcı', Component: ProviderSection },
      { id: 'memory', label: 'Bellek', Component: MemorySection },
      { id: 'conversation', label: 'Konuşma', Component: ConversationSection },
    ],
  },
  {
    title: 'GÜVENLİK',
    items: [
      { id: 'tools', label: 'İzinler', Component: ToolsSection },
      { id: 'security', label: 'Erişim', Component: SecuritySection },
    ],
  },
  {
    title: 'SİSTEM',
    items: [
      { id: 'integrations', label: 'Entegrasyonlar', Component: IntegrationsSection },
      { id: 'automation', label: 'Otomasyon', Component: AutomationSection },
      { id: 'about', label: 'Hakkında', Component: AboutSection },
    ],
  },
];

const ALL = NAV.flatMap((group) => group.items);

interface Props {
  prefs: DeskPrefs;
  setPref: <K extends keyof DeskPrefs>(key: K, value: DeskPrefs[K]) => void;
  onProviderChanged: () => void;
}

export const SettingsView = ({ prefs, setPref, onProviderChanged }: Props) => {
  const [current, setCurrent] = useState<SectionId>('overview');
  const [toast, setToast] = useState<string | null>(null);

  const flash = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast((value) => (value === message ? null : value)), 2600);
  };

  const active = ALL.find((section) => section.id === current) ?? ALL[0];
  const Section = active.Component;

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 45, display: 'flex' }}>
      <nav
        style={{
          width: 252, flex: 'none', height: '100%', padding: '112px 0 32px',
          borderRight: `1px solid ${C.lineSoft}`, background: 'rgba(9,11,16,.62)',
          backdropFilter: 'blur(28px)', overflow: 'auto',
        }}
      >
        {NAV.map((group) => (
          <div key={group.title}>
            <div style={{ padding: '16px 24px 7px', fontSize: 9.5, letterSpacing: '.26em', color: C.faint }}>
              {group.title}
            </div>
            {group.items.map((item) => (
              <button
                key={item.id}
                onClick={() => setCurrent(item.id)}
                style={{
                  display: 'block', width: 'calc(100% - 24px)', textAlign: 'left',
                  margin: '1px 12px', padding: '8px 12px', borderRadius: 9,
                  border: 'none', cursor: 'pointer', fontSize: 13, fontFamily: 'inherit',
                  background: current === item.id ? 'rgba(255,255,255,.085)' : 'transparent',
                  color: current === item.id ? C.textBright : C.dim,
                }}
              >
                {item.label}
              </button>
            ))}
          </div>
        ))}
      </nav>

      <div style={{ flex: 1, minWidth: 0, height: '100%', padding: '104px 52px 170px', overflow: 'auto' }}>
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          <Section
            prefs={prefs}
            setPref={setPref}
            toast={flash}
            onProviderChanged={onProviderChanged}
          />
        </div>
      </div>

      {toast ? (
        <div
          role="status"
          style={{
            position: 'absolute', left: '50%', bottom: 132, zIndex: 130,
            transform: 'translateX(-50%)', padding: '11px 20px', borderRadius: 22,
            border: '1px solid rgba(255,255,255,.12)', background: 'rgba(18,22,30,.90)',
            backdropFilter: 'blur(22px)', fontSize: 12.5, color: 'rgba(232,236,244,.86)',
            animation: 'deskFadeUp .2s ease both',
          }}
        >
          {toast}
        </div>
      ) : null}
    </div>
  );
};
