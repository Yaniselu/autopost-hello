// Cinematic 3D scene: a laptop + phone (built from code, no third-party models),
// liquid glass overlays, kinetic typography. Driven frame-by-frame from Node.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { drawLaptop, drawPhone } from "./screens.js";

const $ = (id) => document.getElementById(id);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, k) => a + (b - a) * k;
const ease = (x) => 1 - Math.pow(1 - clamp(x), 3);
const inOut = (x) => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const back = (x) => { x = clamp(x); const c1 = 1.4, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };
function mulberry(seed) { return () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const words = (s) => String(s || "").replace(/\*/g, "").split(/\s+/).filter(Boolean).length;

let J, W, H, rnd, renderer, composer, bloom, scene, camera;
let laptop, phone, lapCanvas, lapTex, phoneCanvas, phoneTex, bokeh = [], dust, shadowL, shadowP, TL;
let currentSection = null;
const grainOffsets = [];

// ===================================================================== setup
async function setup(job) {
  J = job; W = job.width; H = job.height; rnd = mulberry(job.seed || 1);
  const stage = $("stage");
  stage.style.setProperty("--w", W + "px"); stage.style.setProperty("--h", H + "px");
  document.documentElement.style.setProperty("--accent", job.palette.accent);
  document.documentElement.style.setProperty("--accent2", job.palette.accent2);
  await Promise.all(["800 40px Inter", "700 40px Inter", "500 40px Inter"].map((f) => document.fonts.load(f)));
  // real account images (logo + latest posts) for the profile screen
  const loadImg = (src) => new Promise((res) => { if (!src) return res(null); const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; });
  const acc = job.account || {};
  J._img = { avatar: await loadImg(acc.avatar), mark: await loadImg(acc.logo_mark), grid: (await Promise.all((acc.grid || []).map(loadImg))).filter(Boolean) };

  // reels: render the 3D at reduced size (fast in software GL); text is composited later at full res
  const sc = job.mode === "reel" ? (job.render_scale || 0.6667) : 1;
  const RW = Math.round((W * sc) / 2) * 2, RH = Math.round((H * sc) / 2) * 2;
  const canvas = $("gl"); canvas.width = RW; canvas.height = RH;
  renderer = new THREE.WebGLRenderer({ canvas, antialias: false, preserveDrawingBuffer: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(1); renderer.setSize(RW, RH, false);
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  scene = new THREE.Scene();
  const pm = new THREE.PMREMGenerator(renderer);
  scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture;
  camera = new THREE.PerspectiveCamera(30, W / H, 0.1, 200);

  buildWorld(job.palette, (job.plan && job.plan.bg) || "bokeh");
  laptop = buildLaptop(job.finish_laptop || job.finish);
  phone = buildPhone(job.finish_phone || job.finish);
  scene.add(laptop.group, phone.group);

  const rt = new THREE.WebGLRenderTarget(RW, RH, { type: THREE.HalfFloatType, samples: job.msaa ?? 2 });
  composer = new EffectComposer(renderer, rt);
  composer.addPass(new RenderPass(scene, camera));
  bloom = new UnrealBloomPass(new THREE.Vector2(RW / 2, RH / 2), 0.42, 0.5, 0.94);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  // film grain
  const gc = document.createElement("canvas"); gc.width = gc.height = 256;
  const gx = gc.getContext("2d"); const id = gx.createImageData(256, 256);
  for (let i = 0; i < id.data.length; i += 4) { const v = Math.random() * 255; id.data[i] = id.data[i + 1] = id.data[i + 2] = v; id.data[i + 3] = 255; }
  gx.putImageData(id, 0, 0);
  $("grain").style.backgroundImage = `url(${gc.toDataURL()})`;
  for (let i = 0; i < 64; i++) grainOffsets.push([Math.floor(rnd() * 256), Math.floor(rnd() * 256)]);

  $("handle").textContent = job.brand.handle;
  if (job.mode === "reel") { TL = buildTimeline(job.reel); $("ui").style.display = "none"; }
  else { $("ui").style.display = "none"; $("still").style.display = "block"; }
  return TL || null;
}

// ===================================================================== world
function radialTexture(inner = "rgba(255,255,255,1)", outer = "rgba(255,255,255,0)", size = 256) {
  const c = document.createElement("canvas"); c.width = c.height = size;
  const x = c.getContext("2d"); const g = x.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, inner); g.addColorStop(1, outer); x.fillStyle = g; x.fillRect(0, 0, size, size);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

function buildWorld(pal, variant) {
  const bg = new THREE.Mesh(new THREE.SphereGeometry(80, 32, 16), new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false,
    uniforms: { top: { value: new THREE.Color(pal.bg[1]) }, bottom: { value: new THREE.Color(pal.bg[0]) } },
    vertexShader: "varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.); }",
    fragmentShader: "uniform vec3 top; uniform vec3 bottom; varying vec3 vP; void main(){ float h = vP.y*.5+.5; gl_FragColor = vec4(mix(bottom, top, smoothstep(.35,.85,h)), 1.); }",
  }));
  scene.add(bg);

  const tex = radialTexture();
  const glows = pal.glow.length ? pal.glow : [pal.accent, pal.accent2];
  const nBokeh = variant === "bokeh" ? 16 : variant === "grid" ? 7 : 4;
  for (let i = 0; i < nBokeh; i++) {
    const m = new THREE.SpriteMaterial({ map: tex, color: new THREE.Color(glows[i % glows.length]), blending: THREE.AdditiveBlending,
      transparent: true, depthWrite: false, opacity: 0.18 + rnd() * 0.3 });
    const s = new THREE.Sprite(m);
    const base = new THREE.Vector3((rnd() - 0.5) * 22, -1 + rnd() * 10, -8 - rnd() * 14);
    const sc = 1.5 + rnd() * 6; s.scale.set(sc, sc, 1);
    s.userData = { base, ph: rnd() * 6.28, sp: 0.15 + rnd() * 0.3 };
    bokeh.push(s); scene.add(s);
  }

  const n = 420, pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { pos[i * 3] = (rnd() - 0.5) * 16; pos[i * 3 + 1] = rnd() * 9; pos[i * 3 + 2] = (rnd() - 0.6) * 14; }
  const dg = new THREE.BufferGeometry(); dg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  dust = new THREE.Points(dg, new THREE.PointsMaterial({ size: 0.035, map: radialTexture(), transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending, opacity: 0.55, color: 0xffffff }));
  dust.userData.base = pos.slice();
  scene.add(dust);

  // dark studio floor: soft pool of light in the middle fading into the background colour
  const fc = document.createElement("canvas"); fc.width = fc.height = 512; const fx = fc.getContext("2d");
  const bgc = new THREE.Color(pal.bg[0]), glowc = new THREE.Color(pal.bg[1]).lerp(new THREE.Color(pal.accent2), 0.15);
  const fg = fx.createRadialGradient(256, 256, 0, 256, 256, 256);
  fg.addColorStop(0, `#${glowc.clone().multiplyScalar(0.28).getHexString()}`); fg.addColorStop(0.45, `#${glowc.clone().multiplyScalar(0.09).getHexString()}`);
  fg.addColorStop(1, `#${bgc.getHexString()}`); fx.fillStyle = fg; fx.fillRect(0, 0, 512, 512);
  if (variant === "grid") { // glowing tech grid fading out with distance
    fx.strokeStyle = pal.accent; fx.lineWidth = 1.2;
    for (let i = 0; i <= 512; i += 16) {
      const a = Math.max(0, 1 - Math.abs(i - 256) / 256) * 0.3;
      fx.globalAlpha = a; fx.beginPath(); fx.moveTo(i, 0); fx.lineTo(i, 512); fx.stroke(); fx.beginPath(); fx.moveTo(0, i); fx.lineTo(512, i); fx.stroke();
    }
    fx.globalAlpha = 1;
  }
  const ftex = new THREE.CanvasTexture(fc); ftex.colorSpace = THREE.SRGBColorSpace;
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.MeshBasicMaterial({ map: ftex }));
  floor.rotation.x = -Math.PI / 2; scene.add(floor);

  if (variant === "spot") { // volumetric light cone from above
    const cc = document.createElement("canvas"); cc.width = 256; cc.height = 512; const cx = cc.getContext("2d");
    const lg = cx.createLinearGradient(0, 0, 0, 512); lg.addColorStop(0, "rgba(255,255,255,.55)"); lg.addColorStop(1, "rgba(255,255,255,0)");
    cx.fillStyle = lg; cx.beginPath(); cx.moveTo(110, 0); cx.lineTo(146, 0); cx.lineTo(256, 512); cx.lineTo(0, 512); cx.closePath(); cx.fill();
    const ct = new THREE.CanvasTexture(cc);
    const cone = new THREE.Mesh(new THREE.PlaneGeometry(9, 14), new THREE.MeshBasicMaterial({ map: ct, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, color: new THREE.Color(pal.accent).lerp(new THREE.Color(0xffffff), 0.6), opacity: 0.35 }));
    cone.position.set(0, 6.5, -3.5); scene.add(cone);
  }
  if (variant === "grid") { // horizon glow line
    const hz = new THREE.Mesh(new THREE.PlaneGeometry(60, 0.6), new THREE.MeshBasicMaterial({ map: radialTexture(pal.accent, "rgba(0,0,0,0)"), transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.8 }));
    hz.position.set(0, 0.2, -25); scene.add(hz);
  }
  const sh = radialTexture("rgba(0,0,0,.85)", "rgba(0,0,0,0)");
  shadowL = new THREE.Mesh(new THREE.PlaneGeometry(4.6, 3.4), new THREE.MeshBasicMaterial({ map: sh, transparent: true, depthWrite: false }));
  shadowL.rotation.x = -Math.PI / 2; shadowL.position.y = 0.005; scene.add(shadowL);
  shadowP = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 0.8), new THREE.MeshBasicMaterial({ map: sh, transparent: true, depthWrite: false }));
  shadowP.rotation.x = -Math.PI / 2; shadowP.position.y = 0.006; scene.add(shadowP);

  const key = new THREE.SpotLight(0xffffff, 140, 0, 0.42, 0.9, 2); key.position.set(-3, 9, 7); key.target.position.set(0, 0.8, 0); scene.add(key, key.target);
  const rim1 = new THREE.PointLight(new THREE.Color(pal.accent), 60, 0, 2); rim1.position.set(-4, 3, -3); scene.add(rim1);
  const rim2 = new THREE.PointLight(new THREE.Color(pal.accent2), 60, 0, 2); rim2.position.set(4.5, 2.5, -2.5); scene.add(rim2);
  scene.add(new THREE.AmbientLight(0xffffff, 0.05));
}

