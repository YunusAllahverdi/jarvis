import { useCallback, useEffect, useState } from 'react';

/**
 * Yalnızca bu tarayıcıyı ilgilendiren tercihler.
 *
 * Sunucuya YAZILMAZLAR ve bu bilinçli: masa ızgarası, küre boyutu ve
 * animasyon, bakılan CİHAZIN tercihidir. Sunucuda tutulsalardı, PC'de
 * kapatılan animasyon tablette de kapanırdı — oysa tablette pil ömrü,
 * PC'de akıcılık önemli olabilir.
 *
 * `localStorage` erişimi bile bazı bağlamlarda (gizli sekme, site verisi
 * engelli) istisna fırlatır; bu yüzden her okuma ve yazma sarmalanır ve
 * başarısızlık sessizce varsayılana düşer.
 */

const STORAGE_KEY = 'jarvis.desk.prefs';

export interface DeskPrefs {
  /** Masa modundaki zemin ızgarası. */
  grid: boolean;
  /** Küre animasyonu; kapalıyken küre donar ama görünür kalır. */
  orbAnimated: boolean;
  /** Ana ekrandaki kürenin çapı (piksel). */
  orbSize: number;
  /** Sohbet cevaplarını sesli okusun mu? */
  voice: boolean;
}

const DEFAULTS: DeskPrefs = {
  grid: true,
  orbAnimated: true,
  orbSize: 250,
  voice: false,
};

function read(): DeskPrefs {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<DeskPrefs>;
    return {
      grid: typeof parsed.grid === 'boolean' ? parsed.grid : DEFAULTS.grid,
      orbAnimated:
        typeof parsed.orbAnimated === 'boolean' ? parsed.orbAnimated : DEFAULTS.orbAnimated,
      // Sınırlar burada da uygulanır: depodaki değer elle düzenlenmiş
      // olabilir ve ekranı kaplayan bir küre arayüzü kullanılamaz yapardı.
      orbSize: clamp(Number(parsed.orbSize) || DEFAULTS.orbSize, 120, 360),
      voice: typeof parsed.voice === 'boolean' ? parsed.voice : DEFAULTS.voice,
    };
  } catch {
    return DEFAULTS;
  }
}

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

export function useDeskPrefs() {
  const [prefs, setPrefs] = useState<DeskPrefs>(DEFAULTS);

  // İlk okuma efekt içinde: sunucuda render edilen bir ağaçta
  // `window` yoktur ve ilk render'da okumak orada patlardı.
  useEffect(() => { setPrefs(read()); }, []);

  const update = useCallback(<K extends keyof DeskPrefs>(key: K, value: DeskPrefs[K]) => {
    setPrefs((current) => {
      const next = { ...current, [key]: value };
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // Yazılamaması bir hata değildir; tercih yalnızca kalıcı olmaz.
      }
      return next;
    });
  }, []);

  return { prefs, update };
}
