// "Story" reels: a small cartoon 3D world (street, a cutaway shop, a cutaway home) where
// characters act out a tiny story beat by beat. Every frame is computed from (beat, local time)
// only, so frames can be rendered in parallel by several browsers.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

const $ = (id) => document.getElementById(id);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const eoc = (x) => 1 - Math.pow(1 - clamp(x), 3);
const eio = (x) => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const eob = (x) => { x = clamp(x); const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };
const lerp = (a, b, k) => a + (b - a) * k;
function rng(seed) { let s = (seed >>> 0) || 1; return () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 100000) / 100000; }; }

let J, W, H, R, renderer, scene, camera, sun, hemi, skyMat, fogC;
const night = { stars: null, moon: null, lights: [], windows: [] };
let ACC, ACC_D, ACC_L;
const props = [];      // shop props that pop in during "open"
let sign, signBase, closedSign, clockHands = [], clouds = [], shopPhone, phoneBadge, ripples = [], msgBubbles = [];
const chars = [];
let owner, hero, extras = [];
const SHOP_X = 0, HOME_X = 7.6, FLOOR = 0.12, WALK = 0.06;
let STATION; // where the customer gets served

// ------------------------------------------------------------------ helpers
function mat(c, o = {}) {
  return new THREE.MeshStandardMaterial({ color: c, roughness: o.r ?? 0.78, metalness: o.m ?? 0,
    emissive: o.e ?? 0x000000, emissiveIntensity: o.ei ?? 1, transparent: !!o.t, opacity: o.o ?? 1, map: o.map || null });
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

// ------------------------------------------------------------------ setup
async function setup(job) {
  J = job; W = job.width; H = job.height; R = rng(job.seed || 1);
  ACC = new THREE.Color(job.palette.accent); ACC_D = ACC.clone().lerp(new THREE.Color(0x0b1a14), 0.55); ACC_L = ACC.clone().lerp(new THREE.Color(0xffffff), 0.55);
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

  buildSky(); buildStreet(); buildShop(job.story); buildHome(); buildNeighbours(); buildCast();
  return { total: job.story.total, beats: job.story.beats };
}

// ------------------------------------------------------------------ world
function buildSky() {
  skyMat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { top: { value: new THREE.Color(0x6fb8ec) }, bottom: { value: new THREE.Color(0xeaf5fb) } },
    vertexShader: "varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.); }",
    fragmentShader: "uniform vec3 top; uniform vec3 bottom; varying vec3 vP; void main(){ float h = clamp(vP.y*1.6+.1,0.,1.); gl_FragColor = vec4(mix(bottom, top, h), 1.); }",
  });
  scene.add(new THREE.Mesh(new THREE.SphereGeometry(150, 32, 16), skyMat));
  fogC = new THREE.Color(0xe3f0f8); scene.fog = new THREE.Fog(fogC, 26, 90);
  hemi = new THREE.HemisphereLight(0xe6f3ff, 0xdacbb2, 1.35); scene.add(hemi);
  sun = new THREE.DirectionalLight(0xfff1dc, 2.3); sun.castShadow = true;
  sun.shadow.mapSize.set(1536, 1536); const s = sun.shadow.camera; s.left = -6; s.right = 6; s.top = 6; s.bottom = -4; s.near = 1; s.far = 40;
  sun.shadow.bias = -0.0006; sun.shadow.normalBias = 0.025; scene.add(sun, sun.target);
  // clouds
  const cm = mat(0xffffff, { r: 1, e: 0xffffff, ei: 0.25 });
  for (let i = 0; i < 9; i++) {
    const g = new THREE.Group(); const n = 4 + Math.floor(R() * 3);
    for (let k = 0; k < n; k++) { const m = add(g, sph(0.6 + R() * 0.5, 16, 12), cm, k * 0.75 - n * 0.37, (k % 2) * 0.25, R() * 0.3, false); m.scale.y = 0.75; }
    g.userData.base = new THREE.Vector3(-14 + R() * 36, 6.5 + R() * 4, -10 - R() * 14); g.userData.sp = 0.08 + R() * 0.12;
    scene.add(g); clouds.push(g);
  }
  // night: moon + stars (hidden by day)
  night.moon = add(scene, sph(0.9, 24, 16), mat(0xfff6d8, { e: 0xfff1c8, ei: 1.2 }), 9, 11, -30, false); night.moon.visible = false;
  const n = 260, pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { pos[i * 3] = -40 + R() * 80; pos[i * 3 + 1] = 6 + R() * 26; pos[i * 3 + 2] = -45 - R() * 10; }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  night.stars = new THREE.Points(g, new THREE.PointsMaterial({ size: 0.16, color: 0xffffff, fog: false })); night.stars.visible = false; scene.add(night.stars);
}

function buildStreet() {
  add(scene, new THREE.PlaneGeometry(220, 220), mat(0xe6e0d3), 0, 0, 0, false).rotation.x = -Math.PI / 2;
  const tiles = canvasTex(256, 64, (x, w, h) => { x.fillStyle = "#ebe7de"; x.fillRect(0, 0, w, h); x.strokeStyle = "rgba(0,0,0,.07)"; x.lineWidth = 2;
    for (let i = 0; i <= w; i += 64) { x.beginPath(); x.moveTo(i, 0); x.lineTo(i, h); x.stroke(); } });
  tiles.wrapS = THREE.RepeatWrapping; tiles.repeat.set(40, 1);
  add(scene, new THREE.BoxGeometry(80, WALK, 1.05), mat(0xffffff, { map: tiles }), 4, WALK / 2, 0.5, false);
  add(scene, new THREE.BoxGeometry(80, 0.12, 0.1), mat(0xd3cdc1), 4, 0.06, 1.05, false);
  add(scene, new THREE.PlaneGeometry(80, 14), mat(0x3e424b, { r: 0.95 }), 4, 0.004, 8.1, false).rotation.x = -Math.PI / 2;
  const dm = mat(0xf3e7b4);
  for (let x = -30; x < 40; x += 1.4) add(scene, new THREE.BoxGeometry(0.7, 0.006, 0.09), dm, x, 0.008, 3.4, false);
}

function cutaway(x0, w, d, h, wallC, floorTex) {
  const g = new THREE.Group(); g.position.x = x0; scene.add(g);
  const wall = mat(wallC);
  add(g, box(w + 0.3, FLOOR, d + 0.2, 0.01), mat(0xd9d2c4), 0, FLOOR / 2, -d / 2 + 0.05);
  const fl = add(g, new THREE.PlaneGeometry(w - 0.1, d), mat(0xffffff, { map: floorTex, r: 0.6 }), 0, FLOOR + 0.002, -d / 2, false); fl.rotation.x = -Math.PI / 2;
  add(g, new THREE.BoxGeometry(w, h, 0.15), wall, 0, FLOOR + h / 2, -d - 0.02);
  for (const s of [-1, 1]) add(g, new THREE.BoxGeometry(0.16, h + 0.02, d + 0.1), wall, s * (w / 2), FLOOR + h / 2, -d / 2 + 0.03);
  add(g, new THREE.BoxGeometry(w + 0.34, 0.2, d + 0.4), mat(0xf7f1e6), 0, FLOOR + h + 0.1, -d / 2 + 0.06);
  return g;
}