// Apple-like colourways (no logos): phone = titanium tones, laptop = space black / silver
const FINISH = {
  natural: { body: 0xa9a49b, back: 0xc9c4ba, plate: 0xb7b2a8 },
  black: { body: 0x3a3a3c, back: 0x2b2b2d, plate: 0x333336 },
  white: { body: 0xd9d7d2, back: 0xeceae6, plate: 0xe0ded9 },
  desert: { body: 0xb79a7c, back: 0xd2b99d, plate: 0xc4a88b },
  blue: { body: 0x47566a, back: 0x5a6a80, plate: 0x4f5e72 },
  graphite: { body: 0x4a4e55, back: 0x2a2c31, plate: 0x23252a },
  silver: { body: 0xa8acb2, back: 0xdcdde0, plate: 0xcfd0d3 },
  spaceblack: { body: 0x2f3033, back: 0x2f3033, plate: 0x2f3033 },
};
function fin(name) { return FINISH[name] || FINISH.silver; }
function metal(finish, rough = 0.34) {
  return new THREE.MeshStandardMaterial({ color: fin(finish).body, metalness: 1, roughness: rough, envMapIntensity: 0.95 });
}

function roundedRect(w, h, r) {
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  return new THREE.ShapeGeometry(s, 12);
}

// brand emblem (the Velosyntech mark) where a manufacturer logo would be
function emblem(size, finish) {
  if (!J._img || !J._img.mark) return null;
  const tex = new THREE.Texture(J._img.mark); tex.colorSpace = THREE.SRGBColorSpace; tex.needsUpdate = true;
  const dark = ["black", "graphite", "spaceblack", "blue"].includes(finish);
  return new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshStandardMaterial({
    map: tex, transparent: true, metalness: 0.95, roughness: 0.12, color: dark ? 0xe8eaee : 0x8a8e95, envMapIntensity: 1.4 }));
}

