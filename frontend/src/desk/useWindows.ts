import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Masadaki pencerelerin durumu.
 *
 * Tek bir kanca içinde toplanmasının sebebi z-sırası: hangi pencerenin
 * üstte olduğu, pencerelerin ORTAK bir bilgisidir. Her pencere kendi
 * z-index'ini tutsaydı, "tıklanan öne gelsin" kuralı hiçbir yerde
 * yazılamazdı — kimse diğerlerinin sayısını bilmezdi.
 *
 * Konum sürükleme farkı olarak tutulur (`offset`), mutlak koordinat
 * olarak değil. Böylece tasarımın verdiği yerleşim tek doğruluk kaynağı
 * kalır ve "masayı sıfırla" yalnızca farkları silmek olur.
 */

export type WindowKey =
  | 'notlar' | 'web' | 'hesap' | 'dosyalar' | 'gorevler' | 'kodlama' | 'quote';

export interface WindowBox {
  l: number;
  t: number;
  w: number;
  h: number;
  label: string;
}

/** Tasarımdaki açılış yerleşimi. */
export const WINDOWS: Record<WindowKey, WindowBox> = {
  notlar: { l: 150, t: 180, w: 568, h: 420, label: 'Notlar' },
  web: { l: 492, t: 112, w: 626, h: 452, label: 'Web' },
  hesap: { l: 1046, t: 92, w: 326, h: 378, label: 'Hesap Makinesi' },
  dosyalar: { l: 496, t: 562, w: 394, h: 300, label: 'Dosyalar' },
  gorevler: { l: 926, t: 552, w: 330, h: 314, label: 'Görevler' },
  // Tasarımda yoktu; kodlama döngüsü arayüzsüz kalmasın diye eklendi.
  // Kapalı açılır: masayı ilk açan kişi için en az kullanılacak pencere.
  kodlama: { l: 150, t: 620, w: 520, h: 300, label: 'Kodlama' },
  quote: { l: 1288, t: 434, w: 250, h: 266, label: 'Not kartı' },
};

const MAXIMIZED = { l: 96, t: 96, w: 1400, h: 756 };

const WINDOW_KEYS = Object.keys(WINDOWS) as WindowKey[];

type Anim = 'open' | 'close' | 'min';

interface Drag {
  key: WindowKey;
  startX: number;
  startY: number;
  originX: number;
  originY: number;
}

export interface WindowView {
  key: WindowKey;
  label: string;
  /** DOM'da bulunmalı mı — kapanma animasyonu bitene kadar kalır. */
  visible: boolean;
  style: {
    left: string;
    top: string;
    width: string;
    height: string;
    transform: string;
    zIndex: number;
    animation: string;
  };
  onPointerDown: (event: React.PointerEvent) => void;
  onFocus: () => void;
  onClose: (event?: React.MouseEvent) => void;
  onMinimize: (event?: React.MouseEvent) => void;
  onMaximize: (event?: React.MouseEvent) => void;
}

export interface WindowManager {
  view: (key: WindowKey) => WindowView;
  /** Kapalı ya da küçültülmüş pencereler; alt şeritte rozet olarak çıkar. */
  hidden: { key: WindowKey; label: string; restore: () => void }[];
  open: (key: WindowKey) => void;
  reset: () => void;
}

