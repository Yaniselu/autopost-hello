// "Story" reels v2: a little cartoon 3D town that an AI director uses like a film set.
// One street with cutaway buildings (shop, home, office, warehouse) and a park, plus an abstract
// studio stage. Every shot picks a place, an era (now / past), a time of day, a camera, a cast that
// walks, sits, types, calls, talks (speech bubbles), thinks, celebrates... and props (paper piles,
// money rain, confetti, rain clouds, light bulbs, boxes, message bubbles).
// Every frame is computed from (shot, local time) only, so several browsers can render in parallel.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

const $ = (id) => document.getElementById(id);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const eio = (x) => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const eob = (x) => { x = clamp(x); const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };
const lerp = (a, b, k) => a + (b - a) * k;
function rng(seed) { let s = (seed >>> 0) || 1; return () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 100000) / 100000; }; }
function hash(str) { let h = 2166136261; for (const c of String(str)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }

let J, W, H, R, renderer, scene, camera, sun, hemi, skyMat;
const night = { stars: null, moon: null, lights: [], lamps: [] };
let ACC, ACC_D;
const FLOOR = 0.12, WALK = 0.06;
const SETS = {};            // name -> {x, slots, cams, door, outside, crowd, groups:{now,past}, clock}
const ERA = { now: [], past: [] };
const clouds = [];
const chars = [];           // all character rigs
const CAST = {};            // id -> rig
const crowd = [];
const FX = {};              // prop effects

// ------------------------------------------------------------------ helpers
function mat(c, o = {}) {
  return new THREE.MeshStandardMaterial({ color: c, roughness: o.r ?? 0.78, metalness: o.m ?? 0,
    emissive: o.e ?? 0x000000, emissiveIntensity: o.ei ?? 1, transparent: !!o.t, opacity: o.o ?? 1, map: o.map || null,
    side: o.ds ? THREE.DoubleSide : THREE.FrontSide });
}
function add(parent, geo, m, x = 0, y = 0, z = 0, cast = true) {
  const me = new THREE.Mesh(geo, m); me.position.set(x, y, z); me.castShadow = cast; me.receiveShadow = true; parent.add(me); return me;
}
const box = (w, h, d, r = 0.02) => (r > 0 ? new RoundedBoxGeometry(w, h, d, 2, Math.min(r, w / 2.2, h / 2.2, d / 2.2)) : new THREE.BoxGeometry(w, h, d));
const sph = (r, a = 20, b = 14) => new THREE.SphereGeometry(r, a, b);
const cyl = (r1, r2, h, s = 20) => new THREE.CylinderGeometry(r1, r2, h, s);
function canvasTex(w, h, draw) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; const x = c.getContext("2d"); draw(x, w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
}
function rr(x, X, Y, w, h, r) { x.beginPath(); x.roundRect(X, Y, w, h, r); }
const hex = (c) => "#" + new THREE.Color(c).getHexString();
function group(parent, x = 0, y = 0, z = 0) { const g = new THREE.Group(); g.position.set(x, y, z); parent.add(g); return g; }
function sprite(tex, w, h) { const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthWrite: false, depthTest: false })); s.scale.set(w, h, 1); s.renderOrder = 20; s.visible = false; scene.add(s); return s; }

// ------------------------------------------------------------------ setup
async function setup(job) {
  J = job; W = job.width; H = job.height; R = rng(job.seed || 1);
  ACC = new THREE.Color(job.palette.accent); ACC_D = ACC.clone().lerp(new THREE.Color(0x0b1a14), 0.55);
  await document.fonts.load("800 64px Inter"); await document.fonts.load("600 32px Inter");
  const sc = job.render_scale || 0.6667;
  const RW = Math.round((W * sc) / 2) * 2, RH = Math.round((H * sc) / 2) * 2;
  const canvas = $("gl"); canvas.width = RW; canvas.height = RH;
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1); renderer.setSize(RW, RH, false);
  renderer.toneMapping = THREE.NeutralToneMapping; renderer.toneMappingExposure = 1.0;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFShadowMap;
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(38, W / H, 0.1, 300);
  const S = job.story;
  buildSky(); buildStreet();
  buildShop(S); buildHome(); buildOffice(S); buildWarehouse(S); buildPark(); buildStage();
  buildNeighbours(); buildFX(); buildCast(S);
  return { total: S.total, shots: S.shots };
}

// ------------------------------------------------------------------ sky + street
function buildSky() {
  skyMat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { top: { value: new THREE.Color(0x6fb8ec) }, bottom: { value: new THREE.Color(0xeaf5fb) } },
    vertexShader: "varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.); }",
    fragmentShader: "uniform vec3 top; uniform vec3 bottom; varying vec3 vP; void main(){ float h = clamp(vP.y*1.6+.1,0.,1.); gl_FragColor = vec4(mix(bottom, top, h), 1.); }",
  });
  scene.add(new THREE.Mesh(new THREE.SphereGeometry(150, 32, 16), skyMat));
  scene.fog = new THREE.Fog(0xe3f0f8, 26, 90);
  hemi = new THREE.HemisphereLight(0xe6f3ff, 0xdacbb2, 1.35); scene.add(hemi);
  sun = new THREE.DirectionalLight(0xfff1dc, 2.3); sun.castShadow = true;
  sun.shadow.mapSize.set(1536, 1536); const s = sun.shadow.camera; s.left = -6; s.right = 6; s.top = 6; s.bottom = -4; s.near = 1; s.far = 40;
  sun.shadow.bias = -0.0006; sun.shadow.normalBias = 0.025; scene.add(sun, sun.target);
  const cm = mat(0xffffff, { r: 1, e: 0xffffff, ei: 0.25 });
  for (let i = 0; i < 14; i++) {
    const g = new THREE.Group(); const n = 4 + Math.floor(R() * 3);
    for (let k = 0; k < n; k++) { const m = add(g, sph(0.6 + R() * 0.5, 16, 12), cm, k * 0.75 - n * 0.37, (k % 2) * 0.25, R() * 0.3, false); m.scale.y = 0.75; }
    g.userData.base = new THREE.Vector3(-26 + R() * 64, 6.5 + R() * 4, -10 - R() * 14); g.userData.sp = 0.08 + R() * 0.12;
    scene.add(g); clouds.push(g);
  }
  night.moon = add(scene, sph(0.9, 24, 16), mat(0xfff6d8, { e: 0xfff1c8, ei: 1.2 }), 9, 11, -30, false); night.moon.visible = false;
  const n = 300, pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { pos[i * 3] = -50 + R() * 110; pos[i * 3 + 1] = 6 + R() * 26; pos[i * 3 + 2] = -45 - R() * 10; }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  night.stars = new THREE.Points(g, new THREE.PointsMaterial({ size: 0.16, color: 0xffffff, fog: false })); night.stars.visible = false; scene.add(night.stars);
}

function buildStreet() {
  add(scene, new THREE.PlaneGeometry(260, 260), mat(0xe6e0d3), 0, 0, 0, false).rotation.x = -Math.PI / 2;
  const tiles = canvasTex(256, 64, (x, w, h) => { x.fillStyle = "#ebe7de"; x.fillRect(0, 0, w, h); x.strokeStyle = "rgba(0,0,0,.07)"; x.lineWidth = 2;
    for (let i = 0; i <= w; i += 64) { x.beginPath(); x.moveTo(i, 0); x.lineTo(i, h); x.stroke(); } });
  tiles.wrapS = THREE.RepeatWrapping; tiles.repeat.set(60, 1);
  add(scene, new THREE.BoxGeometry(120, WALK, 1.05), mat(0xffffff, { map: tiles }), 8, WALK / 2, 0.5, false);
  add(scene, new THREE.BoxGeometry(120, 0.12, 0.1), mat(0xd3cdc1), 8, 0.06, 1.05, false);
  add(scene, new THREE.PlaneGeometry(120, 14), mat(0x3e424b, { r: 0.95 }), 8, 0.004, 8.1, false).rotation.x = -Math.PI / 2;
  const dm = mat(0xf3e7b4);
  for (let x = -50; x < 66; x += 1.4) add(scene, new THREE.BoxGeometry(0.7, 0.006, 0.09), dm, x, 0.008, 3.4, false);
}