function buildLaptop(finish) {
  const g = new THREE.Group(), alu = metal(finish);
  const dark = new THREE.MeshStandardMaterial({ color: 0x0c0c0f, roughness: 0.6, metalness: 0.2 });
  const glassBlack = new THREE.MeshStandardMaterial({ color: 0x030304, roughness: 0.06, metalness: 0.6 });
  const base = new THREE.Mesh(new RoundedBoxGeometry(3.0, 0.09, 2.1, 4, 0.04), alu); base.position.y = 0.045; g.add(base);
  const well = new THREE.Mesh(new THREE.PlaneGeometry(2.62, 0.98), dark); well.rotation.x = -Math.PI / 2; well.position.set(0, 0.0905, -0.42); g.add(well);
  const keys = new THREE.InstancedMesh(new RoundedBoxGeometry(0.165, 0.016, 0.15, 1, 0.02), new THREE.MeshStandardMaterial({ color: 0x0d0d10, roughness: 0.55 }), 13 * 5);
  const m = new THREE.Matrix4(); let k = 0;
  for (let r = 0; r < 5; r++) for (let c = 0; c < 13; c++) { m.makeTranslation(-1.2 + c * 0.2, 0.097, -0.82 + r * 0.19); keys.setMatrixAt(k++, m); }
  g.add(keys);
  const pad = new THREE.Mesh(new RoundedBoxGeometry(1.25, 0.006, 0.74, 2, 0.003), new THREE.MeshStandardMaterial({ color: fin(finish).body, metalness: 1, roughness: 0.16 }));
  pad.position.set(0, 0.09, 0.56); g.add(pad);
  // speaker grilles (dotted strips either side of the keyboard)
  const gc = document.createElement("canvas"); gc.width = 64; gc.height = 512; const gx = gc.getContext("2d");
  gx.fillStyle = "#000"; for (let y = 4; y < 512; y += 9) for (let x = 6; x < 64; x += 11) { gx.beginPath(); gx.arc(x + (y % 18 ? 5 : 0), y, 1.8, 0, 7); gx.fill(); }
  const gt = new THREE.CanvasTexture(gc);
  [-1.37, 1.37].forEach((x) => { const sp = new THREE.Mesh(new THREE.PlaneGeometry(0.16, 0.95), new THREE.MeshBasicMaterial({ map: gt, transparent: true, opacity: 0.55 }));
    sp.rotation.x = -Math.PI / 2; sp.position.set(x, 0.0906, -0.42); g.add(sp); });
  const hinge = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 2.5, 16), new THREE.MeshStandardMaterial({ color: 0x111114, roughness: 0.4, metalness: 0.6 }));
  hinge.rotation.z = Math.PI / 2; hinge.position.set(0, 0.09, -1.03); g.add(hinge);

  const lidPivot = new THREE.Group(); lidPivot.position.set(0, 0.09, -1.03); g.add(lidPivot);
  const lid = new THREE.Mesh(new RoundedBoxGeometry(3.0, 2.02, 0.05, 4, 0.024), alu); lid.position.set(0, 1.01, 0); lidPivot.add(lid);
  const em = emblem(0.62, finish); if (em) { em.position.set(0, 1.03, -0.0262); em.rotation.y = Math.PI; lidPivot.add(em); }
  const bezel = new THREE.Mesh(roundedRect(2.95, 1.97, 0.07), glassBlack); bezel.position.set(0, 1.01, 0.0256); lidPivot.add(bezel);
  lapCanvas = document.createElement("canvas"); lapCanvas.width = 1024; lapCanvas.height = 640;
  lapTex = new THREE.CanvasTexture(lapCanvas); lapTex.colorSpace = THREE.SRGBColorSpace; lapTex.generateMipmaps = false; lapTex.minFilter = THREE.LinearFilter;
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(2.8, 1.75), new THREE.MeshBasicMaterial({ map: lapTex, toneMapped: false }));
  screen.position.set(0, 1.05, 0.0262); lidPivot.add(screen);
  const sheen = new THREE.Mesh(new THREE.PlaneGeometry(2.8, 1.75), new THREE.MeshStandardMaterial({ color: 0x000000, roughness: 0.05, metalness: 1, transparent: true, opacity: 0.18 }));
  sheen.position.set(0, 1.05, 0.0266); lidPivot.add(sheen);
  lidPivot.rotation.x = -0.3;
  return { group: g, lidPivot };
}

