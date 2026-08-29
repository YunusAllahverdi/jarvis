import { VERT, FRAG } from './shaders';
import { THEMES, type ThemeName } from '../data';

export type OrbMode = 'idle' | 'listening' | 'speaking';

/**
 * Orb'un WebGL sürücüsü. React'ten bağımsızdır: bir canvas alır, kendi
 * animasyon döngüsünü çalıştırır ve mod/tema değişimlerini imperatif
 * çağrılarla kabul eder. Böylece kare başına React render'ı olmaz.
 *
 * Ses seviyesi iki kaynaktan gelebilir: mikrofon açıksa gerçek analiz,
 * değilse moda göre üretilen sentetik zarf.
 */
export class OrbEngine {
  private canvas: HTMLCanvasElement;
  private barsEl: HTMLElement | null;
  private gl: WebGLRenderingContext | null = null;
  private prog: WebGLProgram | null = null;
  private u: Record<string, WebGLUniformLocation | null> = {};

  private raf = 0;
  private t0 = performance.now();
  private tries = 0;

  private mode: OrbMode = 'listening';
  private theme: ThemeName = 'Gezegen';
  private intensity = 1;

  private level = 0.14;
  private bands = new Float32Array(8);

  private mic: { ctx: AudioContext; an: AnalyserNode; data: Uint8Array<ArrayBuffer> } | null = null;
  private micBusy = false;
  private micDenied = false;

  private onResize = () => this.resize();

  constructor(canvas: HTMLCanvasElement, barsEl: HTMLElement | null = null) {
    this.canvas = canvas;
    this.barsEl = barsEl;
  }

  /* ── yaşam döngüsü ────────────────────────────────────── */

  start(): void {
    this.initGL();
    window.addEventListener('resize', this.onResize);
    this.frame = this.frame.bind(this);
    this.raf = requestAnimationFrame(this.frame);
  }

  destroy(): void {
    cancelAnimationFrame(this.raf);
    window.removeEventListener('resize', this.onResize);
    if (this.mic) {
      void this.mic.ctx.close().catch(() => undefined);
      this.mic = null;
    }
    // Bağlam bilerek kaybettirilmiyor: React StrictMode geliştirmede
    // efektleri iki kez çalıştırır ve aynı canvas'a ikinci kez bağlanırken
    // kaybettirilmiş bir bağlam geri gelmez. Canvas kaldırıldığında bağlam
    // zaten toplanıyor.
    this.gl = null;
  }

  /* ── dışarıdan kontrol ────────────────────────────────── */

  setMode(mode: OrbMode): void { this.mode = mode; }
  setTheme(theme: ThemeName): void { this.theme = theme; }
  setIntensity(v: number): void { this.intensity = v; }
  isMicOn(): boolean { return this.mic !== null; }
  isMicDenied(): boolean { return this.micDenied; }