function cutaway(x0, w, d, h, wallC, floorTex) {
  const g = group(scene, x0);
  const wall = mat(wallC);
  add(g, box(w + 0.3, FLOOR, d + 0.2, 0.01), mat(0xd9d2c4), 0, FLOOR / 2, -d / 2 + 0.05);
  const fl = add(g, new THREE.PlaneGeometry(w - 0.1, d), mat(0xffffff, { map: floorTex, r: 0.6 }), 0, FLOOR + 0.002, -d / 2, false); fl.rotation.x = -Math.PI / 2;
  add(g, new THREE.BoxGeometry(w, h, 0.15), wall, 0, FLOOR + h / 2, -d - 0.02);
  for (const s of [-1, 1]) add(g, new THREE.BoxGeometry(0.16, h + 0.02, d + 0.1), wall, s * (w / 2), FLOOR + h / 2, -d / 2 + 0.03);
  add(g, new THREE.BoxGeometry(w + 0.34, 0.2, d + 0.4), mat(0xf7f1e6), 0, FLOOR + h + 0.1, -d / 2 + 0.06);
  return g;
}
function facade(g, w, h, signText, signCol, awningCol) {
  add(g, box(w + 0.34, 0.62, 0.22, 0.03), mat(0xf7f1e6), 0, FLOOR + h - 0.2, 0.06);
  add(g, box(w + 0.36, 0.08, 0.24, 0.01), mat(awningCol.getHex()), 0, FLOOR + h - 0.48, 0.07);
  for (const s of [-1, 1]) add(g, box(0.24, h, 0.26, 0.03), mat(0xf7f1e6), s * (w / 2 + 0.04), FLOOR + h / 2, 0.02);
  if (signText) {
    const tex = canvasTex(1024, 256, (x, W2, H2) => {
      x.fillStyle = hex(signCol); rr(x, 0, 0, W2, H2, 40); x.fill();
      x.strokeStyle = "#e3c26a"; x.lineWidth = 12; rr(x, 14, 14, W2 - 28, H2 - 28, 30); x.stroke();
      x.fillStyle = "#ffe9a8"; for (let i = 0; i < 22; i++) { x.beginPath(); x.arc(46 + i * 44, 34, 6, 0, 7); x.fill(); x.beginPath(); x.arc(46 + i * 44, H2 - 34, 6, 0, 7); x.fill(); }
      let fs = 132; x.font = `800 ${fs}px Inter`; const name = String(signText).toUpperCase().slice(0, 18);
      while (x.measureText(name).width > W2 - 120 && fs > 50) { fs -= 6; x.font = `800 ${fs}px Inter`; }
      x.fillStyle = "#fff6dc"; x.textAlign = "center"; x.textBaseline = "middle"; x.fillText(name, W2 / 2, H2 / 2 + 6);
    });
    const sg = group(g, 0, FLOOR + h + 0.5, 0.2);
    add(sg, box(2.7, 0.68, 0.14, 0.05), mat(signCol.getHex()), 0, 0, 0);
    add(sg, new THREE.PlaneGeometry(2.62, 0.65), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.5, emissive: 0xffffff, emissiveMap: tex, emissiveIntensity: 0.18 }), 0, 0, 0.075, false);
    for (const s of [-1, 1]) add(sg, cyl(0.02, 0.02, 0.5, 8), mat(0x444444, { m: 0.6 }), s * 1.0, -0.4, -0.05);
  }
  const aw = canvasTex(512, 64, (x) => { for (let i = 0; i < 16; i++) { x.fillStyle = i % 2 ? "#ffffff" : hex(awningCol); x.fillRect(i * 32, 0, 32, 64); } });
  const a = add(g, new THREE.PlaneGeometry(w + 0.2, 0.42), mat(0xffffff, { map: aw, ds: true }), 0, FLOOR + h - 0.56, 0.3, true); a.rotation.x = -1.2;
}
function clock(g, x, y, z, setName) {
  const c = group(g, x, y, z);
  add(c, cyl(0.24, 0.24, 0.06, 32), mat(0x2c2c30), 0, 0, 0).rotation.x = Math.PI / 2;
  add(c, cyl(0.205, 0.205, 0.07, 32), mat(0xffffff), 0, 0, 0.01).rotation.x = Math.PI / 2;
  for (let i = 0; i < 12; i++) { const a = (i / 12) * Math.PI * 2; add(c, new THREE.BoxGeometry(0.012, 0.035, 0.01), mat(0x222222), Math.sin(a) * 0.17, Math.cos(a) * 0.17, 0.05, false).rotation.z = -a; }
  const hands = [];
  for (const [len, wd] of [[0.15, 0.022], [0.11, 0.03]]) { const p = group(c, 0, 0, 0.06); add(p, new THREE.BoxGeometry(wd, len, 0.01), mat(0x16161a), 0, len / 2 - 0.02, 0, false); hands.push(p); }
  SETS[setName].clock = hands;
}
function plant(g, x, y, z, s = 1) {
  const p = group(g, x, y, z); p.scale.setScalar(s);
  add(p, cyl(0.15, 0.11, 0.3, 20), mat(0xc96f45, { r: 0.8 }), 0, 0.15, 0);
  const lm = mat(0x4f9d57, { r: 0.7 });
  for (let i = 0; i < 7; i++) { const a = (i / 7) * Math.PI * 2; const l = add(p, sph(0.12, 12, 8), lm, Math.cos(a) * 0.1, 0.42 + (i % 3) * 0.12, Math.sin(a) * 0.1); l.scale.set(0.7, 1.4, 0.5); l.rotation.z = Math.cos(a) * 0.5; l.rotation.x = Math.sin(a) * 0.5; }
  return p;
}
function sofa(color, len) {
  const g = new THREE.Group(); const m = mat(color, { r: 0.85 });
  add(g, box(len, 0.24, 0.55, 0.06), m, 0, 0.28, 0);
  add(g, box(len, 0.55, 0.16, 0.07), m, 0, 0.5, -0.22);
  for (const s of [-1, 1]) add(g, box(0.16, 0.38, 0.58, 0.06), m, s * (len / 2 - 0.02), 0.36, 0);
  const n = Math.max(2, Math.round(len / 0.5));
  for (let i = 0; i < n; i++) add(g, box(len / n - 0.04, 0.08, 0.46, 0.04), mat(new THREE.Color(color).lerp(new THREE.Color(0xffffff), 0.12).getHex(), { r: 0.9 }), -len / 2 + (i + 0.5) * (len / n), 0.43, 0.03);
  for (const s of [-1, 1]) add(g, cyl(0.03, 0.03, 0.16, 8), mat(0x3a2a1e), s * (len / 2 - 0.12), 0.08, 0.15);
  return g;
}
function chair(g, x, z, ry = 0, col = 0x2b3532) {
  const c = group(g, x, FLOOR, z); c.rotation.y = ry;
  add(c, cyl(0.2, 0.24, 0.04, 20), mat(0x444448, { m: 0.6, r: 0.4 }), 0, 0.02, 0); add(c, cyl(0.035, 0.035, 0.3, 10), mat(0x777777, { m: 0.7 }), 0, 0.2, 0);
  add(c, box(0.46, 0.1, 0.44, 0.04), mat(col), 0, 0.4, 0); add(c, box(0.46, 0.5, 0.08, 0.04), mat(col), 0, 0.7, -0.2);
  return c;
}
function desk(g, x, z, w = 1.1) {
  const d = group(g, x, FLOOR, z);
  add(d, box(w, 0.05, 0.6, 0.01), mat(0xd8b88c, { r: 0.5 }), 0, 0.74, 0);
  for (const s of [-1, 1]) add(d, box(0.05, 0.72, 0.56, 0.01), mat(0xbfa07a), s * (w / 2 - 0.04), 0.36, 0);
  add(d, box(w - 0.1, 0.4, 0.03, 0.01), mat(0xcfae84), 0, 0.5, 0.27);
  return d;
}
function laptop(g, x, y, z) { // lid faces the camera, screen faces the person behind the desk
  const l = group(g, x, y, z);
  add(l, box(0.42, 0.02, 0.3, 0.01), mat(0xb8bcc4, { m: 0.6, r: 0.35 }), 0, 0.01, 0);
  const lid = add(l, box(0.42, 0.28, 0.015, 0.01), mat(0xc8ccd2, { m: 0.6, r: 0.35 }), 0, 0.15, 0.14); lid.rotation.x = 0.25;
  add(l, sph(0.03, 12, 8), mat(0xffffff, { e: 0xffffff, ei: 0.6 }), 0, 0.16, 0.155, false).scale.z = 0.2;
  return l;
}
function crt(g, x, y, z) {
  const c = group(g, x, y, z);
  add(c, box(0.42, 0.36, 0.4, 0.04), mat(0xe2dccb), 0, 0.2, 0);
  add(c, box(0.3, 0.06, 0.25, 0.02), mat(0xd6cfbb), 0, 0.01, 0);
  add(c, box(0.46, 0.03, 0.16, 0.01), mat(0xe2dccb), 0, 0.02, 0.32);
  return c;
}
function papers(g, x, y, z, n = 5) {
  const p = group(g, x, y, z);
  for (let i = 0; i < n; i++) { const s = add(p, new THREE.BoxGeometry(0.26, 0.012, 0.34), mat(i % 3 ? 0xfafaf5 : 0xf1ead2), Math.sin(i) * 0.02, i * 0.014, Math.cos(i * 2) * 0.02, false); s.rotation.y = Math.sin(i * 3) * 0.15; }
  return p;
}
function landline(g, x, y, z) {
  const p = group(g, x, y, z);
  add(p, box(0.2, 0.08, 0.16, 0.03), mat(0x9c2f2a), 0, 0.04, 0);
  add(p, box(0.24, 0.05, 0.06, 0.025), mat(0x8a2925), 0, 0.1, 0);
  add(p, cyl(0.05, 0.05, 0.012, 16), mat(0xf2ead8), 0, 0.085, 0.045).rotation.x = 0.4;
  return p;
}
function cabinet(g, x, z) {
  const c = group(g, x, FLOOR, z);
  add(c, box(0.45, 1.2, 0.5, 0.02), mat(0x8d949c, { m: 0.5, r: 0.45 }), 0, 0.6, 0);
  for (let i = 0; i < 3; i++) { add(c, box(0.38, 0.32, 0.02, 0.01), mat(0x9aa1a9, { m: 0.5, r: 0.4 }), 0, 0.25 + i * 0.38, 0.26); add(c, box(0.1, 0.02, 0.03, 0.005), mat(0x333333), 0, 0.33 + i * 0.38, 0.28); }
  return c;
}
function slot(set, name, x, z, o = {}) { set.slots[name] = { x: set.x + x, z, ry: o.ry ?? 0, seat: o.seat, desk: o.desk ? { x: set.x + o.desk[0], y: o.desk[1], z: o.desk[2] } : null }; }
function newSet(name, x, o) {
  const s = { name, x, slots: {}, crowd: [], ...o };
  s.groups = { now: group(scene, 0), past: group(scene, 0) };
  ERA.now.push(s.groups.now); ERA.past.push(s.groups.past); SETS[name] = s; return s;
}

// ------------------------------------------------------------------ SHOP (business varies)
const BUSINESS = {
  salon: { station: "chair", title: "PRICES" }, clinic: { station: "chair", title: "SERVICES" }, restaurant: { station: "table", title: "MENU" },
  cafe: { station: "counter", title: "MENU" }, store: { station: "counter", title: "TODAY" }, gym: { station: "counter", title: "PLANS" },
  bakery: { station: "counter", title: "FRESH" }, agency: { station: "counter", title: "SERVICES" },
};
function buildShop(S) {
  const X = 0, w = 4.2, d = 2.45, h = 2.6;
  const checker = canvasTex(256, 256, (x) => { for (let i = 0; i < 8; i++) for (let k = 0; k < 8; k++) { x.fillStyle = (i + k) % 2 ? "#2b2d33" : "#f4f1ea"; x.fillRect(i * 32, k * 32, 32, 32); } });
  checker.wrapS = checker.wrapT = THREE.RepeatWrapping; checker.repeat.set(4.5, 2.6);
  const set = newSet("shop", X, { cams: { wide: { p: [X, 2.2, 13.2], l: [X, 1.9, 0] }, medium: { p: [X, 1.5, 8.3], l: [X, 1.4, -1.0] } }, door: [X + 1.6, -0.15], outside: [X + 3.3, 0.4] });
  const g = cutaway(X, w, d, h, 0xf6efe2, checker);
  const biz = BUSINESS[S.business] || BUSINESS.salon;
  add(g, box(w - 0.18, 0.82, 0.05, 0.01), mat(ACC_D.getHex(), { r: 0.55 }), 0, FLOOR + 0.41, -d + 0.08);
  add(g, box(w - 0.18, 0.05, 0.07, 0.01), mat(0xd9b45f, { r: 0.4, m: 0.3 }), 0, FLOOR + 0.84, -d + 0.08);
  facade(g, w, h, S.business_name || "Shop", ACC_D, ACC);
  clock(g, -0.15, FLOOR + 1.95, -d + 0.1, "shop");
  const board = canvasTex(400, 460, (x, w2, h2) => {
    x.fillStyle = "#26302c"; rr(x, 0, 0, w2, h2, 22); x.fill(); x.strokeStyle = "#7a5a3a"; x.lineWidth = 18; rr(x, 9, 9, w2 - 18, h2 - 18, 18); x.stroke();
    x.fillStyle = "#f6e7b8"; x.font = "800 54px Inter"; x.textAlign = "center"; x.fillText(biz.title, w2 / 2, 92);
    x.font = "600 36px Inter"; const sv = (S.services && S.services.length ? S.services : [["Basic", "$15"], ["Plus", "$25"], ["Full", "$40"]]).slice(0, 4);
    sv.forEach(([n, p], i) => { x.textAlign = "left"; x.fillStyle = "#fff"; x.fillText(String(n).slice(0, 11), 44, 170 + i * 70); x.textAlign = "right"; x.fillStyle = "#f6e7b8"; x.fillText(String(p).slice(0, 5), w2 - 44, 170 + i * 70); });
  });
  add(g, new THREE.PlaneGeometry(0.62, 0.72), mat(0xffffff, { map: board, r: 0.9 }), -1.05, FLOOR + 1.75, -d + 0.1, false);
  for (const x of [-1.0, 0.95]) {
    const lp = group(g, x, FLOOR + h, -1.0);
    add(lp, cyl(0.008, 0.008, 0.45, 6), mat(0x333333), 0, -0.22, 0, false);
    add(lp, new THREE.ConeGeometry(0.17, 0.16, 24, 1, true), mat(ACC_D.getHex(), { r: 0.5, ds: true }), 0, -0.5, 0, false);
    add(lp, sph(0.06, 12, 8), mat(0xfff3d0, { e: 0xffe2a8, ei: 2 }), 0, -0.55, 0, false);
    const pl = new THREE.PointLight(0xffdca8, 0.9, 4, 1.6); pl.position.set(X + x, FLOOR + h - 0.6, -1.0); scene.add(pl); night.lights.push(pl);
  }
  plant(g, -1.85, FLOOR, -d + 0.35, 1.0); plant(g, 1.85, FLOOR, -0.55, 0.85);
  const couch = sofa(ACC_D.clone().lerp(ACC, 0.35).getHex(), 1.65); couch.position.set(-1.12, FLOOR, -d + 0.42); g.add(couch);
  const seatY = FLOOR + 0.47;
  [[-1.67, -1.95], [-1.29, -1.95], [-0.92, -1.95], [-0.55, -1.95]].forEach(([x, z], i) => slot(set, `couch${i + 1}`, x, z, { seat: seatY }));
  slot(set, "queue1", -1.45, -0.95); slot(set, "queue2", -0.85, -0.85); slot(set, "center", 0.0, -0.6); slot(set, "door", 1.6, -0.2, { ry: -0.5 });
  set.crowd = ["couch1", "couch2", "couch3", "couch4", "queue1", "queue2"];
  if (biz.station === "chair") {
    const st = group(g, 0.95, FLOOR, -1.45);
    add(st, cyl(0.22, 0.26, 0.05, 24), mat(0xdcdcdc, { m: 0.8, r: 0.3 }), 0, 0.03, 0); add(st, cyl(0.05, 0.05, 0.3, 12), mat(0xdcdcdc, { m: 0.8, r: 0.3 }), 0, 0.2, 0);
    add(st, box(0.56, 0.14, 0.5, 0.05), mat(0x2b3532, { r: 0.6 }), 0, 0.42, 0); add(st, box(0.56, 0.62, 0.12, 0.05), mat(0x2b3532, { r: 0.6 }), 0, 0.78, -0.22);
    if (S.business === "clinic") {
      const cr = group(g, 0.95, FLOOR + 1.55, -d + 0.1); add(cr, box(0.5, 0.5, 0.04, 0.05), mat(0xffffff), 0, 0, 0);
      add(cr, box(0.12, 0.36, 0.05, 0.01), mat(ACC.getHex()), 0, 0, 0.01); add(cr, box(0.36, 0.12, 0.05, 0.01), mat(ACC.getHex()), 0, 0, 0.01);
    } else {
      const mir = group(g, 0.95, FLOOR + 1.45, -d + 0.1);
      add(mir, new THREE.TorusGeometry(0.4, 0.045, 12, 40), mat(0xd9b45f, { m: 0.6, r: 0.35 }), 0, 0, 0);
      add(mir, new THREE.CircleGeometry(0.4, 40), mat(0xcfe9f2, { m: 0.2, r: 0.15 }), 0, 0, -0.01, false);
    }
    slot(set, "service", 0.95, -1.45, { seat: FLOOR + 0.49 }); slot(set, "staff", 1.52, -1.05, { ry: -0.55 });
  } else if (biz.station === "table") {
    const t = group(g, 1.25, FLOOR, -1.4);
    add(t, cyl(0.38, 0.38, 0.04, 28), mat(0xf7f1e6), 0, 0.72, 0); add(t, cyl(0.04, 0.06, 0.7, 12), mat(0x3a2a1e), 0, 0.36, 0);
    add(t, cyl(0.12, 0.12, 0.015, 24), mat(0xffffff), -0.12, 0.75, 0.08);
    chair(g, 0.72, -1.4, Math.PI / 2, 0x8a5a3b);
    slot(set, "service", 0.74, -1.4, { ry: Math.PI / 2, seat: FLOOR + 0.49 }); slot(set, "staff", 1.55, -0.85, { ry: -0.6 });
  } else {
    const c = group(g, 1.0, FLOOR, -1.25);
    add(c, box(1.4, 0.86, 0.5, 0.03), mat(ACC_D.clone().lerp(ACC, 0.2).getHex(), { r: 0.6 }), 0, 0.43, 0);
    add(c, box(1.48, 0.05, 0.58, 0.02), mat(0xc9975f, { r: 0.5 }), 0, 0.88, 0);
    if (S.business === "cafe" || S.business === "bakery") {
      add(c, box(0.36, 0.34, 0.3, 0.03), mat(0xd8d8d8, { m: 0.7, r: 0.3 }), 0.35, 1.08, -0.05);
      add(c, sph(0.12, 16, 10), mat(0xe8c39a), -0.48, 0.98, -0.05).scale.y = 0.6;
      add(c, sph(0.1, 16, 10), mat(0xd99a5a), -0.25, 0.97, 0.05).scale.y = 0.55;
    } else {
      const sh = group(g, -0.1, FLOOR, -d + 0.2);
      for (let r = 0; r < 3; r++) { add(sh, box(0.9, 0.03, 0.26, 0.01), mat(0xc9975f), 0, 1.05 + r * 0.32, 0);
        for (let k = 0; k < 4; k++) add(sh, box(0.16, 0.2, 0.16, 0.02), mat([0xe0483f, 0x3d7fe0, 0xf2c240, 0x3fb07a][(k + r) % 4]), -0.32 + k * 0.21, 1.17 + r * 0.32, 0); }
    }
    const tab = group(set.groups.now, X + 1.4, FLOOR + 0.9, -1.2); add(tab, box(0.26, 0.18, 0.02, 0.01), mat(0x1c1c20), 0, 0.09, 0).rotation.x = -0.4;
    const reg = group(set.groups.past, X + 1.4, FLOOR + 0.9, -1.25); add(reg, box(0.36, 0.22, 0.3, 0.03), mat(0x8c7b5c, { m: 0.4, r: 0.4 }), 0, 0.11, 0); add(reg, box(0.3, 0.12, 0.1, 0.02), mat(0x6e5f45), 0, 0.27, -0.08);
    slot(set, "service", 0.95, -0.62, { ry: Math.PI }); slot(set, "staff", 1.0, -1.75, { desk: [1.0, FLOOR + 0.9, -1.25] });
  }
  if (!set.slots.staff.desk) set.slots.staff.desk = { x: X + 1.75, y: FLOOR + 1.22, z: -d + 0.2 };
  add(g, box(0.36, 0.04, 0.22, 0.01), mat(0xd9b45f, { r: 0.5 }), 1.75, FLOOR + 1.2, -d + 0.2);
  const ph = group(set.groups.now, X + 1.75, FLOOR + 1.36, -d + 0.22); add(ph, box(0.13, 0.24, 0.02, 0.015), mat(0x1c1c20, { r: 0.3 }), 0, 0, 0);
  add(ph, new THREE.PlaneGeometry(0.11, 0.21), mat(0x111111, { e: ACC.getHex(), ei: 0.6 }), 0, 0, 0.012, false); ph.rotation.x = -0.25;
  landline(set.groups.past, X + 1.75, FLOOR + 1.22, -d + 0.22);
  papers(set.groups.past, X - 0.3, FLOOR, -d + 0.3, 3);
}