function buildPhone(finish) {
  const g = new THREE.Group(), frame = metal(finish);
  frame.roughness = 0.24;
  const glassBlack = new THREE.MeshStandardMaterial({ color: 0x020203, roughness: 0.05, metalness: 0.6 });
  const body = new THREE.Mesh(new RoundedBoxGeometry(0.76, 1.56, 0.085, 6, 0.1), frame); g.add(body);
  const front = new THREE.Mesh(roundedRect(0.735, 1.535, 0.1), glassBlack); front.position.z = 0.0428; g.add(front);
  phoneCanvas = document.createElement("canvas"); phoneCanvas.width = 480; phoneCanvas.height = 1029;
  phoneTex = new THREE.CanvasTexture(phoneCanvas); phoneTex.colorSpace = THREE.SRGBColorSpace; phoneTex.generateMipmaps = false; phoneTex.minFilter = THREE.LinearFilter;
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.705, 1.51), new THREE.MeshBasicMaterial({ map: phoneTex, toneMapped: false }));
  screen.position.z = 0.0432; g.add(screen);
  const backGlass = new THREE.Mesh(roundedRect(0.735, 1.535, 0.1), new THREE.MeshStandardMaterial({ color: fin(finish).back, roughness: 0.42, metalness: 0.25 }));
  backGlass.position.z = -0.0428; backGlass.rotation.y = Math.PI; g.add(backGlass);
  const pem = emblem(0.26, finish); if (pem) { pem.position.set(0, -0.02, -0.0432); pem.rotation.y = Math.PI; g.add(pem); }
  const bump = new THREE.Mesh(new RoundedBoxGeometry(0.36, 0.36, 0.03, 3, 0.08), new THREE.MeshStandardMaterial({ color: fin(finish).plate, roughness: 0.12, metalness: 0.55 }));
  bump.position.set(0.165, 0.555, -0.055); g.add(bump);
  const flash = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.034, 20), new THREE.MeshStandardMaterial({ color: 0xfff4dc, emissive: 0x3a3428, roughness: 0.3 }));
  flash.rotation.x = Math.PI / 2; flash.position.set(0.255, 0.66, -0.07); g.add(flash);
  const lidar = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.034, 16), new THREE.MeshStandardMaterial({ color: 0x050507, roughness: 0.2 }));
  lidar.rotation.x = Math.PI / 2; lidar.position.set(0.255, 0.45, -0.07); g.add(lidar);
  const lensMat = new THREE.MeshStandardMaterial({ color: 0x05060a, roughness: 0.02, metalness: 0.9 });
  const ringMat = frame;
  [[0.083, 0.645], [0.083, 0.465], [0.235, 0.555]].forEach(([x, y]) => {
    const ring = new THREE.Mesh(new THREE.CylinderGeometry(0.068, 0.068, 0.04, 32), ringMat); ring.rotation.x = Math.PI / 2; ring.position.set(x, y, -0.072); g.add(ring);
    const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.052, 0.052, 0.042, 32), lensMat); lens.rotation.x = Math.PI / 2; lens.position.set(x, y, -0.073); g.add(lens);
    const glint = new THREE.Mesh(new THREE.CircleGeometry(0.02, 16), new THREE.MeshBasicMaterial({ color: 0x3a4a8a, transparent: true, opacity: 0.6 }));
    glint.position.set(x - 0.012, y + 0.012, -0.0945); glint.rotation.y = Math.PI; g.add(glint);
  });
  [[0.39, 0.35, 0.18], [-0.39, 0.42, 0.1], [-0.39, 0.25, 0.14]].forEach(([x, y, h]) => {
    const b = new THREE.Mesh(new RoundedBoxGeometry(0.02, h, 0.035, 2, 0.008), frame); b.position.set(x, y, 0); g.add(b);
  });
  return { group: g };
}