const BUSINESS = {
  salon: { station: "chair", title: "PRICES" }, clinic: { station: "chair", title: "SERVICES" }, restaurant: { station: "chair", title: "MENU" },
  cafe: { station: "counter", title: "MENU" }, store: { station: "counter", title: "TODAY" }, gym: { station: "counter", title: "PLANS" },
};

function buildShop(S) {
  const w = 4.2, d = 2.45, h = 2.6;
  const checker = canvasTex(256, 256, (x) => { for (let i = 0; i < 8; i++) for (let k = 0; k < 8; k++) { x.fillStyle = (i + k) % 2 ? "#2b2d33" : "#f4f1ea"; x.fillRect(i * 32, k * 32, 32, 32); } });
  checker.wrapS = checker.wrapT = THREE.RepeatWrapping; checker.repeat.set(4.5, 2.6);
  const g = cutaway(SHOP_X, w, d, h, 0xf6efe2, checker);
  const biz = BUSINESS[S.business] || BUSINESS.salon;
  // wainscot + trim
  add(g, box(w - 0.18, 0.82, 0.05, 0.01), mat(ACC_D.getHex(), { r: 0.55 }), 0, FLOOR + 0.41, -d + 0.08);
  add(g, box(w - 0.18, 0.05, 0.07, 0.01), mat(0xd9b45f, { r: 0.4, m: 0.3 }), 0, FLOOR + 0.84, -d + 0.08);
  // facade: band + sign + awning + pillars
  add(g, box(w + 0.34, 0.62, 0.22, 0.03), mat(0xf7f1e6), 0, FLOOR + h - 0.2, 0.06);
  add(g, box(w + 0.36, 0.08, 0.24, 0.01), mat(ACC.getHex()), 0, FLOOR + h - 0.48, 0.07);
  for (const s of [-1, 1]) add(g, box(0.24, h, 0.26, 0.03), mat(0xf7f1e6), s * (w / 2 + 0.04), FLOOR + h / 2, 0.02);
  const signTex = canvasTex(1024, 256, (x, W2, H2) => {
    x.fillStyle = hex(ACC_D); rr(x, 0, 0, W2, H2, 40); x.fill();
    x.strokeStyle = "#e3c26a"; x.lineWidth = 12; rr(x, 14, 14, W2 - 28, H2 - 28, 30); x.stroke();
    x.fillStyle = "#ffe9a8"; for (let i = 0; i < 22; i++) { x.beginPath(); x.arc(46 + i * 44, 34, 6, 0, 7); x.fill(); x.beginPath(); x.arc(46 + i * 44, H2 - 34, 6, 0, 7); x.fill(); }
    let fs = 132; x.font = `800 ${fs}px Inter`; const name = (S.business_name || "Shop").toUpperCase();
    while (x.measureText(name).width > W2 - 120 && fs > 50) { fs -= 6; x.font = `800 ${fs}px Inter`; }
    x.fillStyle = "#fff6dc"; x.textAlign = "center"; x.textBaseline = "middle"; x.fillText(name, W2 / 2, H2 / 2 + 6);
  });
  sign = new THREE.Group(); sign.position.set(0, FLOOR + h + 0.5, 0.2); g.add(sign); signBase = sign.position.y;
  add(sign, box(2.7, 0.68, 0.14, 0.05), mat(ACC_D.getHex()), 0, 0, 0);
  add(sign, new THREE.PlaneGeometry(2.62, 0.65), new THREE.MeshStandardMaterial({ map: signTex, roughness: 0.5, emissive: 0xffffff, emissiveMap: signTex, emissiveIntensity: 0.18 }), 0, 0, 0.075, false);
  for (const s of [-1, 1]) add(sign, cyl(0.02, 0.02, 0.5, 8), mat(0x444444, { m: 0.6 }), s * 1.0, -0.4, -0.05);
  closedSign = new THREE.Sprite(new THREE.SpriteMaterial({ map: canvasTex(256, 128, (x) => { x.fillStyle = "#e0483f"; rr(x, 8, 8, 240, 112, 24); x.fill();
    x.fillStyle = "#fff"; x.font = "800 64px Inter"; x.textAlign = "center"; x.textBaseline = "middle"; x.fillText("CLOSED", 128, 68); }), depthWrite: false }));
  closedSign.scale.set(0.7, 0.35, 1); closedSign.position.set(-0.9, FLOOR + 1.6, 0.25); closedSign.visible = false; g.add(closedSign);
  // awning
  const aw = canvasTex(512, 64, (x) => { for (let i = 0; i < 16; i++) { x.fillStyle = i % 2 ? "#ffffff" : hex(ACC); x.fillRect(i * 32, 0, 32, 64); } });
  const awning = add(g, new THREE.PlaneGeometry(w + 0.2, 0.62), mat(0xffffff, { map: aw }), 0, FLOOR + h - 0.66, 0.36, true);
  awning.rotation.x = -1.05; awning.material.side = THREE.DoubleSide;
  // back wall: clock, board, lamps, plants
  const clock = new THREE.Group(); clock.position.set(-0.15, FLOOR + 1.95, -d + 0.1); g.add(clock); props.push(clock);
  add(clock, cyl(0.24, 0.24, 0.06, 32), mat(0x2c2c30), 0, 0, 0).rotation.x = Math.PI / 2;
  add(clock, cyl(0.205, 0.205, 0.07, 32), mat(0xffffff), 0, 0, 0.01).rotation.x = Math.PI / 2;
  for (let i = 0; i < 12; i++) { const a = (i / 12) * Math.PI * 2; add(clock, new THREE.BoxGeometry(0.012, 0.035, 0.01), mat(0x222222), Math.sin(a) * 0.17, Math.cos(a) * 0.17, 0.05, false).rotation.z = -a; }
  for (const [len, wd] of [[0.15, 0.022], [0.11, 0.03]]) { const p = new THREE.Group(); p.position.z = 0.06; clock.add(p); add(p, new THREE.BoxGeometry(wd, len, 0.01), mat(0x16161a), 0, len / 2 - 0.02, 0, false); clockHands.push(p); }
  const board = canvasTex(400, 460, (x, w2, h2) => {
    x.fillStyle = "#26302c"; rr(x, 0, 0, w2, h2, 22); x.fill(); x.strokeStyle = "#7a5a3a"; x.lineWidth = 18; rr(x, 9, 9, w2 - 18, h2 - 18, 18); x.stroke();
    x.fillStyle = "#f6e7b8"; x.font = "800 54px Inter"; x.textAlign = "center"; x.fillText(biz.title, w2 / 2, 92);
    x.font = "600 36px Inter"; const sv = (S.services && S.services.length ? S.services : [["Basic", "$15"], ["Plus", "$25"], ["Full", "$40"]]).slice(0, 4);
    sv.forEach(([n, p], i) => { x.textAlign = "left"; x.fillStyle = "#fff"; x.fillText(String(n).slice(0, 11), 44, 170 + i * 70); x.textAlign = "right"; x.fillStyle = "#f6e7b8"; x.fillText(String(p).slice(0, 5), w2 - 44, 170 + i * 70); });
  });
  const bd = new THREE.Group(); bd.position.set(-1.05, FLOOR + 1.75, -d + 0.1); g.add(bd); props.push(bd);
  add(bd, new THREE.PlaneGeometry(0.62, 0.72), mat(0xffffff, { map: board, r: 0.9 }), 0, 0, 0, false);
  for (const x of [-1.0, 0.95]) {
    const lp = new THREE.Group(); lp.position.set(x, FLOOR + h, -1.0); g.add(lp); props.push(lp);
    add(lp, cyl(0.008, 0.008, 0.45, 6), mat(0x333333), 0, -0.22, 0, false);
    add(lp, new THREE.ConeGeometry(0.17, 0.16, 24, 1, true), mat(ACC_D.getHex(), { r: 0.5 }), 0, -0.5, 0, false).material.side = THREE.DoubleSide;
    add(lp, sph(0.06, 12, 8), mat(0xfff3d0, { e: 0xffe2a8, ei: 2 }), 0, -0.55, 0, false);
    const pl = new THREE.PointLight(0xffdca8, 0.9, 4, 1.6); pl.position.set(x, FLOOR + h - 0.6, -1.0); g.add(pl); night.lights.push(pl);
  }
  plant(g, -1.85, FLOOR, -d + 0.35, 1.0); plant(g, 1.85, FLOOR, -0.55, 0.85);
  // waiting couch (left)
  const couch = sofa(ACC_D.clone().lerp(ACC, 0.35).getHex(), 1.65); couch.position.set(-1.12, FLOOR, -d + 0.42); g.add(couch); props.push(couch);
  // station (right)
  STATION = { kind: biz.station, ownerAt: [1.6, -1.35, -1.0], custAt: [0.95, -1.4, 0], seatY: 0 };
  if (S.business === "salon" || !BUSINESS[S.business]) salonStation(g, d);
  else if (S.business === "clinic") clinicStation(g, d);
  else if (S.business === "restaurant") restaurantStation(g, d);
  else counterStation(g, d, S.business);
  // ringing phone on a small shelf next to the station
  const shelf = add(g, box(0.36, 0.04, 0.22, 0.01), mat(0xd9b45f, { r: 0.5 }), 1.75, FLOOR + 1.2, -d + 0.2);
  props.push(shelf);
  shopPhone = new THREE.Group(); shopPhone.position.set(1.75, FLOOR + 1.36, -d + 0.22); g.add(shopPhone);
  add(shopPhone, box(0.13, 0.24, 0.02, 0.015), mat(0x1c1c20, { r: 0.3 }), 0, 0, 0);
  shopPhone.userData.screen = add(shopPhone, new THREE.PlaneGeometry(0.11, 0.21), mat(0x111111, { e: ACC.getHex(), ei: 0.6 }), 0, 0, 0.012, false);
  shopPhone.rotation.x = -0.25;
  phoneBadge = new THREE.Sprite(new THREE.SpriteMaterial({ depthWrite: false })); phoneBadge.scale.set(0.2, 0.2, 1); phoneBadge.position.set(1.86, FLOOR + 1.56, -d + 0.3); g.add(phoneBadge);
  for (let i = 0; i < 5; i++) { const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: bubbleTex("msg"), depthWrite: false })); s.visible = false; g.add(s); msgBubbles.push(s); }
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

