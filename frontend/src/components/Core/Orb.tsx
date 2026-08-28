import { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useTheme } from '../../contexts/ThemeContext';
import { useUI } from '../../contexts/UIContext';

/* ── Shared GLSL noise ─────────────────────────────────── */

const noiseGLSL = /* glsl */ `
  float hash(float n) { return fract(sin(n) * 43758.5453123); }

  float noise(vec3 x) {
    vec3 p = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    float n = p.x + p.y * 157.0 + 113.0 * p.z;
    return mix(
      mix(mix(hash(n),        hash(n + 1.0),   f.x),
          mix(hash(n + 157.0), hash(n + 158.0), f.x), f.y),
      mix(mix(hash(n + 113.0), hash(n + 114.0), f.x),
          mix(hash(n + 270.0), hash(n + 271.0), f.x), f.y),
      f.z);
  }

  float fbm(vec3 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 5; i++) {
      v += a * noise(p);
      p = p * 2.01 + vec3(1.7, 9.2, 5.1);
      a *= 0.5;
    }
    return v;
  }
`;

/* ── Core sphere vertex shader ─────────────────────────── */

const coreVertex = /* glsl */ `
  ${noiseGLSL}

  uniform float uTime;
  uniform float uIntensity;

  varying vec3 vPos;
  varying vec3 vNorm;
  varying float vDisp;

  void main() {
    vNorm = normal;
    vec3 dir = normalize(position);

    // ── Slow organic breathing ──
    float breath = fbm(position * 1.2 + uTime * 0.09) * 0.06;

    // ── Mid-frequency fluid surface ──
    float fluid = noise(position * 2.8 + vec3(uTime * 0.17, uTime * 0.13, uTime * 0.11)) * 0.09;

    // ── Fine surface detail ──
    float detail = noise(position * 6.0 + uTime * 0.28) * 0.02;

    // ── Silhouette-breaking wave extensions ──
    // Strongest near the equator band, fade toward poles
    float eqMask = 1.0 - abs(dir.y);
    eqMask = pow(eqMask, 1.8);

    float w1 = noise(vec3(dir.x * 2.0 + uTime * 0.09, dir.z * 2.0, uTime * 0.06));
    float w2 = noise(vec3(dir.z * 1.6 - uTime * 0.07, dir.x * 1.6, uTime * 0.05 + 50.0));
    float w3 = noise(vec3(dir.y * 1.2 + uTime * 0.04, dir.x * 2.5, uTime * 0.08 + 100.0));

    // Narrow band masking → distinct tendrils, not uniform
    float t1 = smoothstep(0.42, 0.58, w1) * eqMask;
    float t2 = smoothstep(0.48, 0.62, w2) * eqMask;
    float t3 = smoothstep(0.44, 0.56, w3) * (1.0 - abs(dir.y) * 0.5);

    float waveExt = (t1 * 0.30 + t2 * 0.22 + t3 * 0.15) * uIntensity;

    float totalDisp = (breath + fluid + detail) * uIntensity + waveExt;
    vDisp = totalDisp;

    vec3 newPos = position + normal * totalDisp;
    vPos = newPos;

    gl_Position = projectionMatrix * modelViewMatrix * vec4(newPos, 1.0);
  }
`;

/* ── Core sphere fragment shader ───────────────────────── */

const coreFragment = /* glsl */ `
  ${noiseGLSL}

  uniform float uTime;
  uniform vec3  uColor1;   // blue
  uniform vec3  uColor2;   // violet
  uniform vec3  uColor3;   // pink accent
  uniform float uIntensity;

  varying vec3  vPos;
  varying vec3  vNorm;
  varying float vDisp;

  void main() {
    vec3 viewDir = normalize(cameraPosition - vPos);
    vec3 N       = normalize(vNorm);

    // ── Fresnel → glass rim ──
    float fresnel = 1.0 - max(dot(viewDir, N), 0.0);
    fresnel = pow(fresnel, 2.8);

    // ── Internal fluid stream layers ──
    // Layer 1 – large slow deep
    vec3  p1 = vPos * 1.8 + vec3(uTime * 0.065, uTime * 0.045, uTime * 0.075);
    float s1 = noise(p1);
    float b1 = 1.0 - smoothstep(0.04, 0.14, abs(s1 - 0.50));
    b1 = pow(b1, 3.5);

    // Layer 2 – medium, different axis
    vec3  p2 = vPos * 2.6 + vec3(-uTime * 0.085, uTime * 0.105, -uTime * 0.055);
    float s2 = noise(p2);
    float b2 = 1.0 - smoothstep(0.04, 0.11, abs(s2 - 0.48));
    b2 = pow(b2, 3.0);

    // Layer 3 – small fast detail
    vec3  p3 = vPos * 4.2 + vec3(uTime * 0.13, -uTime * 0.09, uTime * 0.16);
    float s3 = noise(p3);
    float b3 = 1.0 - smoothstep(0.06, 0.16, abs(s3 - 0.45));
    b3 = pow(b3, 2.5);

    // Layer 4 – deep volume glow
    float deep = fbm(vPos * 0.9 + uTime * 0.035);
    deep = smoothstep(0.30, 0.70, deep);

    // ── Color composition ──
    vec3 darkBase = uColor1 * 0.04;

    vec3 sc1 = mix(uColor1, uColor2, 0.3 + s1 * 0.4);
    vec3 sc2 = mix(uColor2, uColor3, s2 * 0.5);
    vec3 sc3 = mix(uColor1, uColor3, 0.2);

    vec3 streams = sc1 * b1 * 0.85
                 + sc2 * b2 * 0.65
                 + sc3 * b3 * 0.40;

    vec3 deepColor = mix(uColor1 * 0.12, uColor2 * 0.18, deep);

    vec3 color = darkBase + deepColor + streams * uIntensity;

    // Fresnel rim
    color += mix(uColor2, uColor3, 0.35) * fresnel * 0.55;

    // Wave extension glow – brighter where displacement is large
    color += (uColor1 + uColor2) * 0.4 * smoothstep(0.10, 0.32, vDisp) * 0.45;

    // ── Alpha ──
    float alpha = 0.82 + fresnel * 0.12;
    // Fade tips of wave extensions
    float distRatio = length(vPos) / 1.2;
    alpha *= mix(smoothstep(2.0, 1.25, distRatio), 1.0, 0.45);

    gl_FragColor = vec4(color, alpha);
  }
`;