// ===================================================================== reel timeline
function buildTimeline(r) {
  const hook = Math.max(2.6, 1.4 + words(r.hook) * 0.22);
  const problem = Math.max(3.8, 2.2 + words(r.problem.text) * 0.22);
  const steps = r.solution.steps.map((s) => Math.max(2.1, 1.2 + (words(s.title) + words(s.text)) * 0.17));
  const solution = 0.7 + steps.reduce((a, b) => a + b, 0);
  const result = Math.max(2.8, 1.6 + words(r.result) * 0.2);
  const cta = 3.0;
  const S = {}; let t = 0;
  for (const [k, d] of [["hook", hook], ["problem", problem], ["solution", solution], ["result", result], ["cta", cta]]) { S[k] = { start: t, dur: d }; t += d; }
  const stepTimes = []; let st = S.solution.start + 0.7;
  steps.forEach((d) => { stepTimes.push({ start: st, dur: d }); st += d; });
  const cues = [[0, "impact"], [0.05, "whoosh"]];
  cues.push([S.problem.start - 0.25, "whoosh"], [S.problem.start + 0.1, "glitch"]);
  (r.problem.alerts || []).slice(0, 3).forEach((_, i) => cues.push([S.problem.start + 0.4 + i * 0.55, "alert"]));
  cues.push([S.solution.start - 0.25, "whoosh"]);
  stepTimes.forEach((s) => cues.push([s.start, "pop"], [s.start + 0.35, "tick"]));
  cues.push([S.result.start - 0.25, "whoosh"], [S.result.start + 0.2, "chime"]);
  cues.push([S.cta.start - 1.0, "riser"], [S.cta.start, "impact"], [S.cta.start + 0.6, "pop"]);
  return { total: +t.toFixed(2), sections: S, steps: stepTimes, cues };
}

// ===================================================================== per-frame
function place(obj, x, y, z, rx = 0, ry = 0, rz = 0) { obj.position.set(x, y, z); obj.rotation.set(rx, ry, rz); }

function lookFrom(px, py, pz, tx, ty, tz, t, shake = 1) {
  camera.position.set(px + Math.sin(t * 1.3) * 0.035 * shake, py + Math.sin(t * 1.7 + 1) * 0.025 * shake, pz);
  camera.lookAt(tx + Math.sin(t * 0.9) * 0.015 * shake, ty, tz);
}

function animateWorld(t) {
  bokeh.forEach((s) => { const u = s.userData; s.position.set(u.base.x + Math.sin(t * u.sp + u.ph) * 1.2, u.base.y + Math.cos(t * u.sp * 0.8 + u.ph) * 0.7, u.base.z); });
  const p = dust.geometry.attributes.position, b = dust.userData.base;
  for (let i = 0; i < p.count; i++) { p.array[i * 3 + 1] = (b[i * 3 + 1] + t * 0.12) % 9; p.array[i * 3] = b[i * 3] + Math.sin(t * 0.3 + i) * 0.1; }
  p.needsUpdate = true;
}

function screens(lapState, phoneState, lt) {
  if (window.__noScreens) return;
  const base = { pal: J.palette, brand: J.brand, account: J.account || {}, img: J._img || {} };
  // screens are drawn in a fixed design space (1280x800 / 600x1286) and scaled to the canvas
  if (lapState) { const c = lapCanvas.getContext("2d"); c.setTransform(lapCanvas.width / 1280, 0, 0, lapCanvas.height / 800, 0, 0); drawLaptop(c, 1280, 800, { ...base, ...lapState }, lapState.t ?? lt); lapTex.needsUpdate = true; }
  if (phoneState) { const c = phoneCanvas.getContext("2d"); c.setTransform(phoneCanvas.width / 600, 0, 0, phoneCanvas.height / 1286, 0, 0); drawPhone(c, 600, 1286, { ...base, ...phoneState }, phoneState.t ?? lt); phoneTex.needsUpdate = true; }
}