  /** Mikrofonu açar; kullanıcı reddederse sessizce sentetik moda döner. */
  async enableMic(): Promise<boolean> {
    if (this.mic || this.micBusy) return this.mic !== null;
    this.micBusy = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext();
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      an.smoothingTimeConstant = 0.72;
      ctx.createMediaStreamSource(stream).connect(an);
      this.mic = { ctx, an, data: new Uint8Array(new ArrayBuffer(an.frequencyBinCount)) };
      return true;
    } catch {
      this.micDenied = true;
      return false;
    } finally {
      this.micBusy = false;
    }
  }

  /* ── WebGL kurulumu ───────────────────────────────────── */

  private initGL(): void {
    const cv = this.canvas;
    const gl = cv.getContext('webgl', {
      antialias: false,
      alpha: false,
      preserveDrawingBuffer: true,
      powerPreference: 'high-performance',
    });

    // Bağlam bazen ilk denemede gelmez (sekme arka planda, GPU meşgul).
    // Sınırlı sayıda yeniden dene, sonra sessizce vazgeç.
    if (!gl) {
      this.tries += 1;
      if (this.tries < 12) window.setTimeout(() => this.initGL(), 250);
      return;
    }

    this.gl = gl;
    gl.getExtension('OES_standard_derivatives');

    const mk = (type: number, src: string): WebGLShader => {
      const sh = gl.createShader(type)!;
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        console.warn('[orb] shader:', gl.getShaderInfoLog(sh));
      }
      return sh;
    };

    const prog = gl.createProgram()!;
    gl.attachShader(prog, mk(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, mk(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    gl.useProgram(prog);
    this.prog = prog;

    // Ekranı kaplayan tek üçgen — tüm görüntü fragment shader'da üretiliyor.
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'p');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    this.u = {
      res: gl.getUniformLocation(prog, 'uRes'),
      t: gl.getUniformLocation(prog, 'uT'),
      lvl: gl.getUniformLocation(prog, 'uLevel'),
      int: gl.getUniformLocation(prog, 'uInt'),
      ba: gl.getUniformLocation(prog, 'uBA'),
      bb: gl.getUniformLocation(prog, 'uBB'),
      theme: gl.getUniformLocation(prog, 'uTheme'),
      a: gl.getUniformLocation(prog, 'uA'),
      b: gl.getUniformLocation(prog, 'uB'),
    };

    this.resize();
  }

  private resize(): void {
    const cv = this.canvas;
    const gl = this.gl;
    if (!gl) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.4);
    const w = Math.max(1, Math.round(cv.clientWidth * dpr));
    const h = Math.max(1, Math.round(cv.clientHeight * dpr));
    if (cv.width !== w || cv.height !== h) {
      cv.width = w;
      cv.height = h;
    }
    gl.viewport(0, 0, w, h);
  }

  /* ── seviye ve bantlar ────────────────────────────────── */

  private hex(h: string): [number, number, number] {
    const s = (h || '#ffffff').replace('#', '');
    const v = s.length === 3 ? s.split('').map((x) => x + x).join('') : s;
    const n = parseInt(v, 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }

  /** Mikrofon açıksa 8 banda indirgenmiş gerçek spektrum, değilse null. */
  private readMic(): number | null {
    const m = this.mic;
    if (!m) return null;
    m.an.getByteFrequencyData(m.data);
    const n = m.data.length;
    let rms = 0;
    for (let i = 0; i < 8; i++) {
      const lo = Math.floor(Math.pow(n, i / 8));
      const hi = Math.max(lo + 1, Math.floor(Math.pow(n, (i + 1) / 8)));
      let s = 0;
      for (let k = lo; k < hi; k++) s += m.data[k];
      const v = s / (hi - lo) / 255;
      this.bands[i] = v;
      rms += v;
    }
    return Math.min(1, (rms / 8) * 2.6);
  }

  private synthBands(t: number, lvl: number): void {
    for (let i = 0; i < 8; i++) {
      const f = 1.0 + i * 0.55;
      this.bands[i] =
        Math.abs(Math.sin(t * (2.1 + f) + i * 1.9) * Math.sin(t * (0.7 + i * 0.23) + 0.4)) *
        lvl *
        (1.0 - i * 0.07);
    }
  }

  private targetLevel(t: number): number {
    if (this.mode === 'speaking') {
      const e =
        Math.abs(Math.sin(t * 6.1) * Math.sin(t * 2.3 + 0.7)) * 0.7 +
        Math.abs(Math.sin(t * 11.7)) * 0.3;
      return 0.32 + 0.62 * e;
    }
    if (this.mode === 'listening') {
      return 0.15 + 0.24 * Math.abs(Math.sin(t * 1.6) * Math.sin(t * 0.53));
    }
    return 0.09 + 0.055 * (0.5 + 0.5 * Math.sin(t * 0.75));
  }

  /* ── döngü ────────────────────────────────────────────── */

  private frame(): void {
    this.raf = requestAnimationFrame(this.frame);
    // Sekme arka plandayken çizim yapma: GPU ve pil boşa gitmesin.
    if (document.hidden) return;
    if (!this.canvas.isConnected || !this.gl) return;
    this.tick();
  }

  private tick(): void {
    const t = (performance.now() - this.t0) / 1000;

    const live = this.readMic();
    if (live === null) {
      this.level += (this.targetLevel(t) - this.level) * 0.14;
      this.synthBands(t, this.level);
    } else {
      const floor = this.mode === 'idle' ? 0.09 : 0.14;
      this.level += (Math.max(floor, live) - this.level) * 0.3;
    }

    const gl = this.gl;
    if (gl && this.prog) {
      this.resize();
      gl.useProgram(this.prog);
      gl.uniform2f(this.u.res!, this.canvas.width, this.canvas.height);
      gl.uniform1f(this.u.t!, t);
      gl.uniform1f(this.u.lvl!, this.level);
      gl.uniform1f(this.u.int!, this.intensity);

      const th = THEMES[this.theme] ?? THEMES.Gezegen;
      gl.uniform1f(this.u.theme!, th.id);

      const bd = this.bands;
      gl.uniform4f(this.u.ba!, bd[0], bd[1], bd[2], bd[3]);
      gl.uniform4f(this.u.bb!, bd[4], bd[5], bd[6], bd[7]);

      const a = this.hex(th.a);
      const b = this.hex(th.b);
      gl.uniform3f(this.u.a!, a[0], a[1], a[2]);
      gl.uniform3f(this.u.b!, b[0], b[1], b[2]);

      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }

    this.paintBars(t);
  }

  /**
   * Durum çubuğundaki 54 bar doğrudan DOM üzerinden sürülür. React state'i
   * üzerinden geçirmek kare başına yeniden render demek olurdu.
   */
  private paintBars(t: number): void {
    const wrap = this.barsEl;
    if (!wrap) return;
    const bars = wrap.children;
    const n = bars.length;
    for (let i = 0; i < n; i++) {
      const x = i / Math.max(1, n - 1);
      const shape = Math.pow(Math.sin(Math.PI * x), 0.6);
      const j = 0.35 + 0.65 * Math.abs(Math.sin(t * 8.0 + i * 1.7) * Math.sin(t * 3.1 + i * 0.6));
      const v = Math.max(0.06, Math.min(1, this.level * 1.5 * shape * j));
      const el = bars[i] as HTMLElement;
      el.style.transform = `scaleY(${v.toFixed(3)})`;
      el.style.opacity = (0.35 + 0.6 * v).toFixed(2);
    }
  }
}
