/**
 * Tasarımın renk ve yüzey sözlüğü.
 *
 * Tasarım dosyası her rengi her düğümde satır içi yazıyordu; bu kabul
 * edilebilir bir prototip alışkanlığıdır ama üründe bir cam panelin
 * saydamlığını değiştirmek onlarca dosyada arama yapmak demek olurdu.
 * Burada tek tanım noktası var: pencereler, paneller ve kartlar aynı
 * yüzeyi paylaşır, dolayısıyla aynı yerden değişir.
 *
 * Değerler tasarımdan BİREBİR alındı; "biraz daha iyi" yapmak için
 * değiştirilmedi. Tasarımın tutarlılığı tek tek renklerden değil, aynı
 * değerlerin her yerde tekrar etmesinden geliyor.
 */

import type { CSSProperties } from 'react';

export const C = {
  /** Ana metin. */
  text: '#e8ecf4',
  textBright: '#eef1f7',
  /** İkincil metin — etiketler, alt satırlar. */
  dim: 'rgba(232,236,244,.55)',
  dimmer: 'rgba(232,236,244,.40)',
  faint: 'rgba(232,236,244,.28)',

  /** Cam yüzeylerin kenarı. */
  line: 'rgba(255,255,255,.10)',
  lineSoft: 'rgba(255,255,255,.06)',

  /** Vurgulanan (seçili) yüzey. */
  active: 'rgba(255,255,255,.10)',
  hover: 'rgba(255,255,255,.05)',

  /** Pencere gövdesi. */
  window: 'rgba(17,20,28,.90)',
  /** Popover ve açılır paneller. */
  raised: 'rgba(16,19,27,.86)',

  accent: 'rgba(88,124,255,.85)',
  ok: '#5fd39a',
  warn: '#e0b13f',
  danger: '#e0524a',
} as const;

/** Trafik ışığı renkleri — pencere başlığındaki üç nokta. */
export const TRAFFIC = { close: '#e0524a', min: '#e0b13f', max: '#4fb45e' } as const;

/** Büyük harfli, aralıklı bölüm etiketi. */
export const LABEL: CSSProperties = {
  fontSize: 9.5,
  letterSpacing: '.26em',
  color: C.dimmer,
  textTransform: 'uppercase',
};

/** Form alanlarının ortak görünümü. */
export const FIELD: CSSProperties = {
  height: 34,
  padding: '0 12px',
  borderRadius: 9,
  border: `1px solid ${C.line}`,
  background: 'rgba(255,255,255,.045)',
  color: C.textBright,
  fontSize: 12.5,
  fontFamily: 'inherit',
  outline: 'none',
};

/** Cam kart: ayarlar grupları ve panel kutuları. */
export const GLASS: CSSProperties = {
  borderRadius: 16,
  border: '1px solid rgba(255,255,255,.075)',
  background: 'rgba(255,255,255,.030)',
  backdropFilter: 'blur(22px)',
  boxShadow: '0 28px 70px rgba(0,0,0,.40), inset 0 1px 0 rgba(255,255,255,.05)',
};

/** Tasarımın yazı ailesi. */
export const FONT =
  '"Helvetica Neue", Helvetica, Arial, "Segoe UI", system-ui, sans-serif';

export const MONO = '"SF Mono", Menlo, Consolas, monospace';

/**
 * Kabuğun animasyonları.
 *
 * Global stil olarak bir kez basılır. `<style>` etiketini her bileşenin
 * kendi içinde taşıması, aynı keyframe'in onlarca kez tanımlanması
 * demek olurdu.
 */
export const KEYFRAMES = `
@keyframes deskFadeUp { from { opacity:0; transform:translateY(10px) } to { opacity:1; transform:translateY(0) } }
@keyframes deskWinOpen { from { opacity:0; transform:scale(.94) } to { opacity:1; transform:scale(1) } }
@keyframes deskWinClose { from { opacity:1; transform:scale(1) } to { opacity:0; transform:scale(.93) } }
@keyframes deskWinMin { from { opacity:1; transform:scale(1) } to { opacity:0; transform:translate(-30%,46%) scale(.24) } }
@keyframes deskSpin { to { transform: rotate(360deg) } }
`;
