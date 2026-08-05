import { AvatarStateEvent } from "../AvatarStateMachine";

/**
 * Volumetric 3D avatar renderer.
 *
 * Raymarches a signed-distance-field head in a single fragment shader — no meshes,
 * no textures, no third-party 3D library. Visemes drive the mouth SDF, emotions
 * drive brow rotation and the material's spectral tint, and the avatar state drives
 * head pose and the rim-light energy.
 *
 * Implements the same contract as CanvasSpriteRenderer, so it is a drop-in swap.
 */

const VERT = `#version 300 es
in vec2 aPos;
out vec2 vUv;
void main() {
  vUv = aPos;
  gl_Position = vec4(aPos, 0.0, 1.0);
}`;

const FRAG = `#version 300 es
precision highp float;

in vec2 vUv;
out vec4 outColor;

uniform vec2  uRes;
uniform float uTime;
uniform float uMouthOpen;   // 0..1 jaw aperture
uniform float uMouthWide;   // 0..1 corner spread
uniform float uBrowTilt;    // -1..1
uniform float uBlink;       // 0..1
uniform float uLevel;       // mic level 0..1
uniform float uThink;       // 0..1 thinking blend
uniform float uSpeak;       // 0..1 speaking blend
uniform float uListen;      // 0..1 listening blend
uniform vec3  uTint;        // emotion colour

#define MAX_STEPS 96
#define SURF 0.0015
#define FAR 12.0

float smin(float a, float b, float k) {
  float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
  return mix(b, a, h) - k * h * (1.0 - h);
}
float smax(float a, float b, float k) {
  return -smin(-a, -b, k);
}
float sdSphere(vec3 p, float r) { return length(p) - r; }
float sdEllipsoid(vec3 p, vec3 r) {
  float k0 = length(p / r);
  float k1 = length(p / (r * r));
  return k0 * (k0 - 1.0) / k1;
}
float sdCapsule(vec3 p, vec3 a, vec3 b, float r) {
  vec3 pa = p - a, ba = b - a;
  float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
  return length(pa - ba * h) - r;
}
mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }

float hash(vec3 p) {
  p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419));
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float noise(vec3 x) {
  vec3 i = floor(x), f = fract(x);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(hash(i + vec3(0,0,0)), hash(i + vec3(1,0,0)), f.x),
                 mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
             mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
                 mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
}

// Returns (distance, materialId)
//  1 = shell   3 = emissive light element (eye slits, mouth bar)
vec2 map(vec3 p) {
  // idle breathing + micro head sway
  float breathe = sin(uTime * 1.1) * 0.012;
  float sway    = sin(uTime * 0.47) * 0.035 + uThink * sin(uTime * 1.9) * 0.03;
  float nod     = cos(uTime * 0.61) * 0.022;

  vec3 q = p;
  q.y -= breathe;
  q.xz *= rot(sway);
  q.yz *= rot(nod * 0.6 - uThink * 0.06);

  // ---- cranium + jaw ----
  vec3 s = q;
  s.x *= 1.13;
  s.y *= 0.94;
  s.z *= 1.02;
  float skull = sdSphere(s, 0.96);

  vec3 jw = q - vec3(0.0, -0.52 - uMouthOpen * 0.16, 0.10);
  float jaw = sdEllipsoid(jw, vec3(0.55, 0.50 + uMouthOpen * 0.05, 0.66));
  float head = smin(skull, jaw, 0.40);

  // cheekbones
  head = smin(head, sdEllipsoid(q - vec3( 0.52, -0.10, 0.46), vec3(0.30, 0.24, 0.28)), 0.30);
  head = smin(head, sdEllipsoid(q - vec3(-0.52, -0.10, 0.46), vec3(0.30, 0.24, 0.28)), 0.30);

  // brow ridge
  head = smin(head, sdEllipsoid(q - vec3(0.0, 0.20, 0.72), vec3(0.56, 0.12, 0.24)), 0.22);

  // No nose, no lips, no eyeballs. At this fidelity literal anatomy reads as a
  // death mask; the face is instead described by light inlaid into a dark shell.
  // Surface depths were measured from the SDF: eye z~0.898, mouth z~0.907.

  float lid  = 1.0 - uBlink;
  float tilt = uBrowTilt * 0.30;
  vec2  gaze = vec2(sin(uTime * 0.53) * 0.022, cos(uTime * 0.37) * 0.012) * (1.0 - uListen * 0.7);

  float mw = 0.115 + uMouthWide * 0.105;
  float mh = 0.016 + uMouthOpen * 0.135;

  // Recess the shell where the light sits, so the elements read as inlaid
  // rather than stuck on. Done before res is taken.
  head = smax(head, -sdEllipsoid(q - vec3(0.0, -0.45, 0.945), vec3(mw * 1.30, mh * 1.45, 0.085)), 0.05);
  head = smax(head, -sdEllipsoid(q - vec3( 0.33, 0.05, 0.935), vec3(0.175, 0.090, 0.075)), 0.06);
  head = smax(head, -sdEllipsoid(q - vec3(-0.33, 0.05, 0.935), vec3(0.175, 0.090, 0.075)), 0.06);

  vec2 res = vec2(head, 1.0);

  // ---- eye slits: emissive lenses that tilt with emotion and close on blink ----
  vec3 eL = q - vec3( 0.33 + gaze.x, 0.05 + gaze.y, 0.872); eL.xy *= rot(-tilt);
  vec3 eR = q - vec3(-0.33 + gaze.x, 0.05 + gaze.y, 0.872); eR.xy *= rot( tilt);
  float eh = mix(0.018, 0.068, lid);
  float eye = min(sdEllipsoid(eL, vec3(0.150, eh, 0.058)),
                  sdEllipsoid(eR, vec3(0.150, eh, 0.058)));
  if (eye < res.x) res = vec2(eye, 3.0);

  // ---- mouth: a luminous bar whose span and aperture follow the viseme ----
  float mouth = sdEllipsoid(q - vec3(0.0, -0.45, 0.882), vec3(mw, mh, 0.058));
  if (mouth < res.x) res = vec2(mouth, 3.0);

  return res;
}

vec3 calcNormal(vec3 p) {
  vec2 e = vec2(1.0, -1.0) * 0.0008;
  return normalize(e.xyy * map(p + e.xyy).x + e.yyx * map(p + e.yyx).x +
                   e.yxy * map(p + e.yxy).x + e.xxx * map(p + e.xxx).x);
}

float softShadow(vec3 ro, vec3 rd) {
  float res = 1.0, t = 0.04;
  for (int i = 0; i < 24; i++) {
    float h = map(ro + rd * t).x;
    res = min(res, 10.0 * h / t);
    t += clamp(h, 0.02, 0.20);
    if (res < 0.005 || t > 3.0) break;
  }
  return clamp(res, 0.0, 1.0);
}

float ao(vec3 p, vec3 n) {
  float occ = 0.0, sca = 1.0;
  for (int i = 0; i < 5; i++) {
    float h = 0.02 + 0.10 * float(i);
    occ += (h - map(p + n * h).x) * sca;
    sca *= 0.72;
  }
  return clamp(1.0 - 2.4 * occ, 0.0, 1.0);
}

void main() {
  vec2 uv = vUv;
  uv.x *= uRes.x / uRes.y;

  vec3 ro = vec3(0.0, 0.04, 3.55);
  vec3 rd = normalize(vec3(uv * 0.50, -1.0));

  float t = 0.0;
  vec2 hit = vec2(-1.0);
  for (int i = 0; i < MAX_STEPS; i++) {
    vec3 p = ro + rd * t;
    vec2 d = map(p);
    if (d.x < SURF) { hit = vec2(t, d.y); break; }
    t += d.x * 0.85;
    if (t > FAR) break;
  }

  vec3 col = vec3(0.0);
  float alpha = 0.0;

  if (hit.y > 0.0) {
    vec3 p = ro + rd * hit.x;
    vec3 n = calcNormal(p);
    vec3 v = -rd;

    vec3 keyDir  = normalize(vec3(-0.55, 0.72, 0.85));
    vec3 fillDir = normalize(vec3(0.85, -0.10, 0.40));
    vec3 rimDir  = normalize(vec3(0.20, 0.35, -1.0));

    float key  = clamp(dot(n, keyDir), 0.0, 1.0);
    float fill = clamp(dot(n, fillDir), 0.0, 1.0);
    float rim  = pow(clamp(1.0 - dot(n, v), 0.0, 1.0), 2.6);
    float fres = pow(clamp(1.0 - dot(n, v), 0.0, 1.0), 5.0);
    float sh   = softShadow(p + n * 0.01, keyDir);
    float occ  = ao(p, n);

    vec3 base;
    vec3 emissive = vec3(0.0);
    float spec = 0.0;

    if (hit.y < 1.5) {
      // Dark tinted glass. The form is described almost entirely by rim light,
      // internal bleed and specular — the diffuse term stays near black so the
      // silhouette reads as volume rather than a lit solid.
      base = uTint * 0.055;

      // subsurface bleed — light carried through the thin edges of the form
      float sss = pow(clamp(dot(n, -keyDir) * 0.5 + 0.5, 0.0, 1.0), 2.6);
      emissive += uTint * sss * 0.10;

      // interference sheen, so the surface shifts hue as it curves
      float band = sin(n.y * 6.0 + n.x * 3.0 + uTime * 0.35) * 0.5 + 0.5;
      emissive += mix(uTint, uTint.brg, band) * 0.030;

      // fine grain so it reads as material, not plastic
      base += (noise(p * 46.0) - 0.5) * 0.012;
      vec3 h = normalize(keyDir + v);
      spec = pow(clamp(dot(n, h), 0.0, 1.0), 90.0) * 0.42;
    } else if (hit.y < 3.5) {
      // eyes and mouth — genuine light sources, pulsing with thought and speech
      float pulse = 0.60 + 0.40 * sin(uTime * 2.6);
      float energy = 1.20 + uThink * pulse * 0.7 + uSpeak * 0.6 + uLevel * 0.9;
      base = uTint * 0.05;
      // hot core falling off to a tinted corona
      float core = pow(clamp(dot(n, v), 0.0, 1.0), 2.0);
      emissive += (uTint * 1.30 + vec3(0.10) * core) * energy;
      vec3 h = normalize(keyDir + v);
      spec = pow(clamp(dot(n, h), 0.0, 1.0), 180.0) * 1.4;
    }

    col  = base * (0.22 + 0.85 * key * mix(0.40, 1.0, sh));
    col += base * fill * 0.30;
    col += emissive;
    col += uTint * rim * (0.85 + uSpeak * 0.8 + uLevel * 0.7);
    col += mix(uTint, vec3(1.0), 0.30) * spec * sh;
    col += uTint * fres * 0.45;
    col *= mix(0.45, 1.0, occ);

    alpha = 1.0;
  }

  // volumetric halo around the silhouette
  float glow = exp(-max(t - 2.2, 0.0) * 2.4);
  if (hit.y < 0.0) {
    float d = length(uv);
    float aura = smoothstep(1.05, 0.15, d) * (0.10 + uSpeak * 0.10 + uLevel * 0.14);
    col += uTint * aura;
    alpha = max(alpha, aura * 1.7);
  }
  col += uTint * glow * 0.05;

  // filmic-ish tonemap, then restore the chroma the compression flattens
  col = col / (col + vec3(1.0));
  col = pow(max(col, 0.0), vec3(0.4545));
  float luma = dot(col, vec3(0.2126, 0.7152, 0.0722));
  col = clamp(mix(vec3(luma), col, 1.60), 0.0, 1.0);

  outColor = vec4(col, alpha);
}`;