// ------------------------------------------------------------------ HOME
function buildHome() {
  const X = 7.6, w = 3.6, d = 2.3, h = 2.4;
  const wood = canvasTex(256, 256, (x) => { for (let i = 0; i < 8; i++) { x.fillStyle = i % 2 ? "#c8955f" : "#d4a36d"; x.fillRect(0, i * 32, 256, 32); x.fillStyle = "rgba(0,0,0,.06)"; x.fillRect(0, i * 32, 256, 2); } });
  wood.wrapS = wood.wrapT = THREE.RepeatWrapping; wood.repeat.set(2, 2);
  const set = newSet("home", X, { cams: { wide: { p: [X, 2.2, 13.2], l: [X, 1.9, 0] }, medium: { p: [X, 1.5, 7.2], l: [X, 1.3, -0.9] } }, door: [X + 1.2, -0.2], outside: [X, 0.45] });
  const g = cutaway(X, w, d, h, 0xf6dcc2, wood);
  const sh = new THREE.Shape(); sh.moveTo(-w / 2 - 0.35, 0); sh.lineTo(0, 1.05); sh.lineTo(w / 2 + 0.35, 0); sh.lineTo(-w / 2 - 0.35, 0);
  add(g, new THREE.ExtrudeGeometry(sh, { depth: d + 0.5, bevelEnabled: false }), mat(0xc8473d, { r: 0.7 }), 0, FLOOR + h + 0.2, -d - 0.25);
  add(g, box(0.3, 0.6, 0.3, 0.02), mat(0xb03b33), 1.0, FLOOR + h + 0.9, -d / 2);
  add(g, new THREE.ShapeGeometry(sh), mat(0xf6e8d6), 0, FLOOR + h + 0.2, 0.26, false).scale.set(0.86, 0.8, 1);
  const sky = canvasTex(128, 128, (x) => { const gr = x.createLinearGradient(0, 0, 0, 128); gr.addColorStop(0, "#7cc2ee"); gr.addColorStop(1, "#dff1fb"); x.fillStyle = gr; x.fillRect(0, 0, 128, 128);
    x.fillStyle = "#fff"; x.beginPath(); x.arc(40, 50, 14, 0, 7); x.arc(58, 46, 18, 0, 7); x.arc(76, 52, 13, 0, 7); x.fill(); });
  add(g, box(1.1, 0.85, 0.06, 0.02), mat(0xffffff), -0.85, FLOOR + 1.55, -d + 0.07);
  add(g, new THREE.PlaneGeometry(0.96, 0.72), mat(0xffffff, { map: sky, e: 0xffffff, ei: 0.25 }), -0.85, FLOOR + 1.55, -d + 0.11, false);
  for (const s of [-1, 1]) add(g, box(0.22, 1.0, 0.05, 0.03), mat(0xd04a3c, { r: 0.9 }), -0.85 + s * 0.62, FLOOR + 1.5, -d + 0.14);
  add(g, box(0.5, 0.38, 0.04, 0.02), mat(0xc9975f), 0.9, FLOOR + 1.65, -d + 0.08);
  add(g, new THREE.PlaneGeometry(0.42, 0.3), mat(0x9fd3a6), 0.9, FLOOR + 1.65, -d + 0.105, false);
  const couch = sofa(0x3f66c4, 1.75); couch.position.set(0, FLOOR, -d + 0.42); g.add(couch);
  const rug = add(g, new THREE.CircleGeometry(1, 40), mat(0xe9c46a, { r: 1 }), 0, FLOOR + 0.006, -0.95, false); rug.rotation.x = -Math.PI / 2; rug.scale.set(1.3, 0.55, 1);
  add(g, cyl(0.02, 0.02, 1.2, 8), mat(0x333333), 1.35, FLOOR + 0.6, -d + 0.35); add(g, cyl(0.04, 0.16, 0.12, 16), mat(0x333333), 1.35, FLOOR + 0.03, -d + 0.35);
  add(g, new THREE.ConeGeometry(0.22, 0.26, 24, 1, true), mat(0xf6e3b4, { e: 0xffe3a0, ei: 0.4, ds: true }), 1.35, FLOOR + 1.28, -d + 0.35);
  const hl = new THREE.PointLight(0xffd9a0, 0.6, 4, 1.6); hl.position.set(X + 1.35, FLOOR + 1.2, -d + 0.5); scene.add(hl); night.lights.push(hl);
  plant(g, -1.5, FLOOR, -0.6, 1.0);
  add(g, box(0.5, 0.45, 0.4, 0.02), mat(0xb98a5c), -1.25, FLOOR + 0.225, -d + 0.4);
  const tv = group(set.groups.past, X - 1.25, FLOOR + 0.45, -d + 0.4); add(tv, box(0.44, 0.36, 0.36, 0.05), mat(0x5a4a3a), 0, 0.18, 0); add(tv, box(0.32, 0.24, 0.02, 0.03), mat(0x2b3a3a), 0, 0.2, 0.18);
  landline(set.groups.past, X - 1.0, FLOOR + 0.45, -d + 0.55);
  const sp = group(set.groups.now, X - 1.25, FLOOR + 0.45, -d + 0.4); add(sp, cyl(0.07, 0.07, 0.2, 16), mat(0x2b2b30), 0, 0.1, 0);
  slot(set, "couch", 0, -d + 0.45, { seat: FLOOR + 0.47 }); slot(set, "couch2", 0.5, -d + 0.45, { seat: FLOOR + 0.47 });
  slot(set, "center", 0.45, -0.65); slot(set, "window", -0.85, -1.45); slot(set, "door", 1.2, -0.2, { ry: -0.5 });
  set.slots.couch.desk = { x: X - 1.25, y: FLOOR + 0.45, z: -d + 0.4 };
  set.crowd = ["couch2", "center", "window"];
}

