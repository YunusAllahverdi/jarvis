/**
 * Kabuğun statik içeriği: gezinme, temalar, kısayollar ve öneriler.
 *
 * Bu değerler tasarım artboard'undan geldi ve şu an sabit. Backend'de
 * karşılıkları oluştukça (aktivite akışı, öneri üretimi, gerçek sistem
 * ölçümleri) buradan API'ye taşınmaları gerekiyor.
 */

export type ThemeName = 'Gezegen' | 'Sakura' | 'Şehir';

export interface Theme {
  /** Shader'daki uTheme uniform'una geçen kimlik. */
  id: number;
  a: string;
  b: string;
  bg: string;
  sub: string;
}

export const THEMES: Record<ThemeName, Theme> = {
  Gezegen: { id: 0, a: '#3f7bff', b: '#a15cff', bg: '#2b1c4d', sub: 'Mor nebula, sessiz su' },
  Sakura: { id: 1, a: '#ff7fa8', b: '#ffc07a', bg: '#4a2436', sub: 'Fuji, sakura, rüzgâr' },
  Şehir: { id: 2, a: '#2fe0ff', b: '#ff4d9d', bg: '#12294d', sub: 'Neon siluet, ıslak asfalt' },
};

export const THEME_NAMES = Object.keys(THEMES) as ThemeName[];

export interface NavItem {
  label: string;
  path: string;
  badge?: string;
}

export const NAV: NavItem[] = [
  { label: 'Sohbet', path: 'M4.5 6.5a2.5 2.5 0 012.5-2.5h10a2.5 2.5 0 012.5 2.5v6a2.5 2.5 0 01-2.5 2.5H9l-4.5 3.5z' },
  { label: 'Bellek', path: 'M4.5 7.5a3 3 0 013-3h9a3 3 0 013 3v9a3 3 0 01-3 3h-9a3 3 0 01-3-3zM9 9.5h6' },
  { label: 'Deneyimler', path: 'M12 3.8l7 3.4v6.2c0 3.2-3 5.4-7 6.8-4-1.4-7-3.6-7-6.8V7.2z' },
  { label: 'Öğrendiklerim', path: 'M12 3.6l7.2 8.4L12 20.4 4.8 12z' },
  { label: 'Benim Modelim', path: 'M12 4.2a3.4 3.4 0 110 6.8 3.4 3.4 0 010-6.8zM5 20c0-3.4 3.1-5.6 7-5.6s7 2.2 7 5.6' },
  { label: 'Sistem', path: 'M12 8.4a3.6 3.6 0 110 7.2 3.6 3.6 0 010-7.2zM12 3.2v3M12 18v2.8M4.4 12h3M16.6 12h3' },
  // Rozet kaldırıldı: kodlama döngüsü artık gerçek bir ekran açıyor.
  { label: 'Ajanlar', path: 'M8.6 5a2.9 2.9 0 110 5.8 2.9 2.9 0 010-5.8zM16.4 7a2.4 2.4 0 110 4.8 2.4 2.4 0 010-4.8zM2.8 19.6c0-3 2.6-4.9 5.8-4.9s5.8 1.9 5.8 4.9M15.6 15c3 .2 5.6 1.9 5.6 4.6' },
];

export interface IconItem {
  label: string;
  path: string;
}

export interface ShortcutItem extends IconItem {
  /** Varsa bu gezinme ekranını açar. */
  section?: string;
  /** Ekranı yoksa sohbet girişine yazılacak metin. */
  prompt?: string;
}

/**
 * Kısayollar.
 *
 * Notlar ve Takvim henüz BACKEND'DE YOK. Onları da bir ekran açıyormuş gibi
 * göstermek yerine sohbete bir istek yazdırıyorlar: Jarvis o isteği elindeki
 * araçlarla karşılayabildiği kadar karşılar. Var olmayan bir ekranı açan bir
 * düğme, kırık bir düğmedir.
 */
export const SHORTCUTS: ShortcutItem[] = [
  { label: 'Bellek', path: 'M7 4.5h7l4 4v11H7zM14 4.5V9h4', section: 'Bellek' },
  { label: 'Deneyim', path: 'M5 7h14v12H5zM8 4.5V8M16 4.5V8M5 11h14', section: 'Deneyimler' },
  {
    label: 'Ajan',
    path: 'M5 6.5h14v13H5zM8.5 12.5l2.5 2.5 4.5-5',
    section: 'Ajanlar',
  },
  {
    label: 'Sistem',
    path: 'M4.5 11L12 4.8 19.5 11v8.2h-15z',
    section: 'Sistem',
  },
];

export const SUGGESTIONS: IconItem[] = [
  { label: 'Günün planını gözden geçir', path: 'M12 4.5l7 3.2v6c0 3-3 5.2-7 6.5-4-1.3-7-3.5-7-6.5v-6z' },
  { label: 'Hatırlatıcıları kontrol et', path: 'M6 6.5h12v12H6zM9.5 12.5l2 2 4-4.5' },
  { label: 'Yeni bilgilerimi göster', path: 'M12 8.6a3.4 3.4 0 110 6.8 3.4 3.4 0 010-6.8zM12 3.6v2.6M12 17.8v2.6M4.6 12h2.6M16.8 12h2.6' },
];

export const MODE_LABELS: Record<string, string> = {
  idle: 'Hazır, sizi bekliyorum',
  listening: 'Sizi dinliyorum...',
  speaking: 'Konuşuyorum...',
  thinking: 'Düşünüyorum...',
  error: 'Bağlantı kurulamadı',
};
