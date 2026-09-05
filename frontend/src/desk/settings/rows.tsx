import type { ReactNode } from 'react';
import { C, FIELD, GLASS, LABEL } from '../theme';

/**
 * Kontrol merkezinin satır türleri.
 *
 * Tasarım her satırı aynı iskelette gösteriyor: solda ad ve açıklama,
 * sağda denetim. Bunun tek bir bileşende toplanması, otuz küsur ayarın
 * hizalarının birbirinden kaymasını engelliyor — her bölüm kendi
 * satırını çizseydi, aralarındaki 1-2 piksellik farklar birikirdi.
 *
 * Satırların hiçbiri kendi verisini OKUMAZ. Değer ve geri çağrı
 * dışarıdan gelir; aksi hâlde "hangi ayar gerçekten sunucuya yazılıyor"
 * sorusunun cevabı bileşenlerin içine dağılırdı.
 */

export const Group = ({ title, children }: { title: string; children: ReactNode }) => (
  <div style={{ ...GLASS, marginTop: 26, overflow: 'hidden' }}>
    <div style={{ ...LABEL, padding: '14px 22px', borderBottom: '1px solid rgba(255,255,255,.055)' }}>
      {title}
    </div>
    {children}
  </div>
);

export const Row = ({
  label,
  desc,
  children,
}: {
  label: string;
  desc?: string;
  children?: ReactNode;
}) => (
  <div
    style={{
      display: 'flex', alignItems: 'center', gap: 24, padding: '15px 22px',
      borderTop: '1px solid rgba(255,255,255,.035)',
    }}
  >
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 13.5, color: 'rgba(232,236,244,.88)' }}>{label}</div>
      {desc ? (
        <div style={{ marginTop: 4, fontSize: 11.5, lineHeight: 1.5, color: 'rgba(232,236,244,.38)' }}>
          {desc}
        </div>
      ) : null}
    </div>
    <div style={{ flex: 'none', display: 'flex', alignItems: 'center', gap: 12 }}>
      {children}
    </div>
  </div>
);

export const Toggle = ({
  on,
  onChange,
  disabled,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) => (
  <button
    role="switch"
    aria-checked={on}
    disabled={disabled}
    onClick={() => onChange(!on)}
    style={{
      width: 40, height: 22, borderRadius: 12, padding: 2, border: 'none',
      cursor: disabled ? 'default' : 'pointer',
      opacity: disabled ? 0.4 : 1,
      transition: 'background .2s',
      background: on ? 'rgba(110,150,255,.85)' : 'rgba(255,255,255,.12)',
    }}
  >
    <span
      style={{
        display: 'block', width: 18, height: 18, borderRadius: '50%', background: '#fff',
        boxShadow: '0 1px 3px rgba(0,0,0,.45)',
        transition: 'transform .2s cubic-bezier(.4,0,.2,1)',
        transform: on ? 'translateX(18px)' : 'translateX(0)',
      }}
    />
  </button>
);

export const Select = ({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (next: string) => void;
}) => (
  <select
    value={value}
    onChange={(event) => onChange(event.target.value)}
    style={{ ...FIELD, minWidth: 200, background: 'rgba(20,24,32,.92)', cursor: 'pointer' }}
  >
    {options.map((option) => (
      <option key={option.value} value={option.value}>{option.label}</option>
    ))}
  </select>
);

export const Text = ({
  value,
  onChange,
  placeholder,
  width = 250,
  type = 'text',
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  width?: number;
  type?: 'text' | 'password';
}) => (
  <input
    type={type}
    value={value}
    onChange={(event) => onChange(event.target.value)}
    placeholder={placeholder}
    autoComplete="off"
    style={{ ...FIELD, width }}
  />
);

export const Slider = ({
  value,
  min,
  max,
  step,
  readout,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  readout: string;
  onChange: (next: number) => void;
}) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(event) => onChange(Number(event.target.value))}
      style={{ width: 190, accentColor: '#7fa8ff', background: 'transparent' }}
    />
    <span style={{ minWidth: 52, textAlign: 'right', fontSize: 12, fontVariantNumeric: 'tabular-nums', color: 'rgba(232,236,244,.62)' }}>
      {readout}
    </span>
  </div>
);

export const Stat = ({ value }: { value: string }) => (
  <div style={{ fontSize: 20, fontWeight: 300, fontVariantNumeric: 'tabular-nums', color: C.textBright }}>
    {value}
  </div>
);

export type StatusTone = 'on' | 'off' | 'warn';

const TONE: Record<StatusTone, string> = {
  on: '#5fd39a',
  off: 'rgba(232,236,244,.35)',
  warn: '#e0b13f',
};

export const Status = ({ text, tone }: { text: string; tone: StatusTone }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
    <span style={{ width: 7, height: 7, borderRadius: '50%', background: TONE[tone] }} />
    <span style={{ fontSize: 12.5, color: TONE[tone] }}>{text}</span>
  </div>
);

export const Buttons = ({
  items,
}: {
  items: { label: string; onClick: () => void; danger?: boolean }[];
}) => (
  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'flex-end' }}>
    {items.map((item) => (
      <button
        key={item.label}
        onClick={item.onClick}
        style={{
          padding: '8px 14px', borderRadius: 9, cursor: 'pointer', whiteSpace: 'nowrap',
          fontSize: 12, fontFamily: 'inherit',
          border: `1px solid ${item.danger ? 'rgba(241,121,143,.35)' : 'rgba(255,255,255,.11)'}`,
          background: item.danger ? 'transparent' : 'rgba(255,255,255,.05)',
          color: item.danger ? '#f1798f' : 'rgba(232,236,244,.82)',
        }}
      >
        {item.label}
      </button>
    ))}
  </div>
);

/** Bölüm başlığı ve açıklaması. */
export const PanelHead = ({ title, sub }: { title: string; sub: string }) => (
  <>
    <div style={{ fontSize: 31, fontWeight: 300, letterSpacing: '-.01em', color: C.textBright }}>
      {title}
    </div>
    <div style={{ marginTop: 9, fontSize: 13.5, lineHeight: 1.6, color: 'rgba(232,236,244,.45)' }}>
      {sub}
    </div>
  </>
);

/**
 * Henüz backend'i olmayan bölümler için dürüst açıklama.
 *
 * Bu bölümlerde çalışmayan anahtarlar göstermek daha "tamamlanmış"
 * görünürdü ama kullanıcı bir ayarı açıp hiçbir şeyin değişmediğini
 * gördüğünde, çalışan ayarlara da güvenmeyi bırakırdı.
 */
export const NotWired = ({ what, needs }: { what: string; needs: string }) => (
  <div style={{ ...GLASS, marginTop: 26, padding: '22px 24px' }}>
    <div style={{ fontSize: 13.5, color: 'rgba(232,236,244,.80)' }}>
      {what} henüz bağlı değil.
    </div>
    <div style={{ marginTop: 8, fontSize: 12.5, lineHeight: 1.65, color: 'rgba(232,236,244,.45)' }}>
      {needs}
    </div>
    <div style={{ marginTop: 14, fontSize: 11.5, color: 'rgba(232,236,244,.32)' }}>
      Çalışmayan bir anahtar göstermek yerine burada boş bırakıldı: açıp da
      hiçbir şeyin değişmediğini görmek, çalışan ayarlara olan güveni de
      götürürdü.
    </div>
  </div>
);