// ------------------------------------------------------------------ OFFICE
function buildOffice(S) {
  const X = 14.4, w = 4.8, d = 2.6, h = 2.8;
  const carpet = canvasTex(128, 128, (x) => { x.fillStyle = "#c9cdd4"; x.fillRect(0, 0, 128, 128); x.fillStyle = "rgba(0,0,0,.05)"; for (let i = 0; i < 128; i += 8) x.fillRect(i, 0, 1, 128); });
  carpet.wrapS = carpet.wrapT = THREE.RepeatWrapping; carpet.repeat.set(4, 2);
  const set = newSet("office", X, { cams: { wide: { p: [X, 2.3, 13.6], l: [X, 2.0, 0] }, medium: { p: [X, 1.55, 8.6], l: [X, 1.4, -1.1] } }, door: [X + 2.0, -0.2], outside: [X + 3.0, 0.4] });
  const g = cutaway(X, w, d, h, 0xeef1f4, carpet);
  facade(g, w, h, S.office_name || "HQ", new THREE.Color(0x26323f), new THREE.Color(0x3d6fe0));
  add(g, box(w - 0.18, 0.08, 0.05, 0.01), mat(0x3d6fe0), 0, FLOOR + 0.95, -d + 0.08);
  const wb = canvasTex(512, 300, (x, w2, h2) => { x.fillStyle = "#fbfbfb"; x.fillRect(0, 0, w2, h2); x.strokeStyle = "#9aa3ad"; x.lineWidth = 14; x.strokeRect(0, 0, w2, h2);
    x.strokeStyle = hex(ACC); x.lineWidth = 10; x.beginPath(); x.moveTo(40, 240); x.lineTo(150, 200); x.lineTo(250, 220); x.lineTo(360, 120); x.lineTo(470, 70); x.stroke();
    x.fillStyle = "#e0483f"; x.font = "800 40px Inter"; x.fillText("Q4", 40, 70); });
  add(g, new THREE.PlaneGeometry(1.3, 0.76), mat(0xffffff, { map: wb, r: 0.5 }), 0, FLOOR + 1.75, -d + 0.1, false);
  clock(g, 1.75, FLOOR + 2.1, -d + 0.1, "office");
  for (const [k, dx] of [[1, -1.15], [2, 1.15]]) {
    desk(g, dx, -1.55);
    chair(g, dx, -2.05, 0, 0x2f3a46);
    laptop(set.groups.now, X + dx - 0.05, FLOOR + 0.77, -1.6);
    add(set.groups.now, cyl(0.04, 0.035, 0.1, 12), mat(0xffffff), X + dx + 0.38, FLOOR + 0.82, -1.45);
    crt(set.groups.past, X + dx + 0.3, FLOOR + 0.77, -1.6);
    papers(set.groups.past, X + dx - 0.4, FLOOR + 0.77, -1.45, 6);
    slot(set, `desk${k}`, dx, -2.05, { seat: FLOOR + 0.47, desk: [dx - 0.42, FLOOR + 0.77, -1.45] });
  }
  landline(set.groups.past, X - 0.6, FLOOR + 0.77, -1.45);
  cabinet(set.groups.past, X - 2.0, -d + 0.35); cabinet(set.groups.past, X - 1.5, -d + 0.35);
  plant(set.groups.now, X - 2.0, FLOOR, -d + 0.4, 1.1); plant(g, 2.0, FLOOR, -0.5, 0.9);
  const screen = group(set.groups.now, X, FLOOR + 2.35, -d + 0.12);
  add(screen, box(0.8, 0.42, 0.04, 0.02), mat(0x1c1c20), 0, 0, 0);
  add(screen, new THREE.PlaneGeometry(0.74, 0.36), mat(0xffffff, { map: canvasTex(256, 128, (x) => { x.fillStyle = "#0f1720"; x.fillRect(0, 0, 256, 128);
    for (let i = 0; i < 6; i++) { x.fillStyle = hex(ACC); x.fillRect(20 + i * 38, 110 - (20 + i * 14), 24, 20 + i * 14); } }), e: 0xffffff, ei: 0.35 }), 0, 0, 0.025, false);
  for (const x of [-1.2, 1.2]) { const pl = new THREE.PointLight(0xfff2dc, 0.7, 4, 1.6); pl.position.set(X + x, FLOOR + h - 0.5, -1.2); scene.add(pl); night.lights.push(pl);
    add(g, box(0.9, 0.04, 0.25, 0.01), mat(0xffffff, { e: 0xffffff, ei: 0.8 }), x, FLOOR + h - 0.03, -1.2, false); }
  slot(set, "boss", 0, -0.75); slot(set, "whiteboard", -0.75, -1.95, { ry: 0.3 }); slot(set, "center", 0.3, -0.6); slot(set, "door", 2.0, -0.2, { ry: -0.5 });
  set.crowd = ["center", "boss", "whiteboard"];
}

// ------------------------------------------------------------------ WAREHOUSE
function buildWarehouse(S) {
  const X = 26.5, w = 6.0, d = 3.0, h = 3.2;
  const conc = canvasTex(128, 128, (x) => { x.fillStyle = "#c7c3bb"; x.fillRect(0, 0, 128, 128); x.strokeStyle = "rgba(0,0,0,.08)"; x.strokeRect(0, 0, 128, 128); });
  conc.wrapS = conc.wrapT = THREE.RepeatWrapping; conc.repeat.set(5, 3);
  const set = newSet("warehouse", X, { cams: { wide: { p: [X, 2.5, 15.0], l: [X, 2.1, 0] }, medium: { p: [X, 1.7, 9.8], l: [X, 1.45, -1.3] } }, door: [X + 2.6, -0.2], outside: [X + 3.6, 0.4] });
  const g = cutaway(X, w, d, h, 0xd9dde2, conc);
  facade(g, w, h, S.warehouse_name || "DEPOT", new THREE.Color(0x3a3f47), new THREE.Color(0xf2a33a));
  const box0 = mat(0xc89b63, { r: 0.85 }), tape = mat(0xe8d3a8);
  const cardboard = (pg, x, y, z, s = 0.42) => { add(pg, box(s, s * 0.8, s, 0.02), box0, x, y + s * 0.4, z); add(pg, new THREE.BoxGeometry(s * 1.01, 0.02, 0.06), tape, x, y + s * 0.8, z, false); };
  for (const sx of [-2.2, -0.8]) {
    const sh = group(g, sx, FLOOR, -d + 0.35);
    for (const px of [-0.6, 0.6]) add(sh, box(0.06, 2.4, 0.5, 0.01), mat(0x3d6fe0, { m: 0.3 }), px, 1.2, 0);
    for (let r = 0; r < 3; r++) { add(sh, box(1.3, 0.05, 0.52, 0.01), mat(0xf2a33a), 0, 0.4 + r * 0.8, 0); for (let k = 0; k < 3; k++) cardboard(sh, -0.4 + k * 0.4, 0.43 + r * 0.8, 0, 0.36); }
  }
  const tb = group(g, 1.3, FLOOR, -1.45); add(tb, box(1.4, 0.05, 0.7, 0.01), mat(0xd8b88c), 0, 0.78, 0); for (const a of [-0.62, 0.62]) for (const b of [-0.3, 0.3]) add(tb, box(0.05, 0.76, 0.05, 0.01), mat(0x555555), a, 0.38, b);
  cardboard(tb, -0.35, 0.8, 0, 0.36);
  for (let i = 0; i < 4; i++) cardboard(g, 2.4 - (i % 2) * 0.45, FLOOR + Math.floor(i / 2) * 0.34, -2.4 + (i % 2) * 0.1, 0.42);
  const scanner = group(set.groups.now, X + 1.75, FLOOR + 0.8, -1.45); add(scanner, box(0.3, 0.2, 0.02, 0.01), mat(0x1c1c20), 0, 0.12, 0).rotation.x = -0.35;
  papers(set.groups.past, X + 1.75, FLOOR + 0.8, -1.45, 7); add(set.groups.past, box(0.24, 0.32, 0.02, 0.01), mat(0x8a5a3b), X + 1.0, FLOOR + 0.82, -1.3).rotation.x = -1.4;
  for (const x of [-1.8, 0, 1.8]) { const pl = new THREE.PointLight(0xfff2dc, 0.7, 5, 1.6); pl.position.set(X + x, FLOOR + h - 0.5, -1.4); scene.add(pl); night.lights.push(pl); }
  slot(set, "packing", 1.3, -2.05, { desk: [1.3, FLOOR + 0.8, -1.45] }); slot(set, "shelf", -1.5, -1.6, { ry: 0.6 }); slot(set, "center", 0.2, -0.7);
  slot(set, "door", 2.6, -0.2, { ry: -0.5 }); slot(set, "boxes", 2.1, -1.3, { ry: -0.6, desk: [2.4, FLOOR, -2.0] });
  set.crowd = ["center", "shelf", "boxes"];
}

// ------------------------------------------------------------------ PARK
function buildPark() {
  const X = -13.5;
  const set = newSet("park", X, { cams: { wide: { p: [X, 2.2, 13.0], l: [X, 1.6, -1.2] }, medium: { p: [X, 1.45, 7.6], l: [X, 1.15, -1.3] } }, door: [X + 3.0, 0.35], outside: [X + 4.0, 0.4] });
  const g = group(scene, X);
  add(g, new THREE.PlaneGeometry(7.4, 4.2), mat(0x8fcf7a, { r: 1 }), 0, 0.01, -2.1, false).rotation.x = -Math.PI / 2;
  add(g, new THREE.PlaneGeometry(7.4, 0.7), mat(0xe8dcc2, { r: 1 }), 0, 0.015, -0.55, false).rotation.x = -Math.PI / 2;
  for (const [x, z, s] of [[-2.6, -3.3, 1.2], [2.7, -3.4, 1.35], [-0.6, -3.8, 1.0], [1.2, -3.9, 1.1]]) {
    const t = group(g, x, 0, z); t.scale.setScalar(s); add(t, cyl(0.07, 0.1, 1.3, 10), mat(0x7a5236), 0, 0.65, 0);
    [[0, 1.65, 0, 0.62], [-0.38, 1.4, 0.05, 0.42], [0.4, 1.45, -0.05, 0.45], [0, 2.05, 0, 0.42]].forEach(([a, b, c, r], i) => add(t, sph(r, 18, 12), mat([0x5daa5a, 0x6bb964, 0x4f9a50][i % 3]), a, b, c));
  }
  const b = group(g, 0, 0, -1.55);
  add(b, box(1.5, 0.06, 0.45, 0.02), mat(0x9a6b45), 0, 0.42, 0); add(b, box(1.5, 0.35, 0.05, 0.02), mat(0x9a6b45), 0, 0.68, -0.2);
  for (const s of [-1, 1]) add(b, box(0.06, 0.42, 0.42, 0.01), mat(0x2f3a36), s * 0.65, 0.21, 0);
  const f = group(g, -2.3, 0, -1.7); add(f, cyl(0.6, 0.65, 0.3, 28), mat(0xd9d2c4), 0, 0.15, 0); add(f, cyl(0.52, 0.52, 0.02, 28), mat(0x7cc6ee, { r: 0.1, m: 0.2 }), 0, 0.29, 0);
  add(f, cyl(0.06, 0.08, 0.6, 12), mat(0xd9d2c4), 0, 0.5, 0); add(f, sph(0.12, 14, 10), mat(0x9fd8f5, { r: 0.1 }), 0, 0.85, 0);
  for (let i = 0; i < 10; i++) add(g, sph(0.08 + R() * 0.05, 8, 6), mat([0xf2c240, 0xe86fa3, 0xffffff][i % 3]), -3.3 + R() * 6.6, 0.06, -2.6 - R() * 1.2, false);
  const sy = WALK + 0.42;
  slot(set, "bench1", -0.35, -1.5, { seat: sy }); slot(set, "bench2", 0.35, -1.5, { seat: sy });
  slot(set, "path_left", -1.9, -0.55, { ry: Math.PI / 2 }); slot(set, "path_right", 1.9, -0.55, { ry: -Math.PI / 2 }); slot(set, "center", 0.9, -0.8);
  slot(set, "fountain", -1.5, -1.0, { ry: 0.6 }); slot(set, "door", 3.0, 0.35, { ry: -Math.PI / 2 });
  for (const s of Object.values(set.slots)) s.floor = WALK;
  set.crowd = ["path_left", "path_right", "fountain", "center"];
}

