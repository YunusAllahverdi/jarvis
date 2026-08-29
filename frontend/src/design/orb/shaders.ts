// Jarvis orb shaders — Claude Design artboard'undan birebir alındı.
// GLSL kaynağı elle düzenlenmemelidir; görsel değişiklikler tasarım
// projesinde yapılıp buraya yeniden aktarılmalıdır.

export const VERT = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`;

export const FRAG = `
#extension GL_OES_standard_derivatives : enable
precision highp float;
uniform vec2 uRes;
uniform float uT;
uniform float uLevel;
uniform float uInt;
uniform vec3 uA;
uniform vec3 uB;
uniform float uTheme;
uniform vec4 uBA;
uniform vec4 uBB;

const float R = 0.185;
const float HZ = -0.21;
const vec2 ORBC = vec2(0.0, 0.025);

float h21(vec2 p){ p = fract(p * vec2(127.31, 311.7)); p += dot(p, p + 34.72); return fract(p.x * p.y); }
float vn(vec2 p){
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = h21(i), b = h21(i + vec2(1.0,0.0)), c = h21(i + vec2(0.0,1.0)), d = h21(i + vec2(1.0,1.0));
  return mix(mix(a,b,f.x), mix(c,d,f.x), f.y);
}
float fbm(vec2 p){
  float s = 0.0, a = 0.5;
  for(int i = 0; i < 4; i++){ s += a * vn(p); p *= 2.07; a *= 0.5; }
  return s;
}
float aaw(float s){
#ifdef GL_OES_standard_derivatives
  return clamp(fwidth(s), 0.0006, 0.4);
#else
  return 0.01;
#endif
}

// One silk strand family: contour lines of the stream function.
vec3 strand(float s, float phi, float t, float lvl, vec3 c, float wid, float halo, float bright, float taper){
  float d = abs(fract(s) - 0.5);
  wid *= 0.40 + 0.85 * taper;
  float g = aaw(s);
  float core = 1.0 - smoothstep(wid, wid + g * 1.25 + 0.002, d);
  float soft = exp(-d * d * 55.0);
  float wide = exp(-d * d * 11.0);
  float flow = 0.60 + 0.40 * sin(phi * 8.0 - t * 1.4 + s * 0.6);
  float e = core * bright * flow * (1.35 + 1.45 * lvl);
  vec3 o = c * (e + soft * halo * (0.38 + 0.75 * lvl) + wide * halo * 0.16);
  o += mix(c, vec3(1.0), 0.72) * e * 0.55;
  float pos = -1.5 + fract(t * 0.19) * 3.1;
  o += vec3(0.80, 0.88, 1.0) * core * exp(-pow((phi - pos) / 0.040, 2.0)) * (0.35 + 1.1 * lvl);
  return o;
}

// Potential flow around the sphere: the strands bend around the orb.
vec3 ribbons(vec2 p, float t, float lvl, float full){
  float r = max(length(p), 0.02);
  float k = min((R * R) / (r * r), 3.0);
  float psi = p.y * (1.0 - k);
  float phi = p.x * (1.0 + k);
  float w1 = fbm(vec2(p.x * 0.85 + t * 0.045, p.y * 1.15 - t * 0.020));
  float w2 = fbm(vec2(p.x * 1.70 - t * 0.030, p.y * 0.70 + 5.3));
  float near = exp(-max(r - R, 0.0) * 3.9) + 1.30 * exp(-max(r - R, 0.0) * 9.5);
  vec3 cold = mix(vec3(0.24, 0.60, 1.0), uA, 0.28);
  vec3 cl = mix(cold, uB, smoothstep(-0.42, 0.40, p.x + (w1 - 0.5) * 0.85));
  vec3 cc = mix(cl, vec3(1.0), 0.10 + 0.40 * near);

  float tp = clamp(near, 0.0, 1.4);
  vec3 col = strand((psi + (w1 - 0.5) * 0.36) * 3.3, phi, t, lvl, cc, 0.0115, 0.26, 1.0, tp);
  col += strand((psi * 1.35 + (w1 - 0.5) * 0.40 + (w2 - 0.5) * 0.22 + 0.37) * 4.7, phi, t * 1.12, lvl, cl, 0.0085, 0.17, 0.75, tp);
  if(full > 0.5){
    col += strand((psi * 0.80 + (w2 - 0.5) * 0.58 + 0.71) * 2.3, phi, t * 0.82, lvl, mix(cl, cold, 0.45), 0.014, 0.28, 0.5, tp);
    col += strand((psi * 2.35 + (w1 - 0.5) * 0.52 + (w2 - 0.5) * 0.30 + 0.11) * 8.5, phi, t * 1.35, lvl, cc, 0.006, 0.10, 0.42, tp);
    float sd = floor(t * 1.9);
    float flash = exp(-fract(t * 1.9) * 11.0) * step(h21(vec2(sd, 3.7)), 0.28 + 0.55 * lvl);
    float sb = psi * 7.5 + (w2 - 0.5) * 0.8 + h21(vec2(sd, 9.1)) * 4.0;
    float bd = abs(fract(sb) - 0.5);
    float bolt = 1.0 - smoothstep(0.008, 0.008 + aaw(sb) * 1.4 + 0.003, bd);
    col += vec3(0.86, 0.93, 1.0) * bolt * flash * near * 2.2;
  }
  return col * (0.045 + 0.90 * near);
}

