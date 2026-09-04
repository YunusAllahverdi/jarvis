// Yeni Jarvis orb shaders — "uzayda su damlası" efekti.
// Önceki karmaşık shader (dağlar, sakura, şehir) kaldırıldı.
// Tek bir saf, organik, sıvı küre: yumuşak dalgalar, nefes alan ışık.

export const VERT = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`;

export const FRAG = `
precision highp float;
uniform vec2  uRes;
uniform float uT;
uniform float uLevel;   // 0..1 ses seviyesi
uniform vec3  uA;       // birinci tema rengi
uniform vec3  uB;       // ikinci tema rengi

// ── yardımcı fonksiyonlar ─────────────────────────────────────────────────

float hash(vec2 p) {
  p = fract(p * vec2(127.1, 311.7));
  p += dot(p, p + 17.5);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);  // smoothstep
  return mix(
    mix(hash(i), hash(i + vec2(1,0)), f.x),
    mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), f.x),
    f.y
  );
}

// 3 oktav FBM — hafif, ağır değil
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 3; i++) {
    v += a * noise(p);
    p  = p * 2.1 + vec2(1.7, 9.2);
    a *= 0.5;
  }
  return v;
}

// ── ana ───────────────────────────────────────────────────────────────────

void main() {
  // UV: merkez (0,0), kare piksel
  vec2 uv = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y;
  float t  = uT;
  float lvl = uLevel;

  // ── arka plan: koyu, saf ─────────────────────────────────────────────
  vec3 col = vec3(0.010, 0.010, 0.022);

  // ── orb parametreleri ────────────────────────────────────────────────
  // Orb canvas'ın tamamını kaplıyor (küçük canvas, sağ altta konumlandırılmış)
  float r = 0.38;
  vec2  c = uv;

  // ── organik kenar deformasyonu (su damlası gibi) ──────────────────────
  float ang = atan(c.y, c.x);

  // Çoklu sinüs dalgalarıyla yumuşak organik titreşim
  float w1 = sin(ang * 2.0 + t * 0.7)  * 0.018;
  float w2 = sin(ang * 3.0 - t * 1.1)  * 0.012;
  float w3 = sin(ang * 5.0 + t * 0.45) * 0.007;
  float w4 = sin(ang * 7.0 - t * 0.9)  * 0.004;

  // FBM ile ekstra organik gürültü — çok az, sadece canlılık için
  float nz = fbm(c * 2.5 + vec2(t * 0.12, t * 0.08));
  float wobble = w1 + w2 + w3 + w4 + (nz - 0.5) * 0.014;

  // Ses seviyesine göre titreşim genliği artar
  float deform = r * (1.0 + wobble * (0.6 + 0.8 * lvl));
  float dist   = length(c);

  // ── küre yüzey ───────────────────────────────────────────────────────
  float edge  = smoothstep(deform + 0.008, deform - 0.008, dist);
  float inner = smoothstep(deform - 0.008, deform - deform * 0.3, dist);

  if (edge > 0.0) {
    // Yüzey boyama: yumuşak gradyan, renk A→B
    float blend = 0.5 + 0.5 * dot(normalize(c), normalize(vec2(0.5, 0.8)));
    vec3 surface = mix(uA * 0.55, uB * 0.70, blend);

    // İç parlama — merkeze doğru biraz daha açık
    float glow = exp(-dist * dist * 3.5);
    surface += mix(uA, uB, 0.5) * glow * (0.18 + 0.35 * lvl);

    // İnce highlight (sol üst köşe yansıması)
    float hl  = dot(normalize(c), normalize(vec2(-0.55, 0.75)));
    float rim = smoothstep(0.60, 0.95, hl) * smoothstep(0.85, 0.99, dist / deform);
    surface += vec3(0.85, 0.92, 1.0) * rim * 0.55;

    // İnce kenar parlaması
    float edgeGlow = 1.0 - smoothstep(0.0, 0.022, deform - dist);
    surface += mix(uA, uB, 0.6) * edgeGlow * (0.30 + 0.45 * lvl);

    col = mix(col, surface, edge);
  }

  // ── dış hale (aura) ───────────────────────────────────────────────────
  float aura = exp(-max(dist - deform, 0.0) * (7.0 - 3.0 * lvl));
  col += mix(uA, uB, 0.5) * aura * (0.06 + 0.12 * lvl);

  // ── küçük sparkle'lar ─────────────────────────────────────────────────
  // Sadece ses aktifken, orb çevresinde küçük parıltılar
  if (lvl > 0.15) {
    for (int i = 0; i < 4; i++) {
      float fi = float(i);
      float sa = ang + fi * 1.5708 + t * (0.3 + fi * 0.11);
      float sr = deform * (1.05 + 0.08 * sin(t * 2.0 + fi * 2.4));
      vec2  sp = vec2(cos(sa), sin(sa)) * sr;
      float sd = length(c - sp);
      col += mix(uA, vec3(1.0), 0.5) * exp(-sd * 280.0) * (lvl - 0.15) * 1.8;
    }
  }

  // ── tone map ──────────────────────────────────────────────────────────
  col = col / (1.0 + col * 0.65);
  col = pow(max(col, 0.0), vec3(0.90));

  gl_FragColor = vec4(col, 1.0);
}
`;