// ------------------------------------------------------------------ STAGE (abstract explainer studio)
function buildStage() {
  const X = 200;
  const set = newSet("stage", X, { cams: { wide: { p: [X, 1.9, 9.0], l: [X, 1.5, -1.0] }, medium: { p: [X, 1.45, 6.4], l: [X, 1.2, -1.0] } }, door: [X + 2.4, -0.4], outside: [X + 3.4, -0.4], interior: true });
  const g = group(scene, X);
  const back = canvasTex(64, 512, (x) => { const gr = x.createLinearGradient(0, 0, 0, 512); gr.addColorStop(0, hex(ACC.clone().lerp(new THREE.Color(0xffffff), 0.7)));
    gr.addColorStop(1, hex(ACC.clone().lerp(new THREE.Color(0xffffff), 0.9))); x.fillStyle = gr; x.fillRect(0, 0, 64, 512); });
  const cy = add(g, new THREE.CylinderGeometry(9, 9, 14, 48, 1, true), new THREE.MeshBasicMaterial({ map: back, side: THREE.BackSide, fog: false }), 0, 6, 2, false);
  cy.receiveShadow = false;
  add(g, new THREE.CircleGeometry(9, 48), mat(ACC.clone().lerp(new THREE.Color(0xffffff), 0.86).getHex(), { r: 1 }), 0, 0.001, 2, false).rotation.x = -Math.PI / 2;
  add(g, cyl(1.6, 1.7, 0.12, 48), mat(0xffffff, { r: 0.6 }), 0, 0.06, -0.9);
  FX.stageProps = {};
  const bp = group(g, 0, 0, -1.3); add(bp, box(0.9, 1.7, 0.1, 0.12), mat(0x1c1c20, { r: 0.3 }), 0, 1.15, 0);
  add(bp, new THREE.PlaneGeometry(0.8, 1.56), mat(0xffffff, { map: canvasTex(256, 500, (x) => { x.fillStyle = "#f5f4f0"; x.fillRect(0, 0, 256, 500); x.fillStyle = hex(ACC); x.fillRect(0, 0, 256, 70);
    for (let i = 0; i < 4; i++) { x.fillStyle = i % 2 ? hex(ACC) : "#e1ded6"; rr(x, i % 2 ? 90 : 20, 100 + i * 90, 146, 60, 22); x.fill(); } }), e: 0xffffff, ei: 0.3 }), 0, 1.15, 0.055, false);
  FX.stageProps.big_phone = bp;
  const lp = group(g, 0, 0, -1.3); add(lp, box(1.6, 0.06, 1.0, 0.03), mat(0xb8bcc4, { m: 0.6, r: 0.35 }), 0, 0.5, 0.3);
  const lid = add(lp, box(1.6, 1.0, 0.04, 0.03), mat(0x1c1c20), 0, 1.0, -0.2); lid.rotation.x = -0.15;
  add(lp, new THREE.PlaneGeometry(1.5, 0.9), mat(0xffffff, { map: canvasTex(320, 200, (x) => { x.fillStyle = "#0f1720"; x.fillRect(0, 0, 320, 200);
    for (let i = 0; i < 7; i++) { x.fillStyle = hex(ACC); x.fillRect(30 + i * 40, 180 - (20 + i * 20), 26, 20 + i * 20); } }), e: 0xffffff, ei: 0.4 }), 0, 1.0, -0.175, false).rotation.x = -0.15;
  FX.stageProps.big_laptop = lp;
  const coins = group(g, 0, 0, -1.2); for (let k = 0; k < 3; k++) for (let i = 0; i < 4 + k * 2; i++) add(coins, cyl(0.28, 0.28, 0.08, 28), mat(0xf2c240, { m: 0.6, r: 0.3 }), -0.7 + k * 0.7, 0.16 + i * 0.085, 0);
  FX.stageProps.coins = coins;
  const bc = group(g, 0, 1.4, -1.4); add(bc, cyl(0.75, 0.75, 0.14, 40), mat(0xffffff), 0, 0, 0).rotation.x = Math.PI / 2;
  add(bc, new THREE.TorusGeometry(0.75, 0.06, 12, 48), mat(ACC.getHex()), 0, 0, 0.02);
  const hs = []; for (const [len, wd] of [[0.6, 0.06], [0.42, 0.08]]) { const p = group(bc, 0, 0, 0.1); add(p, new THREE.BoxGeometry(wd, len, 0.03), mat(0x16161a), 0, len / 2 - 0.06, 0, false); hs.push(p); }
  FX.stageProps.big_clock = bc; set.clock = hs;
  for (const p of Object.values(FX.stageProps)) p.visible = false;
  slot(set, "left", -1.15, -0.7, { ry: 0.25 }); slot(set, "center", 0, -0.55); slot(set, "right", 1.15, -0.7, { ry: -0.25 }); slot(set, "door", 2.4, -0.4, { ry: -1.2 });
  for (const s of Object.values(set.slots)) s.floor = 0.12;
  set.crowd = ["left", "right", "center"];
  const kl = new THREE.PointLight(0xffffff, 1.2, 12, 1.4); kl.position.set(X, 4, 2); scene.add(kl);
}

function buildNeighbours() {
  const win = (c) => canvasTex(256, 512, (x, w, h) => { x.fillStyle = c; x.fillRect(0, 0, w, h);
    for (let r = 0; r < 5; r++) for (let k = 0; k < 3; k++) { x.fillStyle = "#cfe6f2"; x.fillRect(30 + k * 75, 40 + r * 95, 48, 60); x.fillStyle = "rgba(255,255,255,.5)"; x.fillRect(30 + k * 75, 40 + r * 95, 48, 8); } });
  const bld = (x, w, h, c) => add(scene, box(w, h, 2.4, 0.04), mat(0xffffff, { map: win(c) }), x, h / 2, -2.5);
  bld(-6.0, 4.6, 4.4, "#e8cfa9"); bld(20.3, 3.6, 5.0, "#cfdfe9"); bld(33.5, 4.2, 4.2, "#e9d7e4"); bld(-20.5, 5, 5.6, "#dfe9cf");
  const far = ["#bcd8ee", "#cfe4f3", "#f0dcc8", "#d5e9d8", "#e9d5e6"];
  for (let i = 0; i < 26; i++) { const fh = 3.5 + R() * 6; add(scene, box(2 + R() * 2.5, fh, 2, 0.02), mat(0xffffff, { map: win(far[i % 5]), r: 1 }), -34 + i * 3.0 + R(), fh / 2, -12 - R() * 6, false); }
  for (const x of [3.9, 10.6, 17.9, 23.0, 30.4, -9.4]) tree(x, 0.32);
  for (const x of [-2.9, 5.7, 12.0, 22.3]) lamp(x);
}
function tree(x, z) {
  const g = group(scene, x, WALK, z);
  add(g, cyl(0.07, 0.1, 1.3, 10), mat(0x7a5236), 0, 0.65, 0);
  const lm = [mat(0x5daa5a), mat(0x6bb964), mat(0x4f9a50)];
  [[0, 1.65, 0, 0.62], [-0.38, 1.4, 0.05, 0.42], [0.4, 1.45, -0.05, 0.45], [0, 2.05, 0, 0.42]].forEach(([a, b, c, r], i) => add(g, sph(r, 18, 12), lm[i % 3], a, b, c));
}
function lamp(x) {
  const g = group(scene, x, WALK, 0.85);
  add(g, cyl(0.04, 0.05, 2.6, 10), mat(0x2f3a36, { m: 0.4 }), 0, 1.3, 0);
  night.lamps.push(add(g, sph(0.12, 14, 10), mat(0xfff7e0, { e: 0xffe6b0, ei: 0.3 }), 0, 2.66, 0));
}

// ------------------------------------------------------------------ FX props
const _tx = {};
function iconTex(kind) {
  if (_tx[kind]) return _tx[kind];
  _tx[kind] = canvasTex(256, 256, (x) => {
    x.textAlign = "center"; x.textBaseline = "middle";
    if (kind === "bulb") { x.fillStyle = "rgba(255,220,80,.35)"; x.beginPath(); x.arc(128, 110, 110, 0, 7); x.fill(); x.fillStyle = "#ffd23f"; x.beginPath(); x.arc(128, 105, 62, 0, 7); x.fill();
      x.fillStyle = "#8d8d8d"; x.fillRect(100, 160, 56, 44); x.strokeStyle = "#fff6c8"; x.lineWidth = 10; x.beginPath(); x.arc(110, 90, 26, 3.6, 4.6); x.stroke(); }
    else if (kind === "bill") { x.fillStyle = "#3fae6a"; rr(x, 20, 70, 216, 116, 14); x.fill(); x.strokeStyle = "#cdeed7"; x.lineWidth = 8; rr(x, 34, 84, 188, 88, 10); x.stroke();
      x.fillStyle = "#e6fff0"; x.font = "800 72px Inter"; x.fillText("$", 128, 132); }
    else if (kind === "spark") { x.fillStyle = "#ffd23f"; x.beginPath(); for (let i = 0; i < 8; i++) { const a = i * Math.PI / 4, r = i % 2 ? 34 : 110; x.lineTo(128 + Math.cos(a) * r, 128 + Math.sin(a) * r); } x.fill(); }
    else if (kind === "clock") { x.fillStyle = "#fff"; x.beginPath(); x.arc(128, 128, 100, 0, 7); x.fill(); x.strokeStyle = "#16161a"; x.lineWidth = 14; x.stroke();
      x.lineCap = "round"; x.beginPath(); x.moveTo(128, 128); x.lineTo(128, 60); x.moveTo(128, 128); x.lineTo(176, 150); x.stroke(); }
  });
  return _tx[kind];
}
function buildFX() {
  FX.bills = []; for (let i = 0; i < 26; i++) FX.bills.push(sprite(iconTex("bill"), 0.32, 0.32));
  FX.confetti = []; const cg = new THREE.PlaneGeometry(0.06, 0.1);
  for (let i = 0; i < 70; i++) { const m = new THREE.Mesh(cg, new THREE.MeshBasicMaterial({ color: [0xe0483f, 0x3d7fe0, 0xf2c240, 0x3fb07a, 0xe86fa3, ACC.getHex()][i % 6], side: THREE.DoubleSide }));
    m.visible = false; scene.add(m); FX.confetti.push(m); }
  FX.bulb = sprite(iconTex("bulb"), 0.42, 0.42);
  FX.sparks = []; for (let i = 0; i < 6; i++) FX.sparks.push(sprite(iconTex("spark"), 0.2, 0.2));
  FX.floatClock = sprite(iconTex("clock"), 0.5, 0.5);
  const rc = group(scene); for (let k = 0; k < 4; k++) add(rc, sph(0.17 + (k % 2) * 0.05, 14, 10), mat(0x6f7785, { r: 1 }), -0.2 + k * 0.14, (k % 2) * 0.06, 0, false);
  const drops = []; for (let i = 0; i < 12; i++) drops.push(add(rc, new THREE.BoxGeometry(0.012, 0.12, 0.012), mat(0x7cc6ee, { e: 0x7cc6ee, ei: 0.3 }), -0.25 + (i % 6) * 0.1, -0.3, (i % 2) * 0.05, false));
  rc.userData.drops = drops; rc.visible = false; FX.rain = rc;
  const pp = group(scene); for (let i = 0; i < 40; i++) { const s = add(pp, new THREE.BoxGeometry(0.26, 0.014, 0.34), mat(i % 4 ? 0xfafaf5 : 0xf1ead2), Math.sin(i * 1.7) * 0.025, i * 0.016, Math.cos(i * 2.3) * 0.025, false); s.rotation.y = Math.sin(i * 3.1) * 0.25; }
  pp.visible = false; FX.papers = pp;
  const bp = group(scene); const bm = mat(0xc89b63, { r: 0.85 });
  [[0, 0, 0], [0.45, 0, 0.05], [-0.45, 0, -0.03], [0.2, 0.36, 0], [-0.22, 0.36, 0.02], [0, 0.72, 0], [0.62, 0.36, -0.1], [-0.6, 0.36, 0.08]].forEach(([x, y, z]) => add(bp, box(0.42, 0.34, 0.4, 0.02), bm, x, y + 0.17, z));
  bp.visible = false; FX.boxes = bp;
  FX.msgs = []; for (let i = 0; i < 6; i++) FX.msgs.push(sprite(bubbleTex("msg"), 0.3, 0.3));
}

// ------------------------------------------------------------------ characters
const SKINS = [0xf2c9a5, 0xe3b08a, 0xc68a62, 0x9a6643, 0xf6d6bd, 0xd9a07a];
const COLORS = { red: 0xe0483f, blue: 0x3d7fe0, green: 0x3fb07a, yellow: 0xf2c240, orange: 0xf08a3c, purple: 0x7b5cd6, pink: 0xe86fa3,
  teal: 0x2bb3a3, black: 0x2b2b30, white: 0xf3f1ec, gray: 0x8d949c, navy: 0x2f4a7a, brown: 0x8a5a3b };
const HAIRS = [0x2a1d17, 0x3b2a1f, 0x14110f, 0x6b4428, 0xb07a45, 0x9a9a9a];
const STYLES = ["short", "curly", "bun", "long", "bald"];