function plant(g, x, y, z, s = 1) {
  const p = new THREE.Group(); p.position.set(x, y, z); p.scale.setScalar(s); g.add(p); props.push(p);
  add(p, cyl(0.15, 0.11, 0.3, 20), mat(0xc96f45, { r: 0.8 }), 0, 0.15, 0);
  const lm = mat(0x4f9d57, { r: 0.7 });
  for (let i = 0; i < 7; i++) { const a = (i / 7) * Math.PI * 2; const l = add(p, sph(0.12, 12, 8), lm, Math.cos(a) * 0.1, 0.42 + (i % 3) * 0.12, Math.sin(a) * 0.1); l.scale.set(0.7, 1.4, 0.5); l.rotation.z = Math.cos(a) * 0.5; l.rotation.x = Math.sin(a) * 0.5; }
  return p;
}

function salonStation(g, d) {
  const st = new THREE.Group(); st.position.set(0.95, FLOOR, -1.45); g.add(st); props.push(st);
  add(st, cyl(0.22, 0.26, 0.05, 24), mat(0xdcdcdc, { m: 0.8, r: 0.3 }), 0, 0.03, 0);
  add(st, cyl(0.05, 0.05, 0.3, 12), mat(0xdcdcdc, { m: 0.8, r: 0.3 }), 0, 0.2, 0);
  const cm = mat(0x2b3532, { r: 0.6 });
  add(st, box(0.56, 0.14, 0.5, 0.05), cm, 0, 0.42, 0);
  add(st, box(0.56, 0.62, 0.12, 0.05), cm, 0, 0.78, -0.22);
  for (const s of [-1, 1]) add(st, box(0.08, 0.06, 0.42, 0.02), mat(0xdcdcdc, { m: 0.8, r: 0.3 }), s * 0.3, 0.6, 0.02);
  const mir = new THREE.Group(); mir.position.set(0.95, FLOOR + 1.45, -d + 0.1); g.add(mir); props.push(mir);
  add(mir, new THREE.TorusGeometry(0.4, 0.045, 12, 40), mat(0xd9b45f, { m: 0.6, r: 0.35 }), 0, 0, 0);
  add(mir, new THREE.CircleGeometry(0.4, 40), mat(0xcfe9f2, { m: 0.2, r: 0.15 }), 0, 0, -0.01, false);
  const pole = canvasTex(64, 256, (x) => { for (let i = 0; i < 16; i++) { x.fillStyle = ["#e0483f", "#ffffff", "#3d6fe0", "#ffffff"][i % 4]; x.save(); x.translate(0, i * 20); x.transform(1, 0.4, 0, 1, 0, 0); x.fillRect(-30, 0, 140, 20); x.restore(); } });
  const bp = add(g, cyl(0.06, 0.06, 0.5, 16), mat(0xffffff, { map: pole }), 1.95, FLOOR + 1.55, -d + 0.15); props.push(bp);
  STATION = { kind: "chair", custAt: [0.95, -1.45], custRy: 0, seatTop: FLOOR + 0.49, ownerAt: [1.52, -1.05], ownerRy: -0.55 };
}

function clinicStation(g, d) {
  salonStation(g, d);
  const cross = new THREE.Group(); cross.position.set(0.95, FLOOR + 1.55, -d + 0.1); g.add(cross); props.push(cross);
  g.children.filter((c) => c.position.x === 0.95 && Math.abs(c.position.y - (FLOOR + 1.45)) < 0.01).forEach((c) => { c.visible = false; });
  add(cross, box(0.5, 0.5, 0.04, 0.05), mat(0xffffff), 0, 0, 0);
  add(cross, box(0.12, 0.36, 0.05, 0.01), mat(ACC.getHex()), 0, 0, 0.01); add(cross, box(0.36, 0.12, 0.05, 0.01), mat(ACC.getHex()), 0, 0, 0.01);
}