float mtn(float x, float o, float sc, float amp){
  float n = fbm(vec2(x * sc + o, o * 1.3));
  float ridge = 1.0 - abs(n * 2.0 - 1.0);
  return (ridge * 0.85 - 0.22) * amp * smoothstep(0.12, 0.48, abs(x));
}

// Skyline height above the horizon, per theme and layer.
float hgt(float x, float th, float lay){
  if(th < 0.5){
    float o = lay < 0.5 ? 3.2 : 11.5;
    float sc = lay < 0.5 ? 2.4 : 3.9;
    float am = lay < 0.5 ? 0.36 : 0.24;
    return mtn(x, o, sc, am);
  }
  if(th < 1.5){
    if(lay < 0.5){
      float cone = 0.415 * exp(-pow(abs(x) / 0.80, 1.22)) - 0.016;
      cone += (fbm(vec2(x * 9.0, 2.3)) - 0.5) * 0.016;
      return cone;
    }
    return (fbm(vec2(x * 2.2 + 7.0, 4.0)) - 0.42) * 0.20;
  }
  float ci = floor(x * (lay < 0.5 ? 9.0 : 15.0) + lay * 4.0);
  float hh = h21(vec2(ci, lay * 3.0 + 1.0));
  float top = (lay < 0.5 ? 0.30 : 0.20) * (0.28 + 0.72 * hh);
  return top * smoothstep(0.04, 0.30, abs(x)) - 0.010;
}

// A sakura branch entering from the left edge: x = wood, y = blossom.
vec2 branchSide(vec2 p, float t, float seed, float top){
  float run = p.x + 1.05;
  float sway = sin(t * 0.5 + seed) * 0.012 * clamp(run, 0.0, 1.4);
  float y = top - 0.145 * run - 0.045 * sin(run * 4.4 + seed) + sway;
  float dy = p.y - y;
  float ext = smoothstep(0.34, -0.10, p.x) * step(-1.30, p.x);
  float taper = mix(0.0075, 0.0022, clamp(run / 1.5, 0.0, 1.0));
  float wood = (1.0 - smoothstep(taper, taper + 0.0035, abs(dy))) * ext;
  float tw = sin(run * 9.0 + seed * 3.0);
  float ty = y - 0.055 - 0.03 * tw;
  wood = max(wood, (1.0 - smoothstep(0.0022, 0.005, abs(p.y - ty))) * ext * step(0.35, fract(run * 2.3 + seed)) * 0.8);
  float band = exp(-pow(dy / 0.075, 2.0)) + 0.55 * exp(-pow((dy + 0.055) / 0.055, 2.0));
  float n = fbm(vec2(run * 8.5 + seed, dy * 11.0 + seed));
  float petal = fbm(vec2(run * 34.0 + seed, dy * 38.0));
  float bl = smoothstep(0.50, 0.70, n) * band * ext * (0.45 + 0.85 * smoothstep(0.40, 0.68, petal));
  return vec2(wood, clamp(bl, 0.0, 1.2));
}

float petalMix(vec2 uv){ return fbm(uv * 22.0 + 3.3); }