function makeChar(o) {
  const root = new THREE.Group(), body = new THREE.Group(); root.add(body); scene.add(root);
  const skin = mat(o.skin, { r: 0.6 }), shirt = mat(o.shirt, { r: 0.85 }), pants = mat(o.pants ?? 0x2f3644), shoe = mat(0x1d1d22, { r: 0.5 }), hairM = mat(o.hair, { r: 0.9 });
  const legs = [];
  for (const s of [-1, 1]) { const p = group(body, s * 0.075, 0.32, 0); add(p, new THREE.CapsuleGeometry(0.06, 0.16, 4, 10), pants, 0, -0.14, 0); add(p, box(0.11, 0.07, 0.17, 0.03), shoe, 0, -0.29, 0.03); legs.push(p); }
  const torso = add(body, new THREE.CapsuleGeometry(0.165, 0.13, 6, 16), shirt, 0, 0.5, 0); torso.scale.set(1, 1, 0.8);
  if (o.extra === "apron") add(body, box(0.26, 0.3, 0.03, 0.02), mat(0xf7f7f2), 0, 0.45, 0.125);
  if (o.extra === "tie") { add(body, box(0.05, 0.2, 0.02, 0.01), mat(0xc0392b), 0, 0.52, 0.14); add(body, box(0.18, 0.05, 0.03, 0.01), mat(0xf3f1ec), 0, 0.63, 0.12); }
  const arms = [];
  for (const s of [-1, 1]) { const p = group(body, s * 0.2, 0.6, 0); add(p, new THREE.CapsuleGeometry(0.047, 0.15, 4, 10), shirt, 0, -0.1, 0); add(p, sph(0.052, 12, 10), skin, 0, -0.22, 0); arms.push(p); }
  const head = group(body, 0, 0.86, 0);
  const headM = skin.clone(); add(head, sph(0.215, 28, 20), headM, 0, 0.02, 0);
  for (const s of [-1, 1]) add(head, sph(0.05, 10, 8), headM, s * 0.21, 0.0, 0);
  add(head, sph(0.03, 10, 8), headM, 0, -0.005, 0.212);
  const eyeM = mat(0x15151a, { r: 0.25 });
  for (const s of [-1, 1]) { add(head, sph(0.03, 12, 10), eyeM, s * 0.078, 0.035, 0.192, false); add(head, sph(0.009, 6, 6), mat(0xffffff, { e: 0xffffff, ei: 0.6 }), s * 0.078 + 0.01, 0.047, 0.218, false); }
  const brows = [-1, 1].map((s) => add(head, box(0.075, 0.018, 0.02, 0.008), hairM, s * 0.078, 0.1, 0.198, false));
  for (const s of [-1, 1]) add(head, sph(0.032, 10, 8), mat(0xf29a8f, { r: 0.9, t: true, o: 0.55 }), s * 0.12, -0.04, 0.178, false).scale.set(1, 0.6, 0.4);
  const mouth = add(head, new THREE.TorusGeometry(0.045, 0.012, 8, 18, Math.PI), mat(0x6e2b2b, { r: 0.6 }), 0, -0.075, 0.2, false);
  if (o.style !== "bald") { const cap = add(head, new THREE.SphereGeometry(0.228, 28, 14, 0, Math.PI * 2, 0, 1.3), hairM, 0, 0.03, -0.012); cap.rotation.x = -0.32; }
  else add(head, new THREE.SphereGeometry(0.222, 24, 12, 0, Math.PI * 2, Math.PI * 0.45, 0.5), hairM, 0, 0.02, -0.02).rotation.x = -0.6;
  if (o.style === "curly") for (let i = 0; i < 9; i++) { const a = (i / 9) * Math.PI * 2; add(head, sph(0.075, 10, 8), hairM, Math.cos(a) * 0.15, 0.17 + (i % 2) * 0.03, Math.sin(a) * 0.13 - 0.02); }
  if (o.style === "bun") add(head, sph(0.095, 14, 10), hairM, 0, 0.24, -0.1);
  if (o.style === "long") { const l = add(head, new THREE.CapsuleGeometry(0.17, 0.18, 4, 14), hairM, 0, -0.1, -0.08); l.scale.set(1.18, 1, 0.75); }
  if (o.beard) { add(head, new THREE.SphereGeometry(0.222, 24, 12, 0, Math.PI * 2, Math.PI * 0.56, Math.PI * 0.36), hairM, 0, 0.0, 0.01).rotation.x = 0.15; mouth.position.z = 0.215; }
  if (o.extra === "glasses") { const gm = mat(0x16161a); for (const s of [-1, 1]) add(head, new THREE.TorusGeometry(0.045, 0.008, 6, 20), gm, s * 0.078, 0.035, 0.205, false); add(head, new THREE.BoxGeometry(0.06, 0.008, 0.008), gm, 0, 0.04, 0.21, false); }
  if (o.extra === "cap") { add(head, new THREE.SphereGeometry(0.232, 24, 12, 0, Math.PI * 2, 0, 1.1), mat(0xe0483f), 0, 0.04, 0); add(head, box(0.22, 0.02, 0.16, 0.01), mat(0xe0483f), 0, 0.12, 0.22); }
  const phone = group(body, 0, 0.5, 0.24); phone.rotation.x = -0.7;
  add(phone, box(0.09, 0.16, 0.014, 0.012), mat(0x1c1c20, { r: 0.3 }), 0, 0, 0, false);
  const pscreen = add(phone, new THREE.PlaneGeometry(0.076, 0.142), mat(0x0f2a20, { e: ACC.getHex(), ei: 1.0 }), 0, 0, 0.008, false);
  const handset = add(arms[1], box(0.05, 0.16, 0.05, 0.02), mat(0x9c2f2a), 0.0, -0.26, 0.04, false);
  const carry = add(body, box(0.36, 0.28, 0.32, 0.02), mat(0xc89b63, { r: 0.85 }), 0, 0.55, 0.3);
  const bubble = new THREE.Sprite(new THREE.SpriteMaterial({ depthWrite: false, depthTest: false })); bubble.renderOrder = 10; root.add(bubble);
  const say = new THREE.Sprite(new THREE.SpriteMaterial({ depthWrite: false, depthTest: false })); say.renderOrder = 11; root.add(say);
  const c = { root, body, legs, arms, head, headM, skin: new THREE.Color(o.skin), brows, mouth, phone, pscreen, handset, carry, bubble, say, ph: R() * 6 };
  chars.push(c); return c;
}

function buildCast(S) {
  for (const [i, c] of (S.cast || []).entries()) {
    const L = c.look || {}, h = hash(c.id || i);
    CAST[c.id] = makeChar({ skin: SKINS[(Number.isInteger(L.skin) ? L.skin : h) % SKINS.length], shirt: COLORS[L.shirt] ?? Object.values(COLORS)[h % 9],
      hair: HAIRS[(h >> 3) % HAIRS.length], style: STYLES.includes(L.hair) ? L.hair : STYLES[(h >> 5) % 4], beard: L.beard ?? ((h >> 7) % 4 === 0),
      extra: L.extra, pants: COLORS[L.pants] ?? 0x2f3644 });
  }
  const shirts = [0x7b5cd6, 0x3d7fe0, 0xf08a3c, 0xf2c240, 0xe0483f, 0x3fb07a, 0xe86fa3, 0x2bb3a3];
  for (let i = 0; i < 6; i++) crowd.push(makeChar({ skin: SKINS[(i * 2 + 1) % SKINS.length], shirt: shirts[(i + 3) % shirts.length], hair: HAIRS[i % 5], style: STYLES[i % 4] }));
}

const _bub = {};
function bubbleTex(kind) {
  if (_bub[kind]) return _bub[kind];
  _bub[kind] = canvasTex(256, 256, (x) => {
    x.fillStyle = "rgba(0,0,0,.12)"; rr(x, 30, 34, 196, 160, 60); x.fill();
    x.fillStyle = "#ffffff"; rr(x, 26, 24, 196, 160, 60); x.fill();
    x.beginPath(); x.moveTo(78, 176); x.lineTo(64, 224); x.lineTo(118, 180); x.fill();
    x.textAlign = "center"; x.textBaseline = "middle";
    const sym = (s, c, size = 120) => { x.fillStyle = c; x.font = `800 ${size}px Inter`; x.fillText(s, 124, 112); };
    if (kind === "?") sym("?", "#3d7fe0"); else if (kind === "!") sym("!", "#f08a3c");
    else if (kind === "zzz") sym("zzz", "#7b5cd6", 76); else if (kind === "$") sym("$", "#3fae6a");
    else if (kind === "check") { x.strokeStyle = hex(ACC); x.lineWidth = 22; x.lineCap = "round"; x.beginPath(); x.moveTo(78, 108); x.lineTo(112, 140); x.lineTo(172, 76); x.stroke(); }
    else if (kind === "heart") { x.fillStyle = "#e8455a"; x.beginPath(); x.moveTo(124, 160); x.bezierCurveTo(30, 100, 70, 30, 124, 78); x.bezierCurveTo(178, 30, 218, 100, 124, 160); x.fill(); }
    else if (kind === "angry") { x.strokeStyle = "#e0453a"; x.lineWidth = 16; x.lineCap = "round"; for (const [a, b] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) { x.beginPath(); x.moveTo(124 + a * 18, 104 + b * 18); x.quadraticCurveTo(124 + a * 50, 104 + b * 8, 124 + a * 52, 104 + b * 46); x.stroke(); } }
    else if (kind === "msg") { x.fillStyle = hex(ACC); rr(x, 64, 70, 120, 80, 26); x.fill(); x.fillStyle = "#fff"; for (let i = 0; i < 3; i++) { x.beginPath(); x.arc(96 + i * 28, 110, 9, 0, 7); x.fill(); } }
    else if (kind === "idea") { x.fillStyle = "#ffd23f"; x.beginPath(); x.arc(124, 98, 46, 0, 7); x.fill(); x.fillStyle = "#8d8d8d"; x.fillRect(104, 136, 40, 24); }
    else if (kind === "clock") { x.strokeStyle = "#16161a"; x.lineWidth = 12; x.beginPath(); x.arc(124, 104, 52, 0, 7); x.stroke(); x.beginPath(); x.moveTo(124, 104); x.lineTo(124, 70); x.moveTo(124, 104); x.lineTo(150, 118); x.stroke(); }
    else if (kind === "sweat") { x.fillStyle = "#7cc6ee"; x.beginPath(); x.moveTo(124, 50); x.quadraticCurveTo(170, 120, 124, 150); x.quadraticCurveTo(78, 120, 124, 50); x.fill(); }
    else sym(String(kind).slice(0, 2), "#16161a", 100);
  });
  return _bub[kind];
}
const _say = {};
function sayTex(text, think) {
  const key = (think ? "T|" : "S|") + text;
  if (_say[key]) return _say[key];
  const c = document.createElement("canvas"), x = c.getContext("2d");
  x.font = "800 46px Inter"; const words = String(text).split(/\s+/); const lines = []; let cur = "";
  for (const w of words) { const n = (cur + " " + w).trim(); if (x.measureText(n).width > 380 && cur) { lines.push(cur); cur = w; } else cur = n; }
  if (cur) lines.push(cur);
  const tw = Math.max(...lines.map((l) => x.measureText(l).width)), W2 = Math.ceil(tw + 74), H2 = lines.length * 54 + 56 + 40;
  c.width = W2; c.height = H2; const y = c.getContext("2d");
  y.fillStyle = "rgba(0,0,0,.14)"; rr(y, 6, 10, W2 - 10, H2 - 46, 34); y.fill();
  y.fillStyle = think ? "#eef2ff" : "#ffffff"; rr(y, 2, 2, W2 - 10, H2 - 46, 34); y.fill();
  if (think) { y.beginPath(); y.arc(W2 / 2, H2 - 30, 13, 0, 7); y.fill(); y.beginPath(); y.arc(W2 / 2 - 14, H2 - 10, 8, 0, 7); y.fill(); }
  else { y.beginPath(); y.moveTo(W2 / 2 - 22, H2 - 48); y.lineTo(W2 / 2 - 6, H2 - 4); y.lineTo(W2 / 2 + 22, H2 - 48); y.fill(); }
  y.font = "800 46px Inter"; y.fillStyle = "#16161a"; y.textBaseline = "top"; lines.forEach((l, i) => y.fillText(l, 35, 24 + i * 54));
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.userData = { w: W2, h: H2 }; _say[key] = t; return t;
}

