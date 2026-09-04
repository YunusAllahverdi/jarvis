import { VERT, FRAG } from './shaders';

export type OrbMode = 'idle' | 'listening' | 'speaking';

/** Orb renk teması — iki renk yeterli, karmaşık tema sistemi kaldırıldı. */
export interface OrbTheme {
  a: string; // birinci renk (hex)
  b: string; // ikinci renk (hex)
}

export const DEFAULT_THEME: OrbTheme = { a: '#5b7fff', b: '#9b59ff' };

/**
 * Su damlası orb motoru.
 * React'ten tamamen bağımsız — canvas alır, kendi döngüsünü çalıştırır.
 */
export class OrbEngine {
  private canvas: HTMLCanvasElement;
  private gl: WebGLRenderingContext | null = null;
  private prog: WebGLProgram | null = null;
  private u: Record<string, WebGLUniformLocation | null> = {};

  private raf = 0;
  private t0 = performance.now();
  private tries = 0;

  private mode: OrbMode = 'idle';
  private theme: OrbTheme = DEFAULT_THEME;

  private level = 0.1;

  private mic: { ctx: AudioContext; an: AnalyserNode; data: Uint8Array<ArrayBuffer> } | null = null;
  private micBusy = false;
  private micDenied = false;

  private onResize = () => this.resize();

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
  }

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
    this.gl = null;
  }

  setMode(mode: OrbMode): void { this.mode = mode; }
  setTheme(theme: OrbTheme): void { this.theme = theme; }
  isMicOn(): boolean { return this.mic !== null; }
  isMicDenied(): boolean { return this.micDenied; }

  async enableMic(): Promise<boolean> {
    if (this.mic || this.micBusy) return this.mic !== null;
    this.micBusy = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext();
      const an = ctx.createAnalyser();
      an.fftSize = 256;
      an.smoothingTimeConstant = 0.8;
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

  private initGL(): void {
    const cv = this.canvas;
    const gl = cv.getContext('webgl', {
      antialias: true,
      alpha: true,
      premultipliedAlpha: false,
      powerPreference: 'default',
    });

    if (!gl) {
      this.tries += 1;
      if (this.tries < 12) window.setTimeout(() => this.initGL(), 250);
      return;
    }

    this.gl = gl;
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    const mk = (type: number, src: string): WebGLShader => {
      const sh = gl.createShader(type)!;
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      return sh;
    };

    const prog = gl.createProgram()!;
    gl.attachShader(prog, mk(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, mk(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    gl.useProgram(prog);
    this.prog = prog;

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'p');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    this.u = {
      res:   gl.getUniformLocation(prog, 'uRes'),
      t:     gl.getUniformLocation(prog, 'uT'),
      lvl:   gl.getUniformLocation(prog, 'uLevel'),
      a:     gl.getUniformLocation(prog, 'uA'),
      b:     gl.getUniformLocation(prog, 'uB'),
    };

    this.resize();
  }

  private resize(): void {
    const cv = this.canvas;
    const gl = this.gl;
    if (!gl) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(cv.clientWidth * dpr));
    const h = Math.max(1, Math.round(cv.clientHeight * dpr));
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
    gl.viewport(0, 0, w, h);
  }

  private hex(h: string): [number, number, number] {
    const s = (h || '#ffffff').replace('#', '');
    const v = s.length === 3 ? s.split('').map(x => x + x).join('') : s;
    const n = parseInt(v, 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }

  private targetLevel(t: number): number {
    if (this.mode === 'speaking') {
      return 0.35 + 0.55 * Math.abs(Math.sin(t * 5.2) * Math.sin(t * 2.1 + 0.5));
    }
    if (this.mode === 'listening') {
      return 0.18 + 0.22 * Math.abs(Math.sin(t * 1.8) * Math.sin(t * 0.6));
    }
    // idle: çok yavaş, çok hafif nefes
    return 0.08 + 0.06 * (0.5 + 0.5 * Math.sin(t * 0.55));
  }

  private readMic(): number | null {
    const m = this.mic;
    if (!m) return null;
    m.an.getByteFrequencyData(m.data);
    let sum = 0;
    for (let i = 0; i < m.data.length; i++) sum += m.data[i];
    return Math.min(1, (sum / m.data.length / 128) * 2.2);
  }

  private frame(): void {
    this.raf = requestAnimationFrame(this.frame);
    if (document.hidden) return;
    if (!this.canvas.isConnected || !this.gl) return;
    this.tick();
  }

  private tick(): void {
    const t = (performance.now() - this.t0) / 1000;

    const live = this.readMic();
    if (live === null) {
      this.level += (this.targetLevel(t) - this.level) * 0.08; // çok yumuşak geçiş
    } else {
      const floor = this.mode === 'idle' ? 0.08 : 0.12;
      this.level += (Math.max(floor, live) - this.level) * 0.25;
    }

    const gl = this.gl;
    if (gl && this.prog) {
      this.resize();
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(this.prog);
      gl.uniform2f(this.u.res!, this.canvas.width, this.canvas.height);
      gl.uniform1f(this.u.t!, t);
      gl.uniform1f(this.u.lvl!, this.level);

      const a = this.hex(this.theme.a);
      const b = this.hex(this.theme.b);
      gl.uniform3f(this.u.a!, a[0], a[1], a[2]);
      gl.uniform3f(this.u.b!, b[0], b[1], b[2]);

      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
  }
}
