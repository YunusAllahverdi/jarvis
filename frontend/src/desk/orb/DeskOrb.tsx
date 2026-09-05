import { useEffect, useRef } from 'react';
import { DESK_FRAG, DESK_VERT } from './deskShader';

/**
 * Kürenin dört durumu.
 *
 * Bunlar süs değil, sistemin durum göstergesidir: kullanıcı bir soru
 * sorduktan sonra hiçbir şey olmuyormuş gibi görünen bir arayüzde
 * isteğin gidip gitmediğini bilemez. Küre, bekleyişi görünür kılan tek
 * şeydir — bu yüzden faz DEĞİŞİMİ gerçek olaylara bağlanır, zamanlayıcıya
 * değil.
 */
export type OrbPhase = 'idle' | 'listening' | 'thinking' | 'responding';

const PHASE_VALUE: Record<OrbPhase, number> = {
  idle: 0,
  listening: 1,
  thinking: 2,
  responding: 3,
};

export const PHASE_LABEL: Record<OrbPhase, string> = {
  idle: 'HAZIR',
  listening: 'DİNLİYOR',
  thinking: 'DÜŞÜNÜYOR',
  responding: 'YANITLIYOR',
};

interface Props {
  phase: OrbPhase;
  /** Piksel cinsinden çap; moda göre değişir ve geçiş CSS ile yumuşar. */
  size: number;
  left: string;
  top: string;
  animated: boolean;
  onClick?: () => void;
}

/**
 * WebGL küre.
 *
 * Faz ve boyut React state'inden gelir ama çizim döngüsü React'in DIŞINDA
 * çalışır: kare başına bir render, saniyede 60 React ağacı demek olurdu ve
 * altındaki masa pencereleri boşuna yeniden hesaplanırdı. Bu yüzden
 * değişen değerler ref üzerinden döngüye sızdırılır.
 */
export const DeskOrb = ({ phase, size, left, top, animated, onClick }: Props) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const glowRef = useRef<HTMLDivElement | null>(null);

  // Döngünün okuduğu değerler. State doğrudan okunsaydı, efekt her faz
  // değişiminde WebGL bağlamını yeniden kurardı.
  const phaseRef = useRef(phase);
  const animRef = useRef(animated);
  phaseRef.current = phase;
  animRef.current = animated;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext('webgl', {
      alpha: true,
      premultipliedAlpha: false,
      antialias: true,
    });
    // WebGL yoksa küre hiç çizilmez ama uygulama çalışmaya devam eder.
    // Bir animasyon için tüm arayüzü düşürmek orantısız olurdu.
    if (!gl) return;

    const compile = (type: number, src: string) => {
      const shader = gl.createShader(type);
      if (!shader) return null;
      gl.shaderSource(shader, src);
      gl.compileShader(shader);
      return shader;
    };

    const program = gl.createProgram();
    const vert = compile(gl.VERTEX_SHADER, DESK_VERT);
    const frag = compile(gl.FRAGMENT_SHADER, DESK_FRAG);
    if (!program || !vert || !frag) return;

    gl.attachShader(program, vert);
    gl.attachShader(program, frag);
    gl.linkProgram(program);
    gl.useProgram(program);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW,
    );
    const attr = gl.getAttribLocation(program, 'p');
    gl.enableVertexAttribArray(attr);
    gl.vertexAttribPointer(attr, 2, gl.FLOAT, false, 0, 0);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    const uT = gl.getUniformLocation(program, 't');
    const uS = gl.getUniformLocation(program, 'st');
    const uZ = gl.getUniformLocation(program, 'sz');

    let raf = 0;
    let width = 0;
    let height = 0;
    let last = performance.now();
    let clock = 0;
    // Faz ATLAYARAK değil, süzülerek değişir: küre bir durumdan diğerine
    // sıçrasaydı, geçiş bir hata gibi görünürdü.
    let smoothed = 0;

    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;

      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = Math.max(1, Math.round(rect.width * dpr));
      const h = Math.max(1, Math.round(rect.height * dpr));
      if (w !== width || h !== height) {
        width = w;
        height = h;
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);
      }

      if (animRef.current) clock += dt;
      const target = PHASE_VALUE[phaseRef.current];
      smoothed += (target - smoothed) * Math.min(1, dt * 1.6);

      gl.uniform1f(uT, clock);
      gl.uniform1f(uS, smoothed);
      gl.uniform1f(uZ, Math.min(1, Math.max(0, (rect.width - 60) / 180)));
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

      const glow = glowRef.current;
      if (glow) {
        glow.style.opacity = (
          0.42 + 0.16 * Math.sin(clock * 0.4) + 0.3 * (smoothed / 3)
        ).toFixed(3);
        glow.style.transform = `scale(${
          1 + 0.05 * (smoothed / 3) + 0.02 * Math.sin(clock * 0.31)
        })`;
      }

      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div
      onClick={onClick}
      title={PHASE_LABEL[phase]}
      style={{
        position: 'absolute',
        left,
        top,
        zIndex: 20,
        width: size,
        height: size,
        transform: 'translate(-50%,-50%)',
        cursor: onClick ? 'pointer' : 'default',
        transition:
          'left .6s cubic-bezier(.4,0,.2,1), top .6s cubic-bezier(.4,0,.2,1), width .6s ease, height .6s ease',
      }}
    >
      <div
        ref={glowRef}
        style={{
          position: 'absolute',
          inset: '-40%',
          borderRadius: '50%',
          background:
            'radial-gradient(circle, rgba(190,212,255,.22), rgba(190,212,255,0) 60%)',
          pointerEvents: 'none',
        }}
      />
      <canvas
        ref={canvasRef}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          borderRadius: '50%',
          display: 'block',
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: '50%',
          pointerEvents: 'none',
          border: '1px solid rgba(255,255,255,.16)',
          boxShadow:
            'inset 0 1.5px 2px rgba(255,255,255,.55), 0 30px 80px rgba(0,0,0,.55)',
        }}
      />
    </div>
  );
};