// ------------------------------------------------------------------ poses
function put(c, o) {
  c.root.visible = true;
  c.root.position.set(o.x, o.y ?? FLOOR, o.z); c.root.rotation.set(0, o.ry ?? 0, 0); c.root.scale.setScalar(o.scale ?? 1);
  const t = o.t ?? 0, p = o.pose || "stand";
  c.body.position.set(0, 0, 0); c.body.rotation.set(0, 0, 0); c.head.rotation.set(0, 0, 0);
  c.legs.forEach((l) => l.rotation.set(0, 0, 0)); c.arms.forEach((a, i) => a.rotation.set(0, 0, (i ? 1 : -1) * 0.1));
  c.phone.visible = false; c.handset.visible = false; c.carry.visible = false;
  c.mouth.rotation.set(0, 0, Math.PI); c.mouth.scale.set(1, 1, 1); c.mouth.position.y = -0.075;
  const breath = Math.sin(t * 2.4 + c.ph) * 0.01;
  const moving = p === "walk" || p === "run";
  const seated = o.seat !== undefined && o.seat !== null && !moving && p !== "celebrate";
  if (moving) {
    const f = p === "run" ? 17 : 11, s = Math.sin(t * f + c.ph), a = p === "run" ? 0.9 : 0.65;
    c.legs[0].rotation.x = s * a; c.legs[1].rotation.x = -s * a; c.arms[0].rotation.x = -s * a * 0.85; c.arms[1].rotation.x = s * a * 0.85;
    c.body.position.y = Math.abs(Math.cos(t * f + c.ph)) * (p === "run" ? 0.06 : 0.035); c.body.rotation.x = p === "run" ? 0.18 : 0.06;
  } else if (seated) {
    c.root.position.y = o.seat - 0.27; c.legs.forEach((l) => (l.rotation.x = -1.35)); c.body.position.y = breath;
  } else c.body.position.y = breath;
  if (p === "phone") { c.arms.forEach((a, i) => { a.rotation.x = -1.05; a.rotation.z = (i ? -1 : 1) * 0.35; }); c.phone.visible = true; c.head.rotation.x = 0.28; c.pscreen.material.emissiveIntensity = 0.8 + 0.4 * Math.sin(t * 6); }
  if (p === "call") { c.arms[1].rotation.set(-0.3, 0, 2.55); c.handset.visible = true; c.head.rotation.z = -0.15; c.head.rotation.y = Math.sin(t * 2) * 0.1; c.mouth.scale.y = 1 + Math.abs(Math.sin(t * 12)) * 0.6; }
  if (p === "type") { c.arms.forEach((a, i) => { a.rotation.x = -1.25 + Math.sin(t * 22 + i * 1.7) * 0.08; a.rotation.z = (i ? -1 : 1) * 0.2; }); c.head.rotation.x = 0.18; }
  if (p === "work") { c.arms[1].rotation.x = -1.0 + Math.sin(t * (o.fast ? 16 : 8)) * 0.3; c.arms[0].rotation.x = -0.7 + Math.sin(t * (o.fast ? 14 : 6) + 1) * 0.15; c.head.rotation.x = 0.15; c.body.rotation.y = Math.sin(t * 2) * 0.06; }
  if (p === "talk") { c.arms[1].rotation.x = -0.5 + Math.sin(t * 5) * 0.25; c.arms[1].rotation.z = 0.5; c.arms[0].rotation.x = -0.3 + Math.sin(t * 4 + 1) * 0.15; c.head.rotation.y = Math.sin(t * 1.8) * 0.12; c.mouth.scale.y = 1 + Math.abs(Math.sin(t * 14)) * 0.8; }
  if (p === "wave") c.arms[1].rotation.z = 2.5 + Math.sin(t * 10) * 0.35;
  if (p === "point") { c.arms[1].rotation.x = -1.45; c.arms[1].rotation.z = 0.2; }
  if (p === "carry") { c.arms.forEach((a, i) => { a.rotation.x = -1.2; a.rotation.z = (i ? -1 : 1) * 0.15; }); c.carry.visible = true; }
  if (p === "celebrate") { const j = Math.abs(Math.sin(t * 7)); c.root.position.y += j * 0.22; c.arms[0].rotation.z = -2.6 + Math.sin(t * 7) * 0.2; c.arms[1].rotation.z = 2.6 - Math.sin(t * 7) * 0.2; c.legs[0].rotation.x = -j * 0.4; c.legs[1].rotation.x = -j * 0.3; }
  if (p === "facepalm") { c.arms[1].rotation.set(-2.2, 0, 0.75); c.head.rotation.x = 0.35; c.head.rotation.y = Math.sin(t * 3) * 0.15; }
  if (p === "sleep") { c.head.rotation.z = 0.35; c.head.rotation.x = 0.25; c.body.rotation.z = 0.05; }
  if (p === "shrug") { const k = Math.abs(Math.sin(t * 2.5)); c.arms.forEach((a, i) => { a.rotation.z = (i ? 1 : -1) * (0.9 + k * 0.3); a.rotation.x = -0.4; }); c.head.rotation.z = 0.12; }
  if (p === "panic") { c.arms.forEach((a, i) => { a.rotation.z = (i ? 1 : -1) * (2.4 + Math.sin(t * 18 + i) * 0.3); }); c.body.position.x = Math.sin(t * 30) * 0.015; }
  if (p === "carry" && moving) c.carry.visible = true;
  // emotion
  const e = o.emo || "neutral";
  c.headM.color.copy(c.skin); c.brows[0].rotation.z = 0; c.brows[1].rotation.z = 0; c.brows.forEach((b) => (b.position.y = 0.1));
  if (e === "happy" || e === "proud" || e === "excited") { c.mouth.scale.x = 1.3; c.mouth.scale.y = Math.max(c.mouth.scale.y, 1.5); c.brows.forEach((b) => (b.position.y = 0.115)); }
  if (e === "sad" || e === "angry" || e === "stressed" || e === "tired") { c.mouth.rotation.z = 0; c.mouth.position.y = -0.11; c.mouth.scale.x = 0.9; c.mouth.scale.y = Math.min(c.mouth.scale.y, 0.7); }
  if (e === "angry") { c.headM.color.copy(c.skin).lerp(new THREE.Color(0xe2493c), clamp(o.emoK ?? 1) * 0.6); c.brows[0].rotation.z = -0.5; c.brows[1].rotation.z = 0.5; }
  if (e === "sad" || e === "stressed" || e === "tired") { c.brows[0].rotation.z = 0.35; c.brows[1].rotation.z = -0.35; }
  if (e === "surprised" || e === "confused") { c.mouth.scale.set(0.55, 1.6, 1); c.brows.forEach((b) => (b.position.y = 0.125)); if (e === "confused") c.brows[0].rotation.z = 0.3; }
  if (o.shake) c.head.rotation.y = Math.sin(t * 14) * 0.25;
  // bubble (icon) and speech / thought
  const yTop = seated ? 1.2 : 1.36;
  if (o.bubble) { const k = eob(o.bk ?? 1); c.bubble.visible = k > 0.01; c.bubble.material.map = bubbleTex(o.bubble); c.bubble.material.needsUpdate = true;
    const s = 0.34 * k * (1 + 0.04 * Math.sin(t * 5)); c.bubble.scale.set(s, s, 1); c.bubble.position.set(-0.22, yTop + Math.sin(t * 3) * 0.02, 0); }
  else c.bubble.visible = false;
  if (o.say) { const k = eob(o.sk ?? 1); const tex = sayTex(o.say, o.think); c.say.visible = k > 0.01; c.say.material.map = tex; c.say.material.needsUpdate = true;
    const sw = tex.userData.w / 340, sh = tex.userData.h / 340; c.say.scale.set(sw * k, sh * k, 1); c.say.center.set(0.5, 0.0);
    c.say.position.set(0, yTop + 0.06 + (o.bubble ? 0.3 : 0), 0.1); }
  else c.say.visible = false;
}

function walkPath(pts, k) {
  const seg = []; let tot = 0;
  for (let i = 1; i < pts.length; i++) { const l = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); seg.push(l); tot += l; }
  let d = clamp(k) * tot;
  for (let i = 0; i < seg.length; i++) {
    if (d <= seg[i] || i === seg.length - 1) { const f = seg[i] ? clamp(d / seg[i]) : 1, a = pts[i], b = pts[i + 1];
      return { x: lerp(a[0], b[0], f), z: lerp(a[1], b[1], f), y: lerp(a[2] ?? FLOOR, b[2] ?? FLOOR, f), ry: Math.atan2(b[0] - a[0], b[1] - a[1]) }; }
    d -= seg[i];
  }
  const e = pts[pts.length - 1]; return { x: e[0], z: e[1], y: e[2] ?? FLOOR, ry: 0 };
}

// ------------------------------------------------------------------ world state per frame
function setSky(time) {
  const N = time === "night", S = time === "sunset";
  skyMat.uniforms.top.value.set(N ? 0x0e1a3a : S ? 0x5b7fc4 : 0x6fb8ec); skyMat.uniforms.bottom.value.set(N ? 0x3a3f74 : S ? 0xffc59a : 0xeaf5fb);
  scene.fog.color.set(N ? 0x2b3160 : S ? 0xf3cdb4 : 0xe3f0f8);
  hemi.intensity = N ? 0.45 : 1.35; hemi.color.set(N ? 0x8fa0ff : S ? 0xffe0c8 : 0xe6f3ff);
  sun.intensity = N ? 0.35 : S ? 1.8 : 2.3; sun.color.set(N ? 0x9fb2ff : S ? 0xffb37a : 0xfff1dc);
  night.moon.visible = N; night.stars.visible = N; clouds.forEach((c) => (c.visible = !N));
  night.lights.forEach((l) => (l.intensity = N ? 0.25 : 0.9)); night.lamps.forEach((b) => (b.material.emissiveIntensity = N ? 2.5 : 0.3));
}
function setEra(era) { const past = era === "past"; ERA.now.forEach((g) => (g.visible = !past)); ERA.past.forEach((g) => (g.visible = past)); }

function camTo(spec, k, t, pull) {
  const e = eio(k), push = (spec.push ?? 0.7) * (pull ? e : 1 - e);
  camera.position.set(spec.p[0] + Math.sin(t * 0.9) * 0.03, spec.p[1] + Math.sin(t * 1.3) * 0.02 + push * 0.12, spec.p[2] + push);
  camera.lookAt(spec.l[0], spec.l[1], spec.l[2]);
  sun.position.set(camera.position.x + 4, 9, 7); sun.target.position.set(spec.l[0], 0, -1); sun.target.updateMatrixWorld();
}

function slotOf(set, name) { return set.slots[name] || set.slots.center || Object.values(set.slots)[0]; }
function floorOf(set, s) { return s.floor ?? FLOOR; }
const POSES = { stand: "stand", sit: "stand", type: "type", phone: "phone", call: "call", talk: "talk", work: "work", serve: "work", wave: "wave",
  point: "point", carry: "carry", celebrate: "celebrate", facepalm: "facepalm", sleep: "sleep", shrug: "shrug", panic: "panic" };

const LANDMARK = { park: -13.5, shop: 1.8, home: 7.6, office: 15.6, warehouse: 28.0 };
function renderStreet(shot, lt, d, t) {
  setSky(shot.time || "day"); setEra(shot.era || "now");
  for (const k in FX.stageProps) FX.stageProps[k].visible = false;
  let lead = null;
  (shot.cast || []).forEach((r, idx) => {
    const c = CAST[r.who]; if (!c) return;
    const a = LANDMARK[r.from] ?? LANDMARK.home, b = LANDMARK[r.to] ?? LANDMARK.shop;
    const z = 0.38 + idx * 0.22, xoff = -idx * 0.55 * Math.sign(b - a || 1);
    const k = clamp((lt - 0.1) / Math.max(1, d - 0.5)), x = lerp(a, b, eio(k)) + xoff;
    const moving = k > 0 && k < 1, run = r.do === "run";
    const xb = { bubble: r.icon || null, bk: (lt / d - 0.15) / 0.12, say: r.say || r.think || null, think: !r.say && !!r.think, sk: (lt / d - 0.2 - idx * 0.12) / 0.1 };
    put(c, { x, z, y: WALK, ry: moving ? (b > a ? Math.PI / 2 : -Math.PI / 2) : 0, pose: moving ? (run ? "run" : r.do === "carry" ? "carry" : "walk") : (r.do === "phone" ? "phone" : "wave"),
      t: lt + idx, emo: r.emo || "neutral", ...xb });
    if (r.do === "carry") c.carry.visible = true;
    if (!lead) lead = x;
  });
  const cr = shot.crowd || {};
  for (let i = 0; i < Math.min(6, cr.n || 0); i++) {
    const base = (lead ?? LANDMARK.shop) + (i - 2.5) * 1.3, dir = i % 2 ? 1 : -1, x = base + dir * ((lt * 0.9 + i) % 3 - 1.5);
    put(crowd[i], { x, z: 0.3 + (i % 3) * 0.2, y: WALK, ry: dir * Math.PI / 2, pose: "walk", t: lt + i, emo: cr.emo || "neutral" });
  }
  const cx = lead ?? LANDMARK.shop;
  camTo({ p: [cx, 1.45, 6.2], l: [cx, 1.05, -0.6], push: 0 }, 0, t);
}