// Every section has several camera/staging variants; Python's "director" picks one per video.
const SHOTS = {
  hook: {
    drop_spin(lt, dur, t, d) {
      const k = back(lt / 0.95);
      show(false, true);
      place(phone.group, 0, lerp(3.2, 1.0, k) + Math.sin(t * 1.6) * 0.03, 0, lerp(0.6, 0.06, ease(lt / 1.0)), lerp(-2.8, -0.22, ease(lt / 1.1)) + Math.sin(t * 0.8) * 0.04);
      shadowP.position.set(0, 0.006, 0.1); shadowP.scale.setScalar(0.6 + 0.4 * k);
      lookFrom(0, 1.25, lerp(5.6, 5.0, inOut(lt / dur)), 0, 1.3, 0, t);
      screens(null, { mode: "lock", data: d }, lt);
    },
    rise_turn(lt, dur, t, d) { // phone rises showing its back, turns to reveal the screen
      show(false, true);
      const k = inOut(lt / 1.3);
      place(phone.group, 0, lerp(-0.6, 0.95, ease(lt / 1.0)), 0, 0.05, lerp(Math.PI, -0.18, k));
      shadowP.position.set(0, 0.006, 0.05); shadowP.scale.setScalar(clamp(lt / 0.8));
      lookFrom(-0.25, 0.9, lerp(4.6, 5.2, inOut(lt / dur)), 0, 1.25, 0, t);
      screens(null, { mode: "lock", data: d }, lt);
    },
    lid_open(lt, dur, t, d) { // laptop opens towards the camera
      show(true, false);
      laptop.lidPivot.rotation.x = lerp(1.5, -0.3, inOut(lt / 1.4));
      place(laptop.group, 0, 0, 0, 0, 0);
      shadowL.position.set(0, 0.005, -0.1);
      lookFrom(0, lerp(4.2, 2.9, inOut(lt / dur)), lerp(9.5, 8.6, inOut(lt / dur)), 0, 0.15, -0.5, t);
      screens({ mode: "problem", data: d, t: lt }, null, lt);
    },
    macro_pull(lt, dur, t, d) { // starts on the phone screen, pulls back to reveal the device
      show(false, true);
      place(phone.group, 0, 1.0, 0, 0.02, -0.1 + Math.sin(t * 0.8) * 0.03);
      shadowP.position.set(0, 0.006, 0.05);
      lookFrom(0.05, 1.1, lerp(1.6, 5.3, inOut(lt / (dur * 0.9))), 0, lerp(1.05, 1.32, inOut(lt / dur)), 0, t, 0.5);
      screens(null, { mode: "lock", data: d }, lt);
    },
  },
  problem: {
    orbit_left(lt, dur, t, d) {
      show(true, true);
      laptop.lidPivot.rotation.x = lerp(1.45, -0.3, inOut(lt / 0.9));
      place(laptop.group, 0, 0, 0, 0, 0.08); place(phone.group, 2.05, 0.78, -0.7, 0, -0.55);
      shadowL.position.set(0, 0.005, -0.1); shadowP.position.set(2.05, 0.006, -0.68); shadowP.scale.setScalar(1);
      const a = lerp(-0.5, -0.12, inOut(lt / dur)), r0 = lerp(12.5, 10.2, inOut(lt / dur));
      lookFrom(Math.sin(a) * r0, 2.4, Math.cos(a) * r0, 0.15, 1.55, -0.6, t);
      screens({ mode: "problem", data: d, t: lt }, { mode: "lock", data: d, t: lt + 2 }, lt);
    },
    high_angle(lt, dur, t, d) { // looking down on a desk: laptop + phone lying flat
      show(true, true);
      laptop.lidPivot.rotation.x = -0.35;
      place(laptop.group, -0.2, 0, 0, 0, 0.12); place(phone.group, 1.85, 0.045, 0.75, -Math.PI / 2, 0, 0.35);
      shadowL.position.set(-0.2, 0.005, -0.1); shadowP.position.set(1.85, 0.006, 0.75);
      const r0 = lerp(15.5, 13.5, inOut(lt / dur));
      lookFrom(lerp(1.4, 0.4, inOut(lt / dur)), r0 * 0.72, r0 * 0.7, 0.3, 0.1, -0.2, t, 0.6);
      screens({ mode: "problem", data: d, t: lt }, { mode: "lock", data: d, t: lt + 2 }, lt);
    },
    screen_push(lt, dur, t, d) { // slow push into the laptop screen
      show(true, false);
      laptop.lidPivot.rotation.x = -0.3;
      place(laptop.group, 0, 0, 0, 0, 0);
      shadowL.position.set(0, 0.005, -0.1);
      lookFrom(lerp(0.6, 0.1, inOut(lt / dur)), lerp(2.2, 1.7, inOut(lt / dur)), lerp(10.5, 7.2, inOut(lt / dur)), 0, lerp(1.3, 1.2, inOut(lt / dur)), -1.2, t);
      screens({ mode: "problem", data: d, t: lt }, null, lt);
    },
  },
  solution: {
    orbit_right(lt, dur, t, d) {
      show(true, true);
      laptop.lidPivot.rotation.x = -0.3;
      place(laptop.group, 0, 0, 0, 0, -0.12); place(phone.group, -2.1, 0.78, -0.8, 0, 0.5);
      shadowL.position.set(0, 0.005, -0.1); shadowP.position.set(-2.1, 0.006, -0.78);
      const a = lerp(0.42, 0.12, inOut(lt / dur));
      lookFrom(Math.sin(a) * 11.2, 3.0, Math.cos(a) * 11.2, 0, 0.1, -0.4, t);
      const sh = stepsShown(t);
      screens({ mode: "solution", data: d, stepsShown: sh, stepProgress: sh / Math.max(1, TL.steps.length) }, { mode: "steps", data: d, stepsShown: sh }, lt);
    },
    phone_focus(lt, dur, t, d) { // phone in front showing the checklist, laptop behind
      show(true, true);
      laptop.lidPivot.rotation.x = -0.3;
      place(laptop.group, 0.6, 0, -2.2, 0, -0.25); place(phone.group, -0.25, 0.79, 0.6, 0, lerp(0.35, 0.12, inOut(lt / dur)));
      shadowL.position.set(0.6, 0.005, -2.3); shadowP.position.set(-0.25, 0.006, 0.62);
      lookFrom(lerp(-0.9, -0.3, inOut(lt / dur)), 1.6, 6.9, -0.2, 0.15, 0, t, 0.7);
      const sh = stepsShown(t);
      screens({ mode: "solution", data: d, stepsShown: sh, stepProgress: sh / Math.max(1, TL.steps.length) }, { mode: "steps", data: d, stepsShown: sh }, lt);
    },
    side_track(lt, dur, t, d) { // camera tracks sideways past the laptop
      show(true, true);
      laptop.lidPivot.rotation.x = -0.3;
      place(laptop.group, 0, 0, 0, 0, 0.35); place(phone.group, 2.2, 0.78, 0.3, 0, -0.6);
      shadowL.position.set(0, 0.005, -0.1); shadowP.position.set(2.2, 0.006, 0.32);
      lookFrom(lerp(-3.2, 3.0, inOut(lt / dur)), 2.6, 10.5, lerp(-0.6, 0.6, inOut(lt / dur)), 0.15, -0.3, t, 0.5);
      const sh = stepsShown(t);
      screens({ mode: "solution", data: d, stepsShown: sh, stepProgress: sh / Math.max(1, TL.steps.length) }, { mode: "steps", data: d, stepsShown: sh }, lt);
    },
  },
  result: {
    duo_front(lt, dur, t, d) {
      show(true, true);
      laptop.lidPivot.rotation.x = -0.3;
      place(laptop.group, -0.55, 0, 0, 0, 0.18); place(phone.group, 1.75, 0.78, 0.9, 0, -0.38);
      shadowL.position.set(-0.55, 0.005, -0.1); shadowP.position.set(1.75, 0.006, 0.92);
      lookFrom(0.3, lerp(2.2, 2.7, inOut(lt / dur)), lerp(11.5, 13, inOut(lt / dur)), 0.4, 0.55, 0, t);
      screens({ mode: "solution", data: d, stepsShown: 9, stepProgress: 1 }, { mode: "result", data: d, t: lt }, lt);
    },
    low_hero(lt, dur, t, d) { // low, heroic angle slowly rising
      show(true, true);
      laptop.lidPivot.rotation.x = -0.3;
      place(laptop.group, 0, 0, 0, 0, -0.2); place(phone.group, -1.9, 0.78, 0.8, 0, 0.45);
      shadowL.position.set(0, 0.005, -0.1); shadowP.position.set(-1.9, 0.006, 0.82);
      lookFrom(lerp(1.4, 0.6, inOut(lt / dur)), lerp(0.35, 0.9, inOut(lt / dur)), 11.8, 0, 1.6, -0.3, t, 0.6);
      screens({ mode: "solution", data: d, stepsShown: 9, stepProgress: 1 }, { mode: "result", data: d, t: lt }, lt);
    },
    phone_result(lt, dur, t, d) { // phone close-up with the success screen
      show(false, true);
      place(phone.group, 0, 1.0, 0, 0.03, lerp(-0.45, -0.1, inOut(lt / dur)));
      shadowP.position.set(0, 0.006, 0.05);
      lookFrom(0.4, 1.05, lerp(5.4, 4.8, inOut(lt / dur)), 0, 1.35, 0, t);
      screens(null, { mode: "result", data: d, t: lt }, lt);
    },
  },
  cta: {
    phone_spin(lt, dur, t, d) {
      show(false, true);
      const k = back(lt / 0.8);
      place(phone.group, 0, 1.0 + Math.sin(t * 1.4) * 0.025, 0, 0.04, lerp(0.9, 0, ease(lt / 1.2)) + Math.sin(t * 0.7) * 0.03);
      phone.group.scale.setScalar(0.85 + 0.15 * k);
      shadowP.position.set(0, 0.006, 0.1); shadowP.scale.setScalar(1);
      lookFrom(0, 1.15, lerp(6.2, 5.3, inOut(lt / dur)), 0, 1.12, 0, t, 0.6);
      screens(null, { mode: "profile", data: d, t: lt }, lt);
    },
    duo_cta(lt, dur, t, d) { // phone in front of the open laptop
      show(true, true);
      laptop.lidPivot.rotation.x = -0.3;
      place(laptop.group, 0, 0, -1.6, 0, 0); place(phone.group, 0, 0.82 + Math.sin(t * 1.4) * 0.02, 0.9, 0.04, lerp(-0.6, 0, ease(lt / 1.0)));
      shadowL.position.set(0, 0.005, -1.7); shadowP.position.set(0, 0.006, 0.95);
      lookFrom(0, 1.5, lerp(8.6, 7.6, inOut(lt / dur)), 0, 1.0, 0, t, 0.6);
      screens({ mode: "solution", data: d, stepsShown: 9, stepProgress: 1 }, { mode: "profile", data: d, t: lt }, lt);
    },
  },
};