// Wind-blown petals / embers.
vec3 motes(vec2 uv, float t, vec3 ca, vec3 cb){
  vec3 c = vec3(0.0);
  for(int i = 0; i < 3; i++){
    float fi = float(i);
    float sc = 8.0 + fi * 6.0;
    vec2 p = uv * sc;
    p.x += t * (1.05 + 0.45 * fi) + sin(uv.y * 3.2 + t * 0.8 + fi) * 0.9;
    p.y += t * (0.30 + 0.14 * fi);
    vec2 cell = floor(p);
    vec2 f = fract(p) - 0.5;
    float rnd = h21(cell + fi * 17.3);
    if(rnd > 0.935){
      vec2 off = vec2(h21(cell + 3.1) - 0.5, h21(cell + 7.7) - 0.5) * 0.6;
      float d = length((f - off) * vec2(1.0, 2.2 + 0.7 * sin(t * 2.4 + rnd * 30.0)));
      c += mix(ca, cb, fract(rnd * 7.0)) * smoothstep(0.085, 0.008, d) * (0.75 - 0.16 * fi);
    }
  }
  return c;
}

// Radial displacement from the 8 audio bands — the rim breathes like a waveform.
float rmod(float ang, float t){
  float s = uBA.x * sin(ang * 2.0 + t * 1.9)
          + uBA.y * sin(ang * 3.0 - t * 1.4 + 1.1)
          + uBA.z * sin(ang * 4.0 + t * 2.3 + 2.2)
          + uBA.w * sin(ang * 5.0 - t * 1.7 + 0.6)
          + uBB.x * sin(ang * 6.0 + t * 2.6)
          + uBB.y * sin(ang * 7.0 - t * 2.1 + 1.7)
          + uBB.z * sin(ang * 8.0 + t * 3.0 + 0.4)
          + uBB.w * sin(ang * 9.0 - t * 2.4 + 2.9);
  return s * 0.125;
}