function restaurantStation(g, d) {
  const t = new THREE.Group(); t.position.set(1.25, FLOOR, -1.4); g.add(t); props.push(t);
  add(t, cyl(0.38, 0.38, 0.04, 28), mat(0xf7f1e6), 0, 0.72, 0); add(t, cyl(0.04, 0.06, 0.7, 12), mat(0x3a2a1e), 0, 0.36, 0);
  add(t, cyl(0.12, 0.12, 0.015, 24), mat(0xffffff), -0.12, 0.75, 0.08); add(t, cyl(0.05, 0.04, 0.1, 12), mat(0xbfe3f0, { t: true, o: 0.7 }), 0.15, 0.8, -0.05);
  const ch = new THREE.Group(); ch.position.set(0.72, FLOOR, -1.4); g.add(ch); props.push(ch);
  add(ch, box(0.4, 0.06, 0.4, 0.02), mat(0x8a5a3b), 0, 0.46, 0); add(ch, box(0.4, 0.5, 0.05, 0.02), mat(0x8a5a3b), -0.18, 0.72, 0).rotation.y = Math.PI / 2;
  for (const [a, b] of [[-0.16, -0.16], [0.16, -0.16], [-0.16, 0.16], [0.16, 0.16]]) add(ch, cyl(0.02, 0.02, 0.45, 6), mat(0x3a2a1e), a, 0.22, b);
  STATION = { kind: "chair", custAt: [0.74, -1.4], custRy: Math.PI / 2, seatTop: FLOOR + 0.49, ownerAt: [1.55, -0.85], ownerRy: -0.6 };
}

function counterStation(g, d, kind) {
  const c = new THREE.Group(); c.position.set(1.0, FLOOR, -1.25); g.add(c); props.push(c);
  add(c, box(1.4, 0.86, 0.5, 0.03), mat(ACC_D.clone().lerp(ACC, 0.2).getHex(), { r: 0.6 }), 0, 0.43, 0);
  add(c, box(1.48, 0.05, 0.58, 0.02), mat(0xc9975f, { r: 0.5 }), 0, 0.88, 0);
  if (kind === "cafe") {
    add(c, box(0.36, 0.34, 0.3, 0.03), mat(0xd8d8d8, { m: 0.7, r: 0.3 }), 0.35, 1.08, -0.05);
    add(c, cyl(0.05, 0.04, 0.09, 12), mat(0xffffff), -0.1, 0.96, 0.1); add(c, cyl(0.05, 0.04, 0.09, 12), mat(0xffffff), -0.3, 0.96, 0.05);
    add(c, sph(0.12, 16, 10), mat(0xe8c39a), -0.48, 0.98, -0.05).scale.y = 0.6;
  } else if (kind === "gym") {
    for (let i = 0; i < 3; i++) { const db = add(g, cyl(0.03, 0.03, 0.34, 8), mat(0x333333, { m: 0.6 }), -0.25 + i * 0.12 + 0.3, FLOOR + 0.2, -d + 0.3); db.rotation.z = Math.PI / 2; }
    add(c, box(0.3, 0.2, 0.2, 0.02), mat(0x222222), 0.3, 1.0, 0);
  } else {
    add(c, box(0.34, 0.2, 0.26, 0.03), mat(0x2b2b30), 0.35, 1.0, 0);
    const sh = new THREE.Group(); sh.position.set(-0.1, FLOOR, -d + 0.2); g.add(sh); props.push(sh);
    for (let r = 0; r < 3; r++) { add(sh, box(0.9, 0.03, 0.26, 0.01), mat(0xc9975f), 0, 1.05 + r * 0.32, 0);
      for (let k = 0; k < 4; k++) add(sh, box(0.16, 0.2, 0.16, 0.02), mat([0xe0483f, 0x3d7fe0, 0xf2c240, 0x3fb07a][(k + r) % 4]), -0.32 + k * 0.21, 1.17 + r * 0.32, 0); }
  }
  STATION = { kind: "counter", custAt: [0.95, -0.62], custRy: Math.PI, seatTop: 0, ownerAt: [1.0, -1.75], ownerRy: 0 };
}

function buildHome() {
  const wood = canvasTex(256, 256, (x) => { for (let i = 0; i < 8; i++) { x.fillStyle = i % 2 ? "#c8955f" : "#d4a36d"; x.fillRect(0, i * 32, 256, 32); x.fillStyle = "rgba(0,0,0,.06)"; x.fillRect(0, i * 32, 256, 2); } });
  wood.wrapS = wood.wrapT = THREE.RepeatWrapping; wood.repeat.set(2, 2);
  const w = 3.6, d = 2.3, h = 2.4;
  const g = cutaway(HOME_X, w, d, h, 0xf6dcc2, wood);
  // gable roof
  const sh = new THREE.Shape(); sh.moveTo(-w / 2 - 0.35, 0); sh.lineTo(0, 1.05); sh.lineTo(w / 2 + 0.35, 0); sh.lineTo(-w / 2 - 0.35, 0);
  const roof = add(g, new THREE.ExtrudeGeometry(sh, { depth: d + 0.5, bevelEnabled: false }), mat(0xc8473d, { r: 0.7 }), 0, FLOOR + h + 0.2, -d - 0.25);
  add(g, box(0.3, 0.6, 0.3, 0.02), mat(0xb03b33), 1.0, FLOOR + h + 0.9, -d / 2);
  add(g, new THREE.ShapeGeometry(sh), mat(0xf6e8d6), 0, FLOOR + h + 0.2, 0.26, false).scale.set(0.86, 0.8, 1);
  void roof;
  // window with sky + curtains
  const sky = canvasTex(128, 128, (x) => { const gr = x.createLinearGradient(0, 0, 0, 128); gr.addColorStop(0, "#7cc2ee"); gr.addColorStop(1, "#dff1fb"); x.fillStyle = gr; x.fillRect(0, 0, 128, 128);
    x.fillStyle = "#fff"; x.beginPath(); x.arc(40, 50, 14, 0, 7); x.arc(58, 46, 18, 0, 7); x.arc(76, 52, 13, 0, 7); x.fill(); });
  add(g, box(1.1, 0.85, 0.06, 0.02), mat(0xffffff), -0.85, FLOOR + 1.55, -d + 0.07);
  night.windows.push(add(g, new THREE.PlaneGeometry(0.96, 0.72), mat(0xffffff, { map: sky, e: 0xffffff, ei: 0.25 }), -0.85, FLOOR + 1.55, -d + 0.11, false));
  for (const s of [-1, 1]) add(g, box(0.22, 1.0, 0.05, 0.03), mat(0xd04a3c, { r: 0.9 }), -0.85 + s * 0.62, FLOOR + 1.5, -d + 0.14);
  add(g, box(0.5, 0.38, 0.04, 0.02), mat(0xc9975f), 0.9, FLOOR + 1.65, -d + 0.08);
  add(g, new THREE.PlaneGeometry(0.42, 0.3), mat(0x9fd3a6), 0.9, FLOOR + 1.65, -d + 0.105, false);
  const couch = sofa(0x3f66c4, 1.75); couch.position.set(0, FLOOR, -d + 0.42); g.add(couch);
  const rug = add(g, new THREE.CircleGeometry(1, 40), mat(0xe9c46a, { r: 1 }), 0, FLOOR + 0.006, -0.95, false); rug.rotation.x = -Math.PI / 2; rug.scale.set(1.3, 0.55, 1);
  add(g, cyl(0.02, 0.02, 1.2, 8), mat(0x333333), 1.35, FLOOR + 0.6, -d + 0.35); add(g, cyl(0.04, 0.16, 0.12, 16), mat(0x333333), 1.35, FLOOR + 0.03, -d + 0.35);
  add(g, new THREE.ConeGeometry(0.22, 0.26, 24, 1, true), mat(0xf6e3b4, { e: 0xffe3a0, ei: 0.4 }), 1.35, FLOOR + 1.28, -d + 0.35).material.side = THREE.DoubleSide;
  const hl = new THREE.PointLight(0xffd9a0, 0.6, 4, 1.6); hl.position.set(1.35, FLOOR + 1.2, -d + 0.5); g.add(hl); night.lights.push(hl);
  const pl = plant(g, -1.5, FLOOR, -0.6, 1.0); props.splice(props.indexOf(pl), 1);
  HOME = { couchAt: [0, -d + 0.45], seatTop: FLOOR + 0.47 };
}
let HOME;