function renderShot(shot, lt, d, t) {
  if (shot.set === "street") return renderStreet(shot, lt, d, t);
  const set = SETS[shot.set] || SETS.shop;
  setSky(set.interior ? "day" : shot.time || "day"); setEra(shot.era || "now");
  const P = new Set(shot.props || []);
  if (set.clock) { const sp = P.has("clock_fast") ? 9 : 0; set.clock[0].rotation.z = -t * 0.5 - lt * sp; set.clock[1].rotation.z = -t * 0.04 - 1.2 - lt * sp * 0.08; }
  for (const k in FX.stageProps) FX.stageProps[k].visible = set.name === "stage" && P.has(k);
  let focus = null, walkerX = null;
  (shot.cast || []).forEach((r, idx) => {
    const c = CAST[r.who]; if (!c) return;
    const s = slotOf(set, r.at), fl = floorOf(set, s);
    const doing = r.do || "stand", emo = r.emo || "neutral";
    const base = { x: s.x, z: s.z, ry: s.ry, y: fl, seat: s.seat, t: lt + idx, emo };
    const doorP = [set.door[0], set.door[1], fl], outP = [set.outside[0], set.outside[1], set.interior ? fl : WALK];
    const sayAt = 0.16 + idx * 0.14;
    const xb = { bubble: r.icon || null, bk: (lt / d - 0.12 - idx * 0.08) / 0.12, say: r.say || r.think || null, think: !r.say && !!r.think, sk: (lt / d - sayAt) / 0.1 };
    if (doing === "walk_in" || doing === "run_in") {
      const wt = Math.min(doing === "run_in" ? 1.0 : 1.8, d * 0.5), k = lt / wt;
      if (k < 1) { const p = walkPath([outP, doorP, [s.x, s.z + (s.seat ? 0.4 : 0), fl]], k); put(c, { ...p, pose: doing === "run_in" ? "run" : "walk", t: lt + idx, emo }); walkerX = p.x; }
      else put(c, { ...base, ...xb, pose: "stand", sk: (lt - wt) / 0.3 });
    } else if (doing === "walk_out" || doing === "storm_out") {
      const angry = doing === "storm_out", t0 = d * 0.35, k = (lt - t0) / Math.min(1.8, d * 0.6);
      if (k < 0) put(c, { ...base, ...xb, pose: "stand", emo: angry ? "angry" : emo, bubble: angry ? "angry" : xb.bubble });
      else if (k < 1) { const p = walkPath([[s.x, s.z + (s.seat ? 0.4 : 0), fl], doorP, outP, [outP[0] + 1.5, outP[1], outP[2]]], k); put(c, { ...p, pose: "walk", t: lt + idx, emo: angry ? "angry" : emo, bubble: angry ? "angry" : null }); }
    } else if (doing === "walk_to") {
      const to = slotOf(set, r.to || "center"), t0 = d * 0.12, wt = Math.min(1.8, d * 0.55), k = (lt - t0) / wt;
      if (k < 0) put(c, { ...base, pose: "stand", emo });
      else if (k < 1) { const p = walkPath([[s.x, s.z + (s.seat ? 0.4 : 0), fl], [to.x, to.z + (to.seat ? 0.4 : 0), floorOf(set, to)]], k); put(c, { ...p, pose: "walk", t: lt + idx, emo }); walkerX = p.x; }
      else put(c, { x: to.x, z: to.z, ry: to.ry, y: floorOf(set, to), seat: to.seat, t: lt + idx, emo, ...xb, pose: "stand", sk: (lt - t0 - wt) / 0.3 });
    } else {
      let pose = POSES[doing] || "stand";
      if (pose === "phone" && shot.era === "past") pose = "call";
      put(c, { ...base, ...xb, pose, fast: emo === "stressed" || doing === "panic", bubble: xb.bubble || (doing === "sleep" ? "zzz" : null), bk: doing === "sleep" ? 1 : xb.bk });
    }
    if (r.who === shot.focus || (!focus && idx === 0)) focus = { c, s, fl };
  });
  // crowd
  const cr = shot.crowd || {}; const n = Math.min(6, cr.n || 0), spots = set.crowd || [];
  for (let i = 0; i < n; i++) {
    const s = slotOf(set, spots[i % spots.length]), fl = floorOf(set, s), off = i >= spots.length ? (i - spots.length + 1) * 0.45 : 0;
    const emo = cr.emo || "neutral", bubble = cr.icon || (emo === "angry" ? "angry" : emo === "happy" ? (i % 2 ? "heart" : null) : emo === "tired" ? "zzz" : null);
    const home = { x: s.x + off, z: s.z, ry: s.ry, y: fl, seat: off ? undefined : s.seat };
    if (cr.do === "leave") {
      const t0 = 0.25 * d + i * 0.25, k = (lt - t0) / 1.4;
      if (k < 0) put(crowd[i], { ...home, t: lt + i, emo: "angry", emoK: (lt - t0 + 0.6) / 0.4, bubble: "angry", bk: (lt - t0 + 0.6) / 0.3 });
      else if (k < 1) { const p = walkPath([[home.x, home.z + (home.seat ? 0.4 : 0), fl], [set.door[0], set.door[1], fl], [set.outside[0] + 2, set.outside[1], set.interior ? fl : WALK]], k); put(crowd[i], { ...p, pose: "walk", t: lt + i, emo: "angry", bubble: "angry" }); }
    } else if (cr.do === "arrive") {
      const t0 = 0.1 * d + i * Math.min(0.45, (d * 0.6) / n), k = (lt - t0) / 0.8;
      if (k < 0) continue;
      if (k < 1) { const p = walkPath([[set.outside[0], set.outside[1], set.interior ? fl : WALK], [set.door[0], set.door[1], fl], [home.x, home.z + (home.seat ? 0.4 : 0), fl]], k); put(crowd[i], { ...p, pose: "walk", t: lt + i, emo }); }
      else put(crowd[i], { ...home, t: lt + i, emo, bubble, bk: (k - 1) * 2 });
    } else {
      const pose = cr.do === "celebrate" ? "celebrate" : cr.do === "phone" ? (shot.era === "past" ? "call" : "phone") : cr.do === "talk" ? "talk" : "stand";
      put(crowd[i], { ...home, t: lt + i, emo, pose, bubble, bk: (lt / d - 0.2 - i * 0.07) / 0.12 });
    }
  }
  // props
  const fp = focus ? focus.c.root.position.clone() : new THREE.Vector3(set.x, FLOOR, -1);
  const fSeat = focus && focus.s.seat;
  const deskOf = focus && focus.s.desk ? focus.s.desk : { x: fp.x + 0.5, y: focus ? focus.fl : FLOOR, z: fp.z + 0.15 };
  if (P.has("papers_pile")) { FX.papers.visible = true; FX.papers.position.set(deskOf.x, deskOf.y, deskOf.z); const k = clamp(0.15 + lt / d); FX.papers.children.forEach((s, i) => (s.visible = i < 4 + k * 36)); }
  if (P.has("boxes_pile")) { FX.boxes.visible = true; FX.boxes.position.set(fp.x + 0.8, focus ? focus.fl : FLOOR, fp.z - 0.1);
    FX.boxes.children.forEach((b, i) => { const q = eob((lt / d) * 2.2 - i * 0.18); b.visible = q > 0.02; b.scale.setScalar(Math.max(0.01, q)); }); }
  if (P.has("money_rain")) FX.bills.forEach((b, i) => { const ph = (i * 0.37) % 1, y = 3.2 - ((lt * 0.9 + ph * 3.2) % 3.4); b.visible = true;
    b.position.set(fp.x + Math.sin(i * 2.3) * 1.5, y, fp.z + 0.6 + Math.cos(i * 1.7) * 0.6); b.material.rotation = Math.sin(lt * 3 + i) * 0.8; });
  if (P.has("confetti")) FX.confetti.forEach((m, i) => { const ph = (i * 0.173) % 1, y = 3.4 - ((lt * 1.2 + ph * 3.4) % 3.6); m.visible = lt > 0.15;
    m.position.set(fp.x + Math.sin(i * 1.9) * 1.6, y, fp.z + 0.4 + Math.cos(i * 2.9) * 0.8); m.rotation.set(lt * 4 + i, lt * 3 + i * 2, i); });
  if (P.has("lightbulb") && focus) { const k = eob((lt / d - 0.3) / 0.12); FX.bulb.visible = k > 0.01; const s = 0.42 * k * (1 + 0.06 * Math.sin(lt * 9));
    FX.bulb.scale.set(s, s, 1); FX.bulb.position.set(fp.x, fp.y + (fSeat ? 1.25 : 1.6), fp.z + 0.05);
    FX.sparks.forEach((sp, i) => { const a = (i / 6) * Math.PI * 2 + lt * 0.8, r = 0.32 * k; sp.visible = k > 0.5; sp.scale.set(0.14, 0.14, 1); sp.position.set(FX.bulb.position.x + Math.cos(a) * r, FX.bulb.position.y + Math.sin(a) * r, FX.bulb.position.z); }); }
  if (P.has("sparkles") && focus) FX.sparks.forEach((sp, i) => { const a = (i / 6) * Math.PI * 2 + lt * 1.5, r = 0.45 + 0.05 * Math.sin(lt * 5 + i); sp.visible = true; const s = 0.16 + 0.06 * Math.sin(lt * 7 + i); sp.scale.set(s, s, 1);
    sp.position.set(fp.x + Math.cos(a) * r, fp.y + 0.6 + Math.sin(a) * r * 0.8, fp.z + 0.2); });
  if (P.has("rain_cloud") && focus) { FX.rain.visible = true; FX.rain.position.set(fp.x, fp.y + (fSeat ? 1.35 : 1.7) + Math.sin(lt * 2) * 0.03, fp.z);
    FX.rain.userData.drops.forEach((dr, i) => { dr.position.y = -0.2 - ((lt * 2.2 + i * 0.13) % 0.6); }); }
  if (P.has("msg_bubbles")) FX.msgs.forEach((b, i) => { const q = (lt - 0.2 - i * 0.35) / 1.8; if (q < 0) return; b.visible = true; const s = 0.42 * eob(Math.min(1, q * 4));
    b.scale.set(s, s, 1); b.position.set(set.x - 1.5 + i * 0.6, (set.interior ? 2.2 : FLOOR + 2.0) + (i % 2) * 0.4 + Math.sin(t * 2 + i) * 0.05 + Math.min(q, 1) * 0.3, -1.2 + (i % 3) * 0.2); });
  if (P.has("clock_fast") && !set.clock) { FX.floatClock.visible = true; FX.floatClock.position.set(set.x + 1.2, FLOOR + 2.0, -1.5); FX.floatClock.material.rotation = -lt * 6; }
  // camera
  const camK = lt / d;
  if (walkerX !== null && shot.camera === "track") camTo({ p: [walkerX, 1.4, 6.0], l: [walkerX, 1.0, -0.6], push: 0 }, 0, t);
  else if (shot.camera === "close" && focus) {
    const fy = fSeat ? focus.s.seat - 0.27 : focus.fl;
    camTo({ p: [fp.x + 0.15, fy + (fSeat ? 1.55 : 1.2), fp.z + 4.3], l: [fp.x, fy + (fSeat ? 0.95 : 0.85), fp.z], push: 0.5 }, camK, t);
  } else camTo({ ...set.cams[shot.camera === "wide" ? "wide" : "medium"], push: shot.camera === "wide" ? 1.4 : 0.8 }, camK, t, !!shot.pull);
}

function resetFrame(t) {
  chars.forEach((c) => (c.root.visible = false));
  FX.bulb.visible = false; FX.floatClock.visible = false;
  for (const k of ["bills", "confetti", "sparks", "msgs"]) FX[k].forEach((m) => (m.visible = false));
  for (const k of ["rain", "papers", "boxes"]) FX[k].visible = false;
  clouds.forEach((c) => { const b = c.userData.base; c.position.set(b.x + t * c.userData.sp, b.y, b.z); });
}

function renderFrame(t) {
  const S = J.story; let shot = S.shots[S.shots.length - 1];
  for (const x of S.shots) if (t >= x.start && t < x.start + x.dur) { shot = x; break; }
  resetFrame(t);
  renderShot(shot, t - shot.start, shot.dur, t);
  renderer.render(scene, camera);
  return grab();
}

let _buf, _c2, _x2;
function grab() {
  const cv = $("gl"), w = cv.width, h = cv.height, gl = renderer.getContext();
  if (!_buf) { _buf = new Uint8ClampedArray(w * h * 4); _c2 = document.createElement("canvas"); _c2.width = w; _c2.height = h; _x2 = _c2.getContext("2d", { willReadFrequently: true }); }
  gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, _buf);
  _x2.putImageData(new ImageData(_buf, w, h), 0, 0);
  return _c2.toDataURL("image/jpeg", 0.94); // rows are bottom-up (flipped in Python)
}

window.setup = setup;
window.renderFrame = renderFrame;
window.__ready = true;