export function useWindows(): WindowManager {
  // Kodlama penceresi KAPALI açılır: masanın ilk görünümü tasarımdaki
  // gibi kalsın, döngüye ihtiyaç duyan onu alt şeritten açsın.
  const initialOpen = () =>
    Object.fromEntries(WINDOW_KEYS.map((key) => [key, key !== 'kodlama']));

  const [openState, setOpenState] = useState<Record<string, boolean>>(initialOpen);
  const [minimized, setMinimized] = useState<Record<string, boolean>>({});
  const [maximized, setMaximized] = useState<Record<string, boolean>>({});
  const [anim, setAnim] = useState<Record<string, Anim | undefined>>({});
  const [offset, setOffset] = useState<Record<string, { x: number; y: number }>>({});
  const [z, setZ] = useState<Record<string, number>>({
    notlar: 5, web: 4, hesap: 6, dosyalar: 3, gorevler: 3, kodlama: 3, quote: 2,
  });
  const topRef = useRef(6);
  const dragRef = useRef<Drag | null>(null);
  const timers = useRef<Record<string, number>>({});

  useEffect(() => {
    const captured = timers.current;
    return () => Object.values(captured).forEach((id) => window.clearTimeout(id));
  }, []);

  /* ── sürükleme ────────────────────────────────────────────
   *
   * Dinleyiciler `window` üzerindedir, pencerenin kendisinde değil:
   * imleç hızlı hareket ettiğinde pencerenin dışına çıkar ve elemanın
   * kendi `pointermove`'u artık tetiklenmezdi — pencere imlecin altından
   * kayıp giderdi.
   */
  useEffect(() => {
    const move = (event: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      setOffset((current) => ({
        ...current,
        [drag.key]: {
          x: drag.originX + event.clientX - drag.startX,
          y: drag.originY + event.clientY - drag.startY,
        },
      }));
    };
    const up = () => { dragRef.current = null; };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
    };
  }, []);

  const bringToFront = useCallback((key: WindowKey) => {
    topRef.current += 1;
    const next = topRef.current;
    setZ((current) => ({ ...current, [key]: next }));
  }, []);

  /** Animasyonu başlatır ve BİTİNCE asıl durumu değiştirir. */
  const animate = useCallback(
    (key: WindowKey, kind: Anim, ms: number, done?: () => void) => {
      setAnim((current) => ({ ...current, [key]: kind }));
      window.clearTimeout(timers.current[key]);
      timers.current[key] = window.setTimeout(() => {
        setAnim((current) => ({ ...current, [key]: undefined }));
        done?.();
      }, ms);
    },
    [],
  );

  const view = useCallback(
    (key: WindowKey): WindowView => {
      const box = maximized[key] ? MAXIMIZED : WINDOWS[key];
      const shift = offset[key];
      const animation =
        anim[key] === 'close'
          ? 'deskWinClose .23s cubic-bezier(.4,0,1,1) forwards'
          : anim[key] === 'min'
            ? 'deskWinMin .25s cubic-bezier(.4,0,1,1) forwards'
            : anim[key] === 'open'
              ? 'deskWinOpen .28s cubic-bezier(.16,.84,.44,1)'
              : 'none';

      return {
        key,
        label: WINDOWS[key].label,
        visible:
          (openState[key] && !minimized[key]) ||
          anim[key] === 'close' ||
          anim[key] === 'min',
        style: {
          left: `${box.l}px`,
          top: `${box.t}px`,
          width: `${box.w}px`,
          height: `${box.h}px`,
          transform:
            shift && !maximized[key] ? `translate(${shift.x}px,${shift.y}px)` : 'none',
          zIndex: z[key] ?? 1,
          animation,
        },
        onPointerDown: (event) => {
          if (event.button !== 0 || maximized[key]) return;
          event.preventDefault();
          const origin = offset[key] ?? { x: 0, y: 0 };
          dragRef.current = {
            key,
            startX: event.clientX,
            startY: event.clientY,
            originX: origin.x,
            originY: origin.y,
          };
          bringToFront(key);
        },
        onFocus: () => bringToFront(key),
        onClose: (event) => {
          event?.stopPropagation();
          animate(key, 'close', 230, () => {
            setOpenState((current) => ({ ...current, [key]: false }));
            setMaximized((current) => ({ ...current, [key]: false }));
          });
        },
        onMinimize: (event) => {
          event?.stopPropagation();
          animate(key, 'min', 250, () =>
            setMinimized((current) => ({ ...current, [key]: true })),
          );
        },
        onMaximize: (event) => {
          event?.stopPropagation();
          setMaximized((current) => ({ ...current, [key]: !current[key] }));
          // Tam ekrana geçerken sürükleme farkı silinir; kalsaydı pencere
          // ekranın ortasına değil, taşındığı kadar kaymış bir yere açılırdı.
          setOffset((current) => ({ ...current, [key]: { x: 0, y: 0 } }));
          bringToFront(key);
        },
      };
    },
    [openState, minimized, maximized, anim, offset, z, animate, bringToFront],
  );

  const open = useCallback(
    (key: WindowKey) => {
      setOpenState((current) => ({ ...current, [key]: true }));
      setMinimized((current) => ({ ...current, [key]: false }));
      bringToFront(key);
      animate(key, 'open', 300);
    },
    [animate, bringToFront],
  );

  const hidden = WINDOW_KEYS.filter((key) => !openState[key] || minimized[key]).map(
    (key) => ({ key, label: WINDOWS[key].label, restore: () => open(key) }),
  );

  const reset = useCallback(() => {
    setOffset({});
    setMaximized({});
    setMinimized({});
    setOpenState(initialOpen());
  }, []);

  return { view, hidden, open, reset };
}