function buildNeighbours() {
  const win = (c) => canvasTex(256, 512, (x, w, h) => { x.fillStyle = c; x.fillRect(0, 0, w, h);
    for (let r = 0; r < 5; r++) for (let k = 0; k < 3; k++) { x.fillStyle = "#cfe6f2"; x.fillRect(30 + k * 75, 40 + r * 95, 48, 60); x.fillStyle = "rgba(255,255,255,.5)"; x.fillRect(30 + k * 75, 40 + r * 95, 48, 8); } });
  const bld = (x, w, h, c, z = -1.3) => add(scene, box(w, h, 2.4, 0.04), mat(0xffffff, { map: win(c) }), x, h / 2, z - 1.2);
  bld(-4.75, 4.8, 4.4, "#e8cfa9"); bld(11.9, 4.4, 5.2, "#cfdfe9"); bld(-9.8, 5, 6.4, "#e9d7e4"); bld(16.6, 5, 4.2, "#dfe9cf");
  const far = ["#cfdbe6", "#d9e3ec", "#c8d6e2", "#e1e8ef"];
  for (let i = 0; i < 18; i++) { const fh = 5 + R() * 9; add(scene, box(2 + R() * 2.5, fh, 2, 0.02), mat(far[i % 4], { r: 1 }), -22 + i * 2.8 + R(), fh / 2, -12 - R() * 6, false); }
  for (const x of [3.9, -7.3, 10.6, 14.2]) tree(x, 0.32);
  for (const x of [-2.9, 5.7]) lamp(x);
}
function tree(x, z) {
  const g = new THREE.Group(); g.position.set(x, WALK, z); scene.add(g);
  add(g, cyl(0.07, 0.1, 1.3, 10), mat(0x7a5236), 0, 0.65, 0);
  const lm = [mat(0x5daa5a), mat(0x6bb964), mat(0x4f9a50)];
  [[0, 1.65, 0, 0.62], [-0.38, 1.4, 0.05, 0.42], [0.4, 1.45, -0.05, 0.45], [0, 2.05, 0, 0.42]].forEach(([a, b, c, r], i) => add(g, sph(r, 18, 12), lm[i % 3], a, b, c));
}
function lamp(x) {
  const g = new THREE.Group(); g.position.set(x, WALK, 0.85); scene.add(g);
  add(g, cyl(0.04, 0.05, 2.6, 10), mat(0x2f3a36, { m: 0.4 }), 0, 1.3, 0);
  const bulb = add(g, sph(0.12, 14, 10), mat(0xfff7e0, { e: 0xffe6b0, ei: 0.3 }), 0, 2.66, 0); night.lamps = (night.lamps || []).concat([bulb]);
}

// ------------------------------------------------------------------ characters
const SKINS = [0xf2c9a5, 0xe3b08a, 0xc68a62, 0x9a6643, 0xf6d6bd, 0xd9a07a];
const SHIRTS = [0x7b5cd6, 0x3d7fe0, 0xf08a3c, 0xf2c240, 0xe0483f, 0x3fb07a, 0xe86fa3, 0x2bb3a3];
const HAIRS = [0x2a1d17, 0x3b2a1f, 0x14110f, 0x6b4428, 0xb07a45];
const STYLES = ["short", "curly", "bun", "long", "short", "curly"];

function makeChar(o) {
  const root = new THREE.Group(), body = new THREE.Group(); root.add(body); scene.add(root);
  const skin = mat(o.skin, { r: 0.6 }), shirt = mat(o.shirt, { r: 0.85 }), pants = mat(o.pants ?? 0x2f3644), shoe = mat(0x1d1d22, { r: 0.5 }), hairM = mat(o.hair, { r: 0.9 });
  const legs = [];
  for (const s of [-1, 1]) { const p = new THREE.Group(); p.position.set(s * 0.075, 0.32, 0); body.add(p);
    add(p, new THREE.CapsuleGeometry(0.06, 0.16, 4, 10), pants, 0, -0.14, 0); add(p, box(0.11, 0.07, 0.17, 0.03), shoe, 0, -0.29, 0.03); legs.push(p); }
  const torso = add(body, new THREE.CapsuleGeometry(0.165, 0.13, 6, 16), shirt, 0, 0.5, 0); torso.scale.set(1, 1, 0.8);
  if (o.apron) add(body, box(0.26, 0.3, 0.03, 0.02), mat(0xf7f7f2), 0, 0.45, 0.125);
  const arms = [];
  for (const s of [-1, 1]) { const p = new THREE.Group(); p.position.set(s * 0.2, 0.6, 0); body.add(p);
    add(p, new THREE.CapsuleGeometry(0.047, 0.15, 4, 10), shirt, 0, -0.1, 0); add(p, sph(0.052, 12, 10), skin, 0, -0.22, 0); arms.push(p); }
  const head = new THREE.Group(); head.position.set(0, 0.86, 0); body.add(head);
  const headM = skin.clone(); add(head, sph(0.215, 28, 20), headM, 0, 0.02, 0);
  for (const s of [-1, 1]) add(head, sph(0.05, 10, 8), headM, s * 0.21, 0.0, 0);
  add(head, sph(0.03, 10, 8), headM, 0, -0.005, 0.212);
  const eyeM = mat(0x15151a, { r: 0.25 });
  for (const s of [-1, 1]) { add(head, sph(0.03, 12, 10), eyeM, s * 0.078, 0.035, 0.192, false); add(head, sph(0.009, 6, 6), mat(0xffffff, { e: 0xffffff, ei: 0.6 }), s * 0.078 + 0.01, 0.047, 0.218, false); }
  const brows = [-1, 1].map((s) => { const b = add(head, box(0.075, 0.018, 0.02, 0.008), hairM, s * 0.078, 0.1, 0.198, false); return b; });
  for (const s of [-1, 1]) add(head, sph(0.032, 10, 8), mat(0xf29a8f, { r: 0.9, t: true, o: 0.55 }), s * 0.12, -0.04, 0.178, false).scale.set(1, 0.6, 0.4);
  const mouth = add(head, new THREE.TorusGeometry(0.045, 0.012, 8, 18, Math.PI), mat(0x6e2b2b, { r: 0.6 }), 0, -0.075, 0.2, false);
  const cap = add(head, new THREE.SphereGeometry(0.228, 28, 14, 0, Math.PI * 2, 0, 1.3), hairM, 0, 0.03, -0.012); cap.rotation.x = -0.32;
  if (o.style === "curly") for (let i = 0; i < 9; i++) { const a = (i / 9) * Math.PI * 2; add(head, sph(0.075, 10, 8), hairM, Math.cos(a) * 0.15, 0.17 + (i % 2) * 0.03, Math.sin(a) * 0.13 - 0.02); }
  if (o.style === "bun") add(head, sph(0.095, 14, 10), hairM, 0, 0.24, -0.1);
  if (o.style === "long") { const l = add(head, new THREE.CapsuleGeometry(0.17, 0.18, 4, 14), hairM, 0, -0.1, -0.08); l.scale.set(1.18, 1, 0.75); }
  if (o.beard) { const b = add(head, new THREE.SphereGeometry(0.222, 24, 12, 0, Math.PI * 2, Math.PI * 0.56, Math.PI * 0.36), hairM, 0, 0.0, 0.01); b.rotation.x = 0.15; mouth.position.z = 0.215; }
  const phone = new THREE.Group(); phone.position.set(0, 0.5, 0.24); body.add(phone); phone.rotation.x = -0.7;
  add(phone, box(0.09, 0.16, 0.014, 0.012), mat(0x1c1c20, { r: 0.3 }), 0, 0, 0, false);
  const pscreen = add(phone, new THREE.PlaneGeometry(0.076, 0.142), mat(0x0f2a20, { e: ACC.getHex(), ei: 1.0 }), 0, 0, 0.008, false);
  const bubble = new THREE.Sprite(new THREE.SpriteMaterial({ depthWrite: false, depthTest: false })); bubble.position.set(0.18, 1.36, 0); bubble.renderOrder = 10; root.add(bubble);
  const c = { root, body, legs, arms, head, headM, skin: new THREE.Color(o.skin), brows, mouth, phone, pscreen, bubble, ph: R() * 6 };
  chars.push(c); return c;
}

