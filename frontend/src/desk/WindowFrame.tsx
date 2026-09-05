import type { ReactNode } from 'react';
import { C, TRAFFIC } from './theme';
import type { WindowView } from './useWindows';

/**
 * Pencere kabuğu: başlık çubuğu, trafik ışıkları ve cam gövde.
 *
 * Her pencerenin kendi kabuğunu çizmesi altı ayrı sürükleme hatası
 * demek olurdu; kabuk tek yerdedir ve pencereler yalnızca içeriklerini
 * verir.
 */

interface Props {
  win: WindowView;
  title: string;
  /** Başlık çubuğunun sağına konan küçük denetimler (arama, sekme...). */
  toolbar?: ReactNode;
  children: ReactNode;
  /** Cam gövdenin rengi; tasarımda pencereye göre biraz değişiyor. */
  background?: string;
}

export const WindowFrame = ({
  win,
  title,
  toolbar,
  children,
  background = C.window,
}: Props) => {
  if (!win.visible) return null;

  return (
    <div
      onPointerDown={win.onFocus}
      style={{
        position: 'absolute',
        ...win.style,
        borderRadius: 14,
        border: '1px solid rgba(255,255,255,.11)',
        background,
        backdropFilter: 'blur(22px)',
        boxShadow: '0 40px 90px rgba(0,0,0,.62)',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        transition:
          'left .34s cubic-bezier(.32,.72,0,1), top .34s cubic-bezier(.32,.72,0,1), width .34s cubic-bezier(.32,.72,0,1), height .34s cubic-bezier(.32,.72,0,1)',
      }}
    >
      <div
        onPointerDown={win.onPointerDown}
        onDoubleClick={win.onMaximize}
        style={{
          height: 38,
          flex: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: 9,
          padding: '0 12px',
          borderBottom: `1px solid ${C.lineSoft}`,
          cursor: 'grab',
          userSelect: 'none',
        }}
      >
        {/* Işıklar sürüklemeyi başlatmamalı: tıklamak isteyen kullanıcı
            pencereyi bir piksel oynatınca düğmeyi ıskalardı. */}
        <div onPointerDown={(event) => event.stopPropagation()} style={{ display: 'flex', gap: 6 }}>
          <Light color={TRAFFIC.close} title="Kapat" onClick={win.onClose} />
          <Light color={TRAFFIC.min} title="Küçült" onClick={win.onMinimize} />
          <Light color={TRAFFIC.max} title="Tam ekran" onClick={win.onMaximize} />
        </div>
        <div style={{ marginLeft: 8, fontSize: 12.5, color: 'rgba(232,236,244,.72)' }}>
          {title}
        </div>
        {toolbar ? (
          <div
            onPointerDown={(event) => event.stopPropagation()}
            style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}
          >
            {toolbar}
          </div>
        ) : null}
      </div>
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>{children}</div>
    </div>
  );
};

const Light = ({
  color,
  title,
  onClick,
}: {
  color: string;
  title: string;
  onClick: (event: React.MouseEvent) => void;
}) => (
  <button
    onClick={onClick}
    title={title}
    aria-label={title}
    style={{
      width: 10,
      height: 10,
      padding: 0,
      borderRadius: '50%',
      border: 'none',
      background: color,
      cursor: 'pointer',
    }}
  />
);

/** Pencere içeriğinin boş/hata/yükleniyor hâlleri için ortak yüzey. */
export const WindowNotice = ({ children }: { children: ReactNode }) => (
  <div
    style={{
      flex: 1,
      display: 'grid',
      placeItems: 'center',
      padding: 24,
      textAlign: 'center',
      fontSize: 12.5,
      lineHeight: 1.6,
      color: C.dimmer,
    }}
  >
    <div style={{ maxWidth: 280 }}>{children}</div>
  </div>
);