type Uniforms = Record<string, WebGLUniformLocation | null>;

const VISEMES: Record<string, [number, number]> = {
  // viseme -> [open, wide]
  A: [1.0, 0.45],
  E: [0.34, 0.95],
  I: [0.5, 0.8],
  O: [0.85, 0.12],
  U: [0.45, 0.0],
  MBP: [0.0, 0.42],
  FV: [0.12, 0.5],
  wide: [0.16, 1.0],
  narrow: [0.26, 0.05],
  rest: [0.06, 0.4],
};

const EMOTION_TINT: Record<string, [number, number, number]> = {
  neutral: [0.20, 0.60, 1.0],
  happy: [0.22, 1.0, 0.60],
  sad: [0.42, 0.34, 1.0],
  curious: [1.0, 0.62, 0.16],
  focused: [1.0, 0.34, 0.26],
};

const BROW_TILT: Record<string, number> = {
  neutral: 0,
  happy: -0.55,
  sad: 0.7,
  curious: -0.3,
  focused: 0.45,
};

export class WebGLAvatarRenderer {
  private canvas: HTMLCanvasElement | null = null;
  private gl: WebGL2RenderingContext | null = null;
  private program: WebGLProgram | null = null;
  private u: Uniforms = {};
  private raf: number | null = null;
  private ro: ResizeObserver | null = null;