/* ── Reflection plane shaders ──────────────────────────── */

const reflVertex = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const reflFragment = /* glsl */ `
  ${noiseGLSL}
  uniform float uTime;
  uniform vec3  uColor1;
  uniform vec3  uColor2;
  varying vec2  vUv;

  void main() {
    vec2 c = vUv - 0.5;
    float dist = length(c);
    float fade = pow(smoothstep(0.50, 0.0, dist), 2.5);

    float w1 = noise(vec3(vUv * 3.5, uTime * 0.08));
    float w2 = noise(vec3(vUv * 6.0 + 80.0, uTime * 0.06));
    float bright = w1 * 0.35 + w2 * 0.15;

    vec3 col = mix(uColor1, uColor2, w1);

    gl_FragColor = vec4(col * bright, fade * bright * 0.12);
  }
`;

/* ── OrbMesh ───────────────────────────────────────────── */

const stateSpeed: Record<string, number> = {
  idle: 0.35, listening: 0.55, thinking: 0.90, speaking: 0.75, error: 0.45,
};
const stateIntensity: Record<string, number> = {
  idle: 0.85, listening: 1.05, thinking: 1.35, speaking: 1.55, error: 1.0,
};

const OrbMesh = () => {
  const meshRef = useRef<THREE.Mesh>(null);
  const timeRef = useRef(0);
  const { currentTheme } = useTheme();
  const { orbState, orbIntensity } = useUI();

  const uniforms = useMemo(() => ({
    uTime:      { value: 0 },
    uColor1:    { value: new THREE.Color('#4488ff') },
    uColor2:    { value: new THREE.Color('#7c3aed') },
    uColor3:    { value: new THREE.Color('#c084fc') },
    uIntensity: { value: 1.0 },
  }), []);

  useFrame((state) => {
    const dt = state.clock.getDelta();
    const speed = (stateSpeed[orbState] ?? 0.35) + orbIntensity * 0.25;
    const intensity = (stateIntensity[orbState] ?? 0.85) + orbIntensity * 0.4;

    timeRef.current += dt * speed;
    uniforms.uTime.value      = timeRef.current;
    uniforms.uIntensity.value = THREE.MathUtils.lerp(uniforms.uIntensity.value, intensity, 0.04);

    // Smooth color transitions
    uniforms.uColor1.value.lerp(new THREE.Color(currentTheme.orb.coreColor), 0.03);
    uniforms.uColor2.value.lerp(new THREE.Color(currentTheme.orb.glowColor), 0.03);
    uniforms.uColor3.value.lerp(new THREE.Color(currentTheme.orb.accentColor), 0.03);

    if (meshRef.current) {
      meshRef.current.rotation.y += 0.0015 * speed;
      meshRef.current.rotation.x += 0.0008 * speed;
    }
  });

  return (
    <mesh ref={meshRef}>
      <icosahedronGeometry args={[1.2, 5]} />
      <shaderMaterial
        vertexShader={coreVertex}
        fragmentShader={coreFragment}
        uniforms={uniforms}
        transparent
        depthWrite={false}
      />
    </mesh>
  );
};

/* ── ReflectionPlane ───────────────────────────────────── */

const ReflectionPlane = () => {
  const { currentTheme } = useTheme();

  const uniforms = useMemo(() => ({
    uTime:   { value: 0 },
    uColor1: { value: new THREE.Color('#4488ff') },
    uColor2: { value: new THREE.Color('#7c3aed') },
  }), []);

  useFrame((state) => {
    uniforms.uTime.value = state.clock.getElapsedTime();
    uniforms.uColor1.value.lerp(new THREE.Color(currentTheme.orb.coreColor), 0.03);
    uniforms.uColor2.value.lerp(new THREE.Color(currentTheme.orb.glowColor), 0.03);
  });

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.65, 0]}>
      <planeGeometry args={[10, 10]} />
      <shaderMaterial
        vertexShader={reflVertex}
        fragmentShader={reflFragment}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </mesh>
  );
};

/* ── OrbContainer ──────────────────────────────────────── */

export const OrbContainer = () => {
  const { currentTheme } = useTheme();

  return (
    <div style={{
      width: '100%', height: '100%',
      position: 'relative',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {/* Soft atmospheric glow behind the orb */}
      <div style={{
        position: 'absolute',
        width: '70%', height: '70%',
        borderRadius: '50%',
        background: `radial-gradient(circle,
          ${currentTheme.orb.glowColor}33 0%,
          ${currentTheme.orb.coreColor}15 40%,
          transparent 70%)`,
        filter: 'blur(60px)',
        opacity: 0.45,
        pointerEvents: 'none',
      }} />

      {/* Three.js canvas */}
      <div style={{ width: '100%', height: '100%', zIndex: 1 }}>
        <Canvas
          camera={{ position: [0, 0.2, 4.8], fov: 40 }}
          gl={{ antialias: true, alpha: true }}
          style={{ background: 'transparent' }}
        >
          <OrbMesh />
          <ReflectionPlane />
        </Canvas>
      </div>
    </div>
  );
};