function show(lap, ph) { laptop.group.visible = lap; shadowL.visible = lap; phone.group.visible = ph; shadowP.visible = ph; }
function stepsShown(t) {
  if (t < TL.steps[0].start) return 0;
  let shown = 0;
  TL.steps.forEach((s, i) => { shown = Math.max(shown, i + clamp((t - s.start - 0.2) / 0.4)); });
  return shown;
}

function renderFrame(t) {
  const S = TL.sections, r = J.reel, plan = J.plan || {};
  const sec = Object.keys(S).find((k) => t >= S[k].start && t < S[k].start + S[k].dur) || "cta";
  const lt = t - S[sec].start, dur = S[sec].dur;
  animateWorld(t);
  const data = { app_name: r.app_name, alerts: r.problem.alerts, steps: r.solution.steps, result: r.result, date_label: J.date_label };
  phone.group.scale.setScalar(1); shadowP.scale.setScalar(1);
  const lib = SHOTS[sec], shot = lib[plan[sec]] || Object.values(lib)[0];
  shot(lt, dur, t, data);
  composer.render();
  return grab();
}

// readPixels + software JPEG encode is far faster than WebGL canvas.toDataURL
let _buf, _c2, _x2;
function grab() {
  const cv = $("gl"), w = cv.width, h = cv.height, gl = renderer.getContext();
  if (!_buf) { _buf = new Uint8ClampedArray(w * h * 4); _c2 = document.createElement("canvas"); _c2.width = w; _c2.height = h; _x2 = _c2.getContext("2d", { willReadFrequently: true }); }
  gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, _buf);
  _x2.putImageData(new ImageData(_buf, w, h), 0, 0);
  return _c2.toDataURL("image/jpeg", 0.94); // note: rows are bottom-up (flipped later)
}