function buildCast() {
  owner = makeChar({ skin: SKINS[1 + Math.floor(R() * 3)], shirt: ACC_D.getHex(), hair: HAIRS[0], style: "short", beard: R() < 0.6, apron: true });
  hero = makeChar({ skin: SKINS[Math.floor(R() * SKINS.length)], shirt: 0xf08a3c, hair: HAIRS[2], style: "curly", pants: 0x34405a });
  const n = 6;
  for (let i = 0; i < n; i++) extras.push(makeChar({ skin: SKINS[(i * 2 + 1) % SKINS.length], shirt: SHIRTS[i % SHIRTS.length], hair: HAIRS[i % HAIRS.length], style: STYLES[i % STYLES.length] }));
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
    else if (kind === "zzz") sym("zzz", "#7b5cd6", 76); else if (kind === "check") { x.strokeStyle = hex(ACC); x.lineWidth = 22; x.lineCap = "round"; x.beginPath(); x.moveTo(78, 108); x.lineTo(112, 140); x.lineTo(172, 76); x.stroke(); }
    else if (kind === "heart") { x.fillStyle = "#e8455a"; x.beginPath(); x.moveTo(124, 160); x.bezierCurveTo(30, 100, 70, 30, 124, 78); x.bezierCurveTo(178, 30, 218, 100, 124, 160); x.fill(); }
    else if (kind === "angry") { x.strokeStyle = "#e0453a"; x.lineWidth = 16; x.lineCap = "round"; for (const [a, b] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) { x.beginPath(); x.moveTo(124 + a * 18, 104 + b * 18); x.quadraticCurveTo(124 + a * 50, 104 + b * 8, 124 + a * 52, 104 + b * 46); x.stroke(); } }
    else if (kind === "msg") { x.fillStyle = hex(ACC); rr(x, 64, 70, 120, 80, 26); x.fill(); x.fillStyle = "#fff"; for (let i = 0; i < 3; i++) { x.beginPath(); x.arc(96 + i * 28, 110, 9, 0, 7); x.fill(); } }
  });
  return _bub[kind];
}
const _num = {};
function badgeTex(n) {
  if (_num[n]) return _num[n];
  _num[n] = canvasTex(128, 128, (x) => { x.fillStyle = "#e0483f"; x.beginPath(); x.arc(64, 64, 58, 0, 7); x.fill(); x.fillStyle = "#fff"; x.font = `800 ${n > 9 ? 58 : 70}px Inter`; x.textAlign = "center"; x.textBaseline = "middle"; x.fillText(String(n), 64, 70); });
  return _num[n];
}

// ------------------------------------------------------------------ poses
function put(c, o) {
  c.root.visible = true;
  c.root.position.set(o.x, o.y ?? FLOOR, o.z); c.root.rotation.set(0, o.ry ?? 0, 0);
  c.root.scale.setScalar(o.scale ?? 1);
  const t = o.t ?? 0, p = o.pose || "stand";
  c.body.position.set(0, 0, 0); c.body.rotation.set(0, 0, 0); c.head.rotation.set(0, 0, 0);
  c.legs.forEach((l) => l.rotation.set(0, 0, 0)); c.arms.forEach((a, i) => a.rotation.set(0, 0, (i ? 1 : -1) * 0.1));
  c.phone.visible = false;
  const breath = Math.sin(t * 2.4 + c.ph) * 0.01;
  if (p === "walk") {
    const s = Math.sin(t * 11 + c.ph);
    c.legs[0].rotation.x = s * 0.65; c.legs[1].rotation.x = -s * 0.65; c.arms[0].rotation.x = -s * 0.55; c.arms[1].rotation.x = s * 0.55;
    c.body.position.y = Math.abs(Math.cos(t * 11 + c.ph)) * 0.035; c.body.rotation.x = 0.06;
  } else if (p === "sit" || p === "sitphone") {
    c.root.position.y = (o.seat ?? FLOOR + 0.47) - 0.27;
    c.legs.forEach((l) => (l.rotation.x = -1.35)); c.body.position.y = breath;
  } else { c.body.position.y = breath; }
  if (p === "phone" || p === "sitphone") {
    c.arms.forEach((a, i) => { a.rotation.x = -1.05; a.rotation.z = (i ? -1 : 1) * 0.35; }); c.phone.visible = true; c.head.rotation.x = 0.28;
    c.pscreen.material.emissiveIntensity = 0.8 + 0.4 * Math.sin(t * 6);
  }
  if (p === "work") { c.arms[1].rotation.x = -1.0 + Math.sin(t * (o.fast ? 16 : 8)) * 0.3; c.arms[0].rotation.x = -0.7 + Math.sin(t * (o.fast ? 14 : 6) + 1) * 0.15; c.head.rotation.x = 0.15; c.body.rotation.y = Math.sin(t * 2) * 0.06; }
  if (p === "wave") { c.arms[1].rotation.z = 2.5 + Math.sin(t * 10) * 0.35; }
  if (o.shake) c.head.rotation.y = Math.sin(t * 14) * 0.25;
  // emotion
  const e = o.emo || "neutral";
  c.headM.color.copy(c.skin); c.brows[0].rotation.z = 0; c.brows[1].rotation.z = 0; c.brows.forEach((b) => (b.position.y = 0.1));
  c.mouth.rotation.set(0, 0, Math.PI); c.mouth.scale.set(1, 1, 1); c.mouth.position.y = -0.075;
  if (e === "happy") { c.mouth.scale.set(1.3, 1.5, 1); c.brows.forEach((b) => (b.position.y = 0.115)); }
  if (e === "sad" || e === "angry") { c.mouth.rotation.z = 0; c.mouth.position.y = -0.11; c.mouth.scale.set(0.9, 0.7, 1); }
  if (e === "angry") { c.headM.color.copy(c.skin).lerp(new THREE.Color(0xe2493c), clamp(o.emoK ?? 1) * 0.6); c.brows[0].rotation.z = -0.5; c.brows[1].rotation.z = 0.5; }
  if (e === "sad") { c.brows[0].rotation.z = 0.35; c.brows[1].rotation.z = -0.35; }
  if (e === "surprised") { c.mouth.scale.set(0.55, 1.6, 1); c.brows.forEach((b) => (b.position.y = 0.125)); }
  // bubble
  if (o.bubble) { const k = eob(o.bk ?? 1); c.bubble.visible = k > 0.01; c.bubble.material.map = bubbleTex(o.bubble); c.bubble.material.needsUpdate = true;
    const s = 0.34 * k * (1 + 0.04 * Math.sin(t * 5)); c.bubble.scale.set(s, s, 1); c.bubble.position.y = (p === "sit" || p === "sitphone" ? 1.2 : 1.36) + Math.sin(t * 3) * 0.02; }
  else c.bubble.visible = false;
}