  private state: AvatarStateEvent = { s: "idle", e: "neutral", i: 1, t: 0 };
  private emotion = "neutral";
  private viseme = "rest";
  private visemeTimer: any = null;

  // eased values
  private mouthOpen = 0.06;
  private mouthWide = 0.4;
  private browTilt = 0;
  private blink = 0;
  private level = 0;
  private think = 0;
  private speak = 0;
  private listen = 0;
  private tint: [number, number, number] = [0.42, 0.68, 1.0];

  private blinkTimer = 0;
  private blinkPhase = -1;
  private last = 0;

  /** True when WebGL2 initialised; callers can fall back if not. */
  supported = false;

  async mount(el: HTMLElement) {
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.display = "block";
    el.appendChild(canvas);
    this.canvas = canvas;

    const gl = canvas.getContext("webgl2", {
      alpha: true,
      antialias: true,
      premultipliedAlpha: false,
    });
    if (!gl) {
      console.warn("[Avatar] WebGL2 unavailable — 3D renderer disabled.");
      return;
    }
    this.gl = gl;

    const program = this.link(gl, VERT, FRAG);
    if (!program) return;
    this.program = program;
    gl.useProgram(program);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]),
      gl.STATIC_DRAW
    );
    const loc = gl.getAttribLocation(program, "aPos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    for (const name of [
      "uRes", "uTime", "uMouthOpen", "uMouthWide", "uBrowTilt",
      "uBlink", "uLevel", "uThink", "uSpeak", "uListen", "uTint",
    ]) {
      this.u[name] = gl.getUniformLocation(program, name);
    }

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    this.resize();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(el);

    this.supported = true;
    this.loop(0);
  }

  private link(gl: WebGL2RenderingContext, vs: string, fs: string): WebGLProgram | null {
    const compile = (type: number, src: string) => {
      const sh = gl.createShader(type)!;
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        console.error("[Avatar] shader compile failed:", gl.getShaderInfoLog(sh));
        return null;
      }
      return sh;
    };
    const v = compile(gl.VERTEX_SHADER, vs);
    const f = compile(gl.FRAGMENT_SHADER, fs);
    if (!v || !f) return null;
    const p = gl.createProgram()!;
    gl.attachShader(p, v);
    gl.attachShader(p, f);
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      console.error("[Avatar] program link failed:", gl.getProgramInfoLog(p));
      return null;
    }
    return p;
  }

  private resize() {
    if (!this.canvas || !this.gl) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.floor(this.canvas.clientWidth * dpr));
    const h = Math.max(1, Math.floor(this.canvas.clientHeight * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
      this.gl.viewport(0, 0, w, h);
    }
  }

  applyState(e: AvatarStateEvent) {
    this.state = e;
    this.emotion = e.e || "neutral";
    this.triggerBlink();
  }

  applyViseme(viseme: string, durationMs: number) {
    this.viseme = viseme;
    if (this.visemeTimer) clearTimeout(this.visemeTimer);
    this.visemeTimer = setTimeout(() => { this.viseme = "rest"; }, durationMs);
  }

  applyEmotion(emotion: string, _intensity: number) {
    this.emotion = emotion;
  }

  /** Drive the rim/iris energy from the client VAD level (0..1). */
  setLevel(v: number) {
    this.level = Math.max(0, Math.min(1, v));
  }

  private triggerBlink() {
    this.blinkPhase = 0;
  }

  private loop = (ts: number) => {
    const dt = Math.min(64, ts - this.last) || 16;
    this.last = ts;
    this.update(dt);
    this.draw(ts);
    this.raf = requestAnimationFrame(this.loop);
  };

  private update(dt: number) {
    const s = this.state.s;

    // blinks: state-triggered plus a natural random cadence
    this.blinkTimer += dt;
    if (this.blinkTimer > 2800 + Math.random() * 3800) {
      this.triggerBlink();
      this.blinkTimer = 0;
    }
    if (this.blinkPhase >= 0) {
      this.blinkPhase += dt / 105;
      this.blink = this.blinkPhase < 1 ? Math.sin(this.blinkPhase * Math.PI) : 0;
      if (this.blinkPhase >= 1) this.blinkPhase = -1;
    }

    let [tOpen, tWide] = VISEMES[this.viseme] || VISEMES.rest;
    if (s !== "speaking") {
      tOpen = s === "thinking" ? 0.03 : 0.06;
      tWide = s === "thinking" ? 0.25 : 0.4;
    }

    const k = 1 - Math.pow(0.0016, dt / 1000); // frame-rate independent easing
    this.mouthOpen += (tOpen - this.mouthOpen) * k;
    this.mouthWide += (tWide - this.mouthWide) * k;

    const tBrow = BROW_TILT[this.emotion] ?? 0;
    this.browTilt += (tBrow - this.browTilt) * (k * 0.5);

    const kk = 1 - Math.pow(0.02, dt / 1000);
    this.think += ((s === "thinking" || s === "tool_using" ? 1 : 0) - this.think) * kk;
    this.speak += ((s === "speaking" ? 1 : 0) - this.speak) * kk;
    this.listen += ((s === "listening" ? 1 : 0) - this.listen) * kk;
    this.level += (0 - this.level) * (kk * 0.35); // decay unless refreshed

    const target = EMOTION_TINT[this.emotion] || EMOTION_TINT.neutral;
    for (let i = 0; i < 3; i++) {
      this.tint[i] += (target[i] - this.tint[i]) * (kk * 0.6);
    }
  }

  private draw(ts: number) {
    const gl = this.gl;
    if (!gl || !this.program) return;
    this.resize();
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.program);
    gl.uniform2f(this.u.uRes!, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.uniform1f(this.u.uTime!, ts / 1000);
    gl.uniform1f(this.u.uMouthOpen!, this.mouthOpen);
    gl.uniform1f(this.u.uMouthWide!, this.mouthWide);
    gl.uniform1f(this.u.uBrowTilt!, this.browTilt);
    gl.uniform1f(this.u.uBlink!, this.blink);
    gl.uniform1f(this.u.uLevel!, this.level);
    gl.uniform1f(this.u.uThink!, this.think);
    gl.uniform1f(this.u.uSpeak!, this.speak);
    gl.uniform1f(this.u.uListen!, this.listen);
    gl.uniform3f(this.u.uTint!, this.tint[0], this.tint[1], this.tint[2]);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  unmount() {
    if (this.raf) cancelAnimationFrame(this.raf);
    if (this.visemeTimer) clearTimeout(this.visemeTimer);
    this.ro?.disconnect();
    this.canvas?.remove();
    this.canvas = null;
    this.gl = null;
  }
}