// ===================================================================== stills
function stillScene(kind, i) {
  laptop.group.visible = true; phone.group.visible = true; shadowL.visible = true;
  laptop.lidPivot.rotation.x = -0.3; phone.group.scale.setScalar(1);
  const t = 3 + i * 1.7;
  animateWorld(t);
  const data = { app_name: J.app_name, alerts: J.alerts || [], steps: J.steps || [], result: J.result || "", date_label: J.date_label };
  const tall = H / W > 1.5;
  if (kind === "hero") {
    place(laptop.group, -0.5, 0, 0, 0, 0.2); place(phone.group, 1.6, 0.78, 0.8, 0, -0.42);
    shadowL.position.set(-0.5, 0.005, -0.1); shadowP.position.set(1.6, 0.006, 0.82);
    lookFrom(0.4, 2.8, tall ? 15 : 12.5, 0.35, tall ? 2.4 : 1.75, 0, t, 0);
    screens({ mode: "solution", data, stepsShown: 9, stepProgress: 1 }, { mode: "lock", data, t: 5 }, 5);
  } else if (kind === "phone") {
    laptop.group.visible = false; shadowL.visible = false;
    place(phone.group, 0, 1.0, 0, 0.05, -0.32 + (i % 2) * 0.5);
    shadowP.position.set(0, 0.006, 0.1);
    lookFrom(0.2, 1.2, tall ? 7.4 : 5.9, 0, tall ? 1.78 : 1.3, 0, t, 0);
    screens(null, { mode: J.phone_mode || "profile", data, t: 5 }, 5);
  } else { // "bg": close, angled, blurred later via CSS
    place(laptop.group, 0, 0, 0, 0, (i % 2 ? -1 : 1) * 0.35); place(phone.group, (i % 2 ? -1 : 1) * 2.1, 0.78, -0.8, 0, (i % 2 ? 1 : -1) * 0.5);
    shadowL.position.set(0, 0.005, -0.1); shadowP.position.set((i % 2 ? -1 : 1) * 2.1, 0.006, -0.78);
    lookFrom((i % 2 ? 1 : -1) * 3.5, 2.6, 9, 0, 1.0, -0.6, t, 0);
    screens({ mode: "solution", data, stepsShown: 9, stepProgress: 1 }, { mode: "app", data }, 5);
  }
  composer.render();
}

function renderStill(spec) {
  // spec: {scene: hero|phone|bg, blur, html}
  stillScene(spec.scene, spec.index || 0);
  $("gl").style.filter = spec.blur ? `blur(${spec.blur}px) brightness(.7) saturate(1.2)` : "none";
  $("still").innerHTML = spec.html;
  const g = grainOffsets[(spec.index || 0) % grainOffsets.length];
  $("grain").style.backgroundPosition = `${g[0]}px ${g[1]}px`;
  $("flash").style.opacity = 0;
}

window.__dbg = () => ({ composer, bloom, renderer, scene, lapTex, phoneTex, THREE });
window.setup = setup;
window.renderFrame = renderFrame;
window.renderStill = renderStill;
window.__ready = true;