void main(){
  vec2 uv = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y;
  float t = uT;
  float lvl = uLevel;
  vec2 c = uv - ORBC;

  vec3 col = vec3(0.010, 0.009, 0.027);

  float w = fbm(uv * 0.9 + t * 0.010);
  float neb = pow(fbm(uv * 1.5 + w * 1.1 + vec2(t * 0.009, -t * 0.006)), 2.0);
  col += mix(uA, uB, clamp(fbm(uv * 0.55 - t * 0.007) * 1.4, 0.0, 1.0)) * neb * 0.085
       * smoothstep(0.85, 0.05, length(c * vec2(0.60, 1.0)));

  float mA = hgt(uv.x, uTheme, 0.0);
  float mB = hgt(uv.x, uTheme, 1.0);
  float band = exp(-pow(abs(uv.y - ORBC.y) / 0.26, 2.2));

  if(uv.y > HZ){
    if(uv.y > HZ + mA){
      vec2 sc = floor(gl_FragCoord.xy * 0.7);
      float star = fract(sin(dot(sc, vec2(12.9898, 78.233))) * 43758.5453);
      col += vec3(0.72, 0.80, 1.0) * step(0.9993, star) * (0.30 + 0.70 * abs(sin(t * 1.7 + star * 90.0)));
    } else {
      col += mix(uA, uB, 0.7) * smoothstep(0.0035, 0.0, abs(uv.y - (HZ + mA))) * 0.85;
      vec3 fill = vec3(0.030, 0.026, 0.058);
      if(uTheme > 0.5 && uTheme < 1.5){
        fill = vec3(0.072, 0.062, 0.112) * (0.45 + 0.95 * smoothstep(HZ, HZ + 0.34, uv.y));
        float cap = HZ + 0.300 + (fbm(vec2(uv.x * 22.0, 9.0)) - 0.5) * 0.034;
        float snow = smoothstep(cap - 0.003, cap + 0.014, uv.y);
        fill = mix(fill, vec3(0.56, 0.58, 0.74), snow * 0.94);
        float gully = fbm(vec2(uv.x * 26.0, uv.y * 8.0 + 4.0));
        fill *= 0.78 + 0.44 * gully;
        fill += vec3(0.10, 0.11, 0.17) * smoothstep(0.035, 0.0, abs(uv.y - (HZ + mA))) * 1.1;
      } else if(uTheme > 1.5){
        fill = vec3(0.020, 0.026, 0.050);
      }
      col = mix(col, fill, uTheme > 0.5 && uTheme < 1.5 ? 0.96 : 0.90);
      if(uv.y < HZ + mB) col = mix(col, vec3(0.008, 0.010, 0.026), 0.93);
      if(uTheme > 1.5){
        float front = step(uv.y, HZ + mA);
        float cw = front > 0.5 ? 9.0 : 15.0;
        float fx = fract(uv.x * cw + (front > 0.5 ? 0.0 : 4.0));
        float seam = min(fx, 1.0 - fx);
        vec3 neon = mix(uA, uB, 0.5 + 0.5 * sin(floor(uv.x * cw) * 2.1));
        col += neon * (1.0 - smoothstep(0.004, 0.014, seam)) * (front > 0.5 ? 0.16 : 0.07);
        vec2 wc = floor(vec2(uv.x * 250.0, uv.y * 150.0));
        float wr = h21(wc + 5.0);
        float lit = step(0.925, wr) * step(0.28, fract(wr * 13.0 + t * 0.07));
        col += mix(mix(uA, uB, fract(wr * 31.0)), vec3(1.0, 0.92, 0.78), 0.35)
             * lit * (front > 0.5 ? 0.42 : 0.18);
        col += mix(uA, uB, 0.5) * exp(-(uv.y - HZ) * 13.0) * 0.09;
      }
    }
    if(uTheme > 0.5 && uTheme < 1.5){
      vec2 sL = branchSide(uv, t, 0.0, 0.46);
      vec2 sR = branchSide(vec2(-uv.x, uv.y), t, 4.7, 0.415);
      float wood = max(sL.x, sR.x);
      float bl = max(sL.y, sR.y);
      col = mix(col, vec3(0.026, 0.012, 0.022), clamp(bl * 0.80, 0.0, 0.80));
      col += mix(vec3(1.0, 0.46, 0.70), vec3(1.0, 0.84, 0.90), petalMix(uv)) * bl * 1.05;
      col = mix(col, vec3(0.10, 0.075, 0.085), wood * 0.85);
    }
    col += ribbons(c, t, lvl, 1.0) * band * smoothstep(HZ - 0.01, HZ + 0.22, uv.y);
    if(uTheme > 0.5){
      vec3 ca = uTheme < 1.5 ? vec3(1.0, 0.66, 0.80) : mix(uA, vec3(1.0), 0.35);
      vec3 cb = uTheme < 1.5 ? vec3(1.0, 0.90, 0.94) : mix(uB, vec3(1.0), 0.35);
      col += motes(uv, t, ca, cb) * (0.55 + 0.45 * lvl);
    }
  } else {
    float dep = HZ - uv.y;
    vec2 mu = vec2(uv.x + (fbm(vec2(uv.x * 4.0, dep * 17.0 - t * 0.45)) - 0.5) * dep * 0.55, HZ + dep * 1.85);
    vec2 mc = mu - ORBC;
    float bR = exp(-pow(abs(mu.y - ORBC.y) / 0.30, 2.2));
    vec3 refl = ribbons(mc, t, lvl, 0.0) * bR * 0.30 * smoothstep(R * 0.80, R * 1.10, length(mc))
              + mix(uA, uB, 0.5) * exp(-max(length(mc) - R, 0.0) * 8.5) * 0.26;
    if(mu.y < HZ + mA) refl *= 0.25;
    float fade = exp(-dep * 3.2);
    col = vec3(0.006, 0.005, 0.016) + refl * fade * 0.55;
    col += mix(uA, uB, 0.45) * exp(-pow(uv.x / 0.11, 2.0)) * fade * 0.10;
    col += vec3(0.036, 0.042, 0.105) * exp(-dep * 18.0) * 0.18;
    float rip = pow(max(0.0, sin(dep * 62.0 + fbm(vec2(uv.x * 6.0, dep * 8.0)) * 7.0)), 10.0);
    col += mix(uA, uB, 0.5) * rip * fade * 0.09;
  }

  col += vec3(0.042, 0.048, 0.125) * exp(-abs(uv.y - HZ) * 17.0) * 0.30;
  col += mix(uA, uB, 0.5) * exp(-abs(uv.y - HZ) * 22.0) * exp(-pow(uv.x / 0.26, 2.0)) * (0.10 + 0.20 * lvl);

  float d = length(c);
  float ang = atan(c.y, c.x);
  float RM = R * (1.0 + 0.13 * rmod(ang, t));
  col += mix(uA, uB, 0.5) * exp(-max(d - RM, 0.0) * 8.0) * (0.16 + 0.50 * lvl)
       + mix(uA, uB, 0.5) * exp(-max(d - RM, 0.0) * 2.2) * (0.05 + 0.14 * lvl);

  if(d < RM){
    vec2 q = c / RM;
    float nz = sqrt(max(0.0, 1.0 - dot(q, q)));
    col *= mix(0.20, 0.030, nz);
    vec2 sp = q;
    float ws1 = fbm(vec2(sp.x * 1.15 + t * 0.055, sp.y * 0.95 - t * 0.030));
    float ws2 = fbm(vec2(sp.x * 2.10 - t * 0.040, sp.y * 1.35 + 8.1));
    vec3 tint = mix(mix(vec3(0.30, 0.66, 1.0), uA, 0.30), uB, smoothstep(-0.85, 0.85, sp.x));
    vec3 ins = strand((sp.y * 0.55 + (ws1 - 0.5) * 0.80) * 1.75, sp.x * 1.7, t, lvl, mix(tint, vec3(1.0), 0.18), 0.030, 0.30, 1.0, 1.0);
    ins += strand((sp.y * 0.85 + (ws1 - 0.5) * 0.62 + (ws2 - 0.5) * 0.40 + 0.41) * 2.7, sp.x * 1.7, t * 1.18, lvl, tint, 0.020, 0.20, 0.62, 1.0);
    ins *= exp(-pow(abs(sp.y) / 0.92, 2.4));
    col += ins * (0.30 + 0.80 * nz) * 0.95;
    col += mix(uA, uB, 0.30) * exp(-d * 13.0) * (0.07 + 0.50 * lvl);
    col += mix(uA, uB, 0.55) * pow(1.0 - nz, 3.2) * 0.40;
    vec2 nq = q / max(length(q), 1e-4);
    col += vec3(0.80, 0.90, 1.0) * smoothstep(0.70, 1.0, dot(nq, normalize(vec2(-0.52, 0.80))))
         * smoothstep(0.58, 0.99, length(q)) * 0.62;
    col += mix(uB, vec3(1.0), 0.30) * smoothstep(0.90, 1.0, dot(nq, normalize(vec2(0.66, -0.52))))
         * smoothstep(0.74, 1.0, length(q)) * 0.28;
  }

  col += vec3(0.78, 0.87, 1.0) * smoothstep(0.0045, 0.0, abs(d - RM)) * (0.28 + 0.50 * lvl);
  {
    float rr = R * (1.0 + 0.26 * rmod(ang, t * 1.15 + 2.0)) * 1.20;
    col += mix(uA, uB, 0.5) * smoothstep(0.0055, 0.0, abs(d - rr)) * (0.10 + 0.55 * lvl);
    float r2 = R * (1.0 + 0.34 * rmod(ang, t * 0.85 - 1.3)) * 1.42;
    col += mix(uA, uB, 0.65) * smoothstep(0.0045, 0.0, abs(d - r2)) * (0.05 + 0.35 * lvl);
  }

  {
    float rf = max(length(c), 0.02);
    float kf = min((R * R) / (rf * rf), 3.0) * 0.22;
    float psif = c.y * (1.0 - kf);
    float phif = c.x * (1.0 + kf);
    float wf = fbm(vec2(c.x * 0.8 - t * 0.035, c.y * 1.1 + 19.3));
    vec3 cf = mix(mix(vec3(0.30, 0.64, 1.0), uA, 0.35), uB, smoothstep(-0.40, 0.40, c.x));
    col += strand((psif + (wf - 0.5) * 0.42 + 0.19) * 2.9, phif, t * 0.9, lvl, cf, 0.0075, 0.20, 0.62, 1.0)
         * band * exp(-max(rf - R, 0.0) * 2.4) * 0.85;
  }

  col *= uInt;
  col *= 1.0 - 0.45 * smoothstep(0.34, 1.10, length(uv * vec2(0.62, 1.0)));
  col = col / (1.0 + col * 0.70);
  col = pow(max(col, 0.0), vec3(0.92));
  gl_FragColor = vec4(col, 1.0);
}
`;