function walkPath(pts, k) { // pts: [[x,z,y]...], k in 0..1 -> {x,z,y,ry}
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

const SEATS = [[-1.67, -1.95], [-1.29, -1.95], [-0.92, -1.95], [-0.55, -1.95], [-1.5, -1.0], [-0.95, -0.95]];
const SEAT_Y = FLOOR + 0.47;
function extraAt(i, t, emo, bubble, bk, extra = {}) {
  const [x, z] = SEATS[i];
  if (i < 4) put(extras[i], { x, z, pose: "sit", seat: SEAT_Y, t, emo, bubble, bk, ...extra });
  else put(extras[i], { x, z, pose: "stand", t, emo, bubble, bk, ...extra });
}
function customerServed(c, t, emo, bubble, bk) {
  if (STATION.kind === "chair") put(c, { x: STATION.custAt[0], z: STATION.custAt[1], ry: STATION.custRy, pose: "sit", seat: STATION.seatTop, t, emo, bubble, bk });
  else put(c, { x: STATION.custAt[0], z: STATION.custAt[1], ry: STATION.custRy, t, emo, bubble, bk });
}
function ownerWork(t, emo, bubble, bk, fast) { put(owner, { x: STATION.ownerAt[0], z: STATION.ownerAt[1], ry: STATION.ownerRy, pose: "work", fast, t, emo, bubble, bk }); }
const ENTRY = [[3.0, 0.4, WALK], [1.75, 0.35, WALK], [1.55, -0.25, FLOOR]];

// ------------------------------------------------------------------ camera
const SHOTS = {
  wide: { p: [0, 2.2, 13.2], l: [0, 1.9, 0], push: 1.4 },
  shop: { p: [0, 1.6, 8.3], l: [0, 1.2, -1.0], push: 0.8 },
  station: { p: [0.9, 1.35, 5.6], l: [0.9, 1.05, -1.3], push: 0.6 },
  couch: { p: [-1.05, 1.25, 4.8], l: [-1.05, 0.95, -1.4], push: 0.6 },
  home: { p: [HOME_X, 1.5, 6.6], l: [HOME_X, 1.2, -0.9], push: 0.7 },
  homeClose: { p: [HOME_X, 1.25, 4.7], l: [HOME_X, 1.0, -1.3], push: 0.5 },
};
function cam(name, k, t, dx = 0, pull = false) {
  const s = SHOTS[name]; const e = eio(k), push = s.push * (pull ? e : 1 - e);
  camera.position.set(s.p[0] + dx + Math.sin(t * 0.9) * 0.03, s.p[1] + Math.sin(t * 1.3) * 0.02 + push * 0.12, s.p[2] + push);
  camera.lookAt(s.l[0] + dx, s.l[1], s.l[2]); camera.updateProjectionMatrix();
  sun.position.set(camera.position.x + 4, 9, 7); sun.target.position.set(s.l[0] + dx, 0, -1); sun.target.updateMatrixWorld();
}

function setNight(on) {
  skyMat.uniforms.top.value.set(on ? 0x0e1a3a : 0x6fb8ec); skyMat.uniforms.bottom.value.set(on ? 0x3a3f74 : 0xeaf5fb);
  scene.fog.color.set(on ? 0x2b3160 : 0xe3f0f8); hemi.intensity = on ? 0.45 : 1.35; hemi.color.set(on ? 0x8fa0ff : 0xe6f3ff);
  sun.intensity = on ? 0.35 : 2.3; sun.color.set(on ? 0x9fb2ff : 0xfff1dc);
  night.moon.visible = on; night.stars.visible = on; clouds.forEach((c) => (c.visible = !on));
  night.lights.forEach((l) => (l.intensity = on ? 0.25 : 0.9));
  (night.lamps || []).forEach((b) => (b.material.emissiveIntensity = on ? 2.5 : 0.3));
}

// ------------------------------------------------------------------ beats
function resetFrame(t) {
  chars.forEach((c) => (c.root.visible = false));
  setNight(false); closedSign.visible = false; phoneBadge.visible = false; msgBubbles.forEach((b) => (b.visible = false));
  sign.position.y = signBase; props.forEach((p) => p.scale.setScalar(1));
  shopPhone.rotation.z = 0; shopPhone.userData.screen.material.emissiveIntensity = 0.4;
  clockHands[0].rotation.z = -t * 0.5; clockHands[1].rotation.z = -t * 0.04 - 1.2;
  clouds.forEach((c) => { const b = c.userData.base; c.position.set(b.x + t * c.userData.sp, b.y, b.z); });
}

const SCENES = {
  open(lt, d, t) {
    cam("wide", lt / d, t);
    sign.position.y = signBase + (1 - eob((lt - 0.15) / 0.6)) * 3;
    props.forEach((p, i) => p.scale.setScalar(Math.max(0.001, eob((lt - 0.45 - i * 0.07) / 0.45))));
    const k = eob((lt - 1.0) / 0.4);
    if (k > 0.01) put(owner, { x: 0.2, z: -0.45, t: lt, pose: "wave", emo: "happy", scale: k });
  },
  first_customer(lt, d, t) {
    cam("shop", lt / d, t);
    const walk = Math.min(1.9, d * 0.55), k = lt / walk;
    if (k < 1) { const p = walkPath([...ENTRY, [STATION.custAt[0] - 0.5, STATION.custAt[1] + 0.5, FLOOR]], k); put(hero, { ...p, pose: "walk", t: lt, emo: "happy" }); put(owner, { x: STATION.ownerAt[0], z: STATION.ownerAt[1], ry: -0.5, t: lt, pose: "wave", emo: "happy" }); }
    else { customerServed(hero, lt, "happy", lt > walk + 0.6 ? "heart" : null, (lt - walk - 0.6) / 0.4); ownerWork(lt, "happy"); }
  },
  rush(lt, d, t) {
    cam("shop", lt / d, t);
    customerServed(hero, lt, "neutral");
    const n = 6, gap = Math.min(0.5, (d - 1.2) / n);
    for (let i = 0; i < n; i++) {
      const t0 = 0.2 + i * gap, k = (lt - t0) / 0.75;
      if (k < 0) continue;
      if (k < 1) { const p = walkPath([[1.75, 0.35, WALK], [1.4, -0.3, FLOOR], [SEATS[i][0], SEATS[i][1] + (i < 4 ? 0.45 : 0), FLOOR]], k); put(extras[i], { ...p, pose: "walk", t: lt + i }); }
      else extraAt(i, lt + i, i > 3 ? "surprised" : "neutral");
    }
    ownerWork(lt, "surprised", lt > 1.2 ? "!" : null, (lt - 1.2) / 0.4, true);
  },
  phone_overload(lt, d, t) {
    cam("station", lt / d, t, 0.25);
    customerServed(hero, lt, "neutral");
    for (let i = 0; i < 4; i++) extraAt(i, lt + i, "neutral");
    const n = Math.min(19, 1 + Math.floor(lt * 3.2));
    phoneBadge.visible = true; phoneBadge.material.map = badgeTex(n); phoneBadge.material.needsUpdate = true;
    shopPhone.rotation.z = Math.sin(lt * 40) * 0.12; shopPhone.userData.screen.material.emissiveIntensity = 1 + Math.sin(lt * 12) * 0.6;
    msgBubbles.forEach((b, i) => { const q = (lt - 0.3 - i * 0.45) / 1.6; if (q < 0 || q > 1) return; b.visible = true;
      const s = 0.26 * eob(q * 3) * (1 - clamp((q - 0.8) / 0.2)); b.scale.set(s, s, 1); b.position.set(1.75 + Math.sin(i * 2.1) * 0.35, FLOOR + 1.5 + q * 0.7, -2.0); });
    ownerWork(lt, lt > 1.0 ? "sad" : "surprised", "?", (lt - 0.6) / 0.4, true);
  },
  after_hours(lt, d, t) {
    setNight(true); cam("wide", lt / d, t);
    closedSign.visible = true; closedSign.scale.set(0.7 * eob(lt / 0.5), 0.35 * eob(lt / 0.5), 1);
    msgBubbles.forEach((b, i) => { const q = (lt - 0.4 - i * 0.4) / 2.2; if (q < 0) return; b.visible = true;
      const s = 0.62 * eob(Math.min(1, q * 4)); b.scale.set(s, s, 1); b.position.set(-1.4 + i * 0.7, FLOOR + 3.6 + (i % 2) * 0.6 + Math.sin(t * 2 + i) * 0.05, 0.4); });
  },
  customers_leave(lt, d, t) {
    cam("shop", lt / d, t);
    customerServed(hero, lt, "neutral"); ownerWork(lt, "sad", lt > d - 1.2 ? "?" : null, (lt - (d - 1.2)) / 0.4);
    const gap = Math.min(0.6, (d - 1.4) / 4);
    for (let i = 0; i < 4; i++) {
      const ta = 0.2 + i * gap, tl = ta + 0.55, k = (lt - tl) / 1.0;
      if (k < 0) extraAt(i, lt + i, lt > ta ? "angry" : "neutral", lt > ta ? "angry" : null, (lt - ta) / 0.3, { emoK: (lt - ta) / 0.3 });
      else if (k < 1) { const p = walkPath([[SEATS[i][0], SEATS[i][1] + 0.45, FLOOR], [1.4, -0.2, FLOOR], [1.8, 0.35, WALK], [3.4, 0.4, WALK]], k); put(extras[i], { ...p, pose: "walk", t: lt + i, emo: "angry", bubble: "angry" }); }
    }
  },
  owner_stressed(lt, d, t) {
    cam("station", lt / d, t, 0.25);
    clockHands[0].rotation.z = -t * 0.5 - lt * 9; clockHands[1].rotation.z = -lt * 0.8 - 1.2;
    customerServed(hero, lt, "neutral", "zzz", (lt - 0.5) / 0.4);
    for (let i = 0; i < 4; i++) extraAt(i, lt + i, "angry", i % 2 ? "zzz" : "angry", (lt - 0.3 - i * 0.2) / 0.3);
    ownerWork(lt, "sad", Math.floor(lt * 1.5) % 2 ? "?" : "!", (lt - 0.2) / 0.3, true);
  },
  fix(lt, d, t) {
    cam("homeClose", lt / d, t);
    put(hero, { x: HOME_X + HOME.couchAt[0], z: HOME.couchAt[1], pose: "sitphone", seat: HOME.seatTop, t: lt, emo: lt > 1.2 ? "happy" : "neutral", bubble: lt > d - 1.0 ? "check" : null, bk: (lt - (d - 1.0)) / 0.35 });
  },
  booked(lt, d, t) {
    const wk = Math.max(1.2, d - 1.3), k = lt / wk;
    if (k < 1) {
      const p = walkPath([[HOME_X, -0.8, FLOOR], [HOME_X, 0.4, WALK], [1.7, 0.4, WALK], [1.45, -0.3, FLOOR]], eio(k) * 0.98 + 0.02 * k);
      put(hero, { ...p, pose: "walk", t: lt, emo: "happy" });
      SHOTS.track = { p: [p.x, 1.35, 5.6], l: [p.x, 1.0, -0.6], push: 0 }; cam("track", 0, t);
      put(owner, { x: 0.3, z: -0.4, ry: 0.4, t: lt, pose: lt > wk - 1.2 ? "wave" : "stand", emo: "happy" });
    } else {
      cam("shop", (lt - wk) / 1.3 * 0.4 + 0.6, t);
      customerServed(hero, lt, "happy", "check", (lt - wk) / 0.35); ownerWork(lt, "happy");
    }
  },
  happy(lt, d, t) {
    cam("shop", lt / d, t);
    customerServed(hero, lt, "happy"); ownerWork(lt, "happy", lt > 0.8 ? "heart" : null, (lt - 0.8) / 0.4);
    for (let i = 0; i < 4; i++) extraAt(i, lt + i, "happy", i % 2 ? "heart" : "check", (lt - 0.35 - i * 0.22) / 0.35, {});
  },
  outro(lt, d, t) {
    cam("wide", lt / d, t, 0, true);
    put(owner, { x: -0.35, z: -0.4, t: lt, pose: "wave", emo: "happy" });
    put(hero, { x: 0.35, z: -0.4, ry: -0.2, t: lt, pose: "wave", emo: "happy" });
  },
};

function renderFrame(t) {
  const S = J.story; let b = S.beats[S.beats.length - 1];
  for (const x of S.beats) if (t >= x.start && t < x.start + x.dur) { b = x; break; }
  resetFrame(t);
  (SCENES[b.scene] || SCENES.happy)(t - b.start, b.dur, t);
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
