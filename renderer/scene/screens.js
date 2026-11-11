// 2D UIs drawn on the device screens (canvas textures). Everything is a pure
// function of (state, t) so frames are deterministic.

const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const ease = (x) => 1 - Math.pow(1 - clamp(x), 3);
const back = (x) => { x = clamp(x); const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };

function rr(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }

function fitText(ctx, text, maxW, size, weight = 700, min = 12) {
  let s = size;
  do { ctx.font = `${weight} ${s}px Inter`; if (ctx.measureText(text).width <= maxW) break; s -= 1; } while (s > min);
  return s;
}

function wrap(ctx, text, maxW) {
  const words = String(text).split(/\s+/); const lines = []; let cur = "";
  for (const w of words) {
    const t = cur ? cur + " " + w : w;
    if (ctx.measureText(t).width > maxW && cur) { lines.push(cur); cur = w; } else cur = t;
  }
  if (cur) lines.push(cur);
  return lines;
}

function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// ------------------------------------------------------------------ laptop
export function drawLaptop(ctx, W, H, st, t) {
  drawLaptopUI(ctx, W, H, st, t);
  displayFrame(ctx, W, H);
}

function drawLaptopUI(ctx, W, H, st, t) {
  const { mode, data, pal } = st;
  ctx.save();
  // wallpaper
  const g = ctx.createLinearGradient(0, 0, W, H);
  g.addColorStop(0, mode === "problem" ? "#1a0b12" : "#0b1022");
  g.addColorStop(1, mode === "problem" ? "#2a0d16" : "#121a3a");
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

  // menu bar
  ctx.fillStyle = "rgba(255,255,255,.06)"; ctx.fillRect(0, 0, W, 30);
  ctx.fillStyle = "rgba(255,255,255,.75)"; ctx.font = "600 13px Inter";
  ctx.fillText(data.app_name || "Workspace", 16, 18);
  ctx.textAlign = "right"; ctx.fillText("9:41", W - 16, 18); ctx.textAlign = "left";

  // window
  const wx = 40, wy = 50, ww = W - 80, wh = H - 90;
  rr(ctx, wx, wy, ww, wh, 16); ctx.fillStyle = "rgba(18,20,34,.92)"; ctx.fill();
  ctx.strokeStyle = "rgba(255,255,255,.08)"; ctx.lineWidth = 1; ctx.stroke();
  // traffic lights
  ["#ff5f57", "#febc2e", "#28c840"].forEach((c, i) => { ctx.beginPath(); ctx.arc(wx + 22 + i * 20, wy + 20, 6, 0, 7); ctx.fillStyle = c; ctx.fill(); });
  // sidebar
  ctx.fillStyle = "rgba(255,255,255,.035)"; ctx.fillRect(wx, wy + 40, 170, wh - 40);
  ["Dashboard", "Tasks", "Inbox", "Reports", "Automations"].forEach((s, i) => {
    const active = (mode === "problem" && i === 1) || (mode !== "problem" && i === 4);
    if (active) { rr(ctx, wx + 10, wy + 54 + i * 36, 150, 28, 8); ctx.fillStyle = hexA(mode === "problem" ? "#ff4d6d" : pal.accent, .18); ctx.fill(); }
    ctx.fillStyle = active ? "#fff" : "rgba(255,255,255,.5)"; ctx.font = `${active ? 700 : 500} 14px Inter`;
    ctx.fillText(s, wx + 24, wy + 73 + i * 36);
  });

  const cx = wx + 200, cw = ww - 230;
  if (mode === "problem") {
    ctx.fillStyle = "#fff"; ctx.font = "800 26px Inter"; ctx.fillText("Tasks", cx, wy + 80);
    ctx.fillStyle = "#ff6b81"; ctx.font = "700 15px Inter";
    const pending = Math.floor(12 + ease(t / 2.5) * 35);
    ctx.fillText(`${pending} overdue`, cx, wy + 106);
    // messy rows
    for (let i = 0; i < 7; i++) {
      const y = wy + 130 + i * 44;
      rr(ctx, cx, y, cw, 36, 8); ctx.fillStyle = "rgba(255,255,255,.04)"; ctx.fill();
      ctx.fillStyle = i % 3 === 0 ? "#ff4d6d" : "rgba(255,255,255,.25)"; ctx.fillRect(cx + 12, y + 14, 8, 8);
      ctx.fillStyle = "rgba(255,255,255,.18)"; rr(ctx, cx + 32, y + 13, 120 + ((i * 53) % 160), 10, 5); ctx.fill();
      ctx.fillStyle = "rgba(255,77,109,.6)"; ctx.font = "700 12px Inter"; ctx.textAlign = "right";
      ctx.fillText(i % 2 ? "LATE" : "BLOCKED", cx + cw - 12, y + 23); ctx.textAlign = "left";
    }
    // alerts popping
    (data.alerts || []).slice(0, 3).forEach((a, i) => {
      const k = back((t - 0.4 - i * 0.55) / 0.45);
      if (k <= 0) return;
      const aw = 330, ah = 62, ax = wx + ww - aw - 20, ay = wy + 52 + i * 74;
      ctx.save(); ctx.globalAlpha = clamp(k); ctx.translate(ax + aw / 2, ay + ah / 2); ctx.scale(0.85 + 0.15 * k, 0.85 + 0.15 * k);
      rr(ctx, -aw / 2, -ah / 2, aw, ah, 14); ctx.fillStyle = "rgba(40,14,22,.96)"; ctx.fill();
      ctx.strokeStyle = "rgba(255,77,109,.7)"; ctx.lineWidth = 2; ctx.stroke();
      ctx.beginPath(); ctx.arc(-aw / 2 + 28, 0, 13, 0, 7); ctx.fillStyle = "#ff4d6d"; ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = "900 16px Inter"; ctx.textAlign = "center"; ctx.fillText("!", -aw / 2 + 28, 6); ctx.textAlign = "left";
      ctx.fillStyle = "#fff"; fitText(ctx, a, aw - 70, 17, 700); ctx.fillText(a, -aw / 2 + 52, 6);
      ctx.restore();
    });
  } else {
    // clean automation view
    ctx.fillStyle = "#fff"; ctx.font = "800 26px Inter"; ctx.fillText(data.app_name || "Automations", cx, wy + 80);
    const steps = data.steps || [];
    const prog = clamp(st.stepProgress || 0);
    ctx.fillStyle = hexA(pal.accent, .9); ctx.font = "700 15px Inter";
    ctx.fillText(prog >= 0.999 ? "All systems running ✓" : "Setting up…", cx, wy + 106);
    // progress bar
    rr(ctx, cx, wy + 120, cw, 10, 5); ctx.fillStyle = "rgba(255,255,255,.08)"; ctx.fill();
    const pg = ctx.createLinearGradient(cx, 0, cx + cw, 0); pg.addColorStop(0, pal.accent); pg.addColorStop(1, pal.accent2);
    rr(ctx, cx, wy + 120, Math.max(10, cw * prog), 10, 5); ctx.fillStyle = pg; ctx.fill();
    steps.forEach((s, i) => {
      const y = wy + 150 + i * 70;
      const k = clamp((st.stepsShown || 0) - i);
      rr(ctx, cx, y, cw, 58, 12); ctx.fillStyle = k > 0 ? hexA(pal.accent, .10 + .06 * k) : "rgba(255,255,255,.035)"; ctx.fill();
      ctx.strokeStyle = k > 0 ? hexA(pal.accent, .5 * k) : "rgba(255,255,255,.06)"; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.beginPath(); ctx.arc(cx + 30, y + 29, 14, 0, 7); ctx.fillStyle = k > 0.5 ? pal.accent : "rgba(255,255,255,.12)"; ctx.fill();
      if (k > 0.5) { ctx.strokeStyle = "#071018"; ctx.lineWidth = 3.5; ctx.beginPath(); ctx.moveTo(cx + 23, y + 29); ctx.lineTo(cx + 28, y + 35); ctx.lineTo(cx + 38, y + 23); ctx.stroke(); }
      ctx.fillStyle = "#fff"; fitText(ctx, s.title, cw - 80, 18, 700); ctx.fillText(s.title, cx + 56, y + 25);
      ctx.fillStyle = "rgba(255,255,255,.55)"; fitText(ctx, s.text, cw - 80, 13, 500); ctx.fillText(s.text, cx + 56, y + 45);
    });
    // rising chart
    const chY = wy + 150 + steps.length * 70 + 12, chH = wh - (chY - wy) - 20;
    if (chH > 60) {
      rr(ctx, cx, chY, cw, chH, 12); ctx.fillStyle = "rgba(255,255,255,.03)"; ctx.fill();
      ctx.beginPath(); const n = 24;
      for (let i = 0; i <= n; i++) {
        const x = cx + 14 + (cw - 28) * i / n;
        const v = 0.15 + 0.7 * (i / n) * (0.6 + 0.4 * prog) + 0.05 * Math.sin(i * 1.7);
        const y = chY + chH - 12 - (chH - 30) * v * clamp(prog * 1.2 + 0.2);
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.strokeStyle = pal.accent; ctx.lineWidth = 3; ctx.stroke();
    }
  }
  ctx.restore();
}

function displayFrame(ctx, W, H) {
  // rounded display corners + camera notch, like modern laptop displays
  ctx.save(); ctx.fillStyle = "#000";
  const r = 22;
  for (const [x, y, sx, sy] of [[0, 0, 1, 1], [W, 0, -1, 1]]) {
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + sx * r, y); ctx.quadraticCurveTo(x, y, x, y + sy * r); ctx.closePath(); ctx.fill();
  }
  rr(ctx, W / 2 - 92, -20, 184, 52, 14); ctx.fill();
  ctx.beginPath(); ctx.arc(W / 2, 14, 5, 0, 7); ctx.fillStyle = "#14161c"; ctx.fill();
  ctx.restore();
}

// ------------------------------------------------------------------ phone
export function drawPhone(ctx, W, H, st, t) {
  const { mode, data, pal, brand } = st;
  ctx.save();
  ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, H);
  ctx.save(); rr(ctx, 3, 3, W - 6, H - 6, 86); ctx.clip();
  // wallpaper: a real image from the account when available, otherwise a gradient
  const pics = (st.img && st.img.grid) || [];
  const wp = pics.length ? pics[(st.wall || 0) % pics.length] : null;
  if (wp) {
    ctx.save();
    ctx.filter = mode === "lock" ? "brightness(.72) saturate(1.15)" : "blur(16px) brightness(.42) saturate(1.3)";
    const sc = Math.max(W / wp.width, H / wp.height), dw = wp.width * sc, dh = wp.height * sc;
    ctx.drawImage(wp, (W - dw) / 2, (H - dh) / 2, dw, dh);
    ctx.restore();
    const shade = ctx.createLinearGradient(0, 0, 0, H);
    shade.addColorStop(0, "rgba(0,0,0,.25)"); shade.addColorStop(0.5, "rgba(0,0,0,0)"); shade.addColorStop(1, "rgba(0,0,0,.45)");
    ctx.fillStyle = shade; ctx.fillRect(0, 0, W, H);
  } else {
    const g = ctx.createLinearGradient(0, 0, W, H);
    if (mode === "lock") { g.addColorStop(0, pal.bg[1]); g.addColorStop(1, pal.bg[0]); }
    else if (mode === "result") { g.addColorStop(0, "#06221c"); g.addColorStop(1, "#0b1530"); }
    else { g.addColorStop(0, "#0d0f1c"); g.addColorStop(1, "#171332"); }
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    // wallpaper blobs
    [[0.2, 0.25, pal.accent], [0.85, 0.6, pal.accent2], [0.3, 0.9, pal.glow[2] || pal.accent]].forEach(([x, y, c], i) => {
      const rg = ctx.createRadialGradient(W * x, H * (y + 0.03 * Math.sin(t + i)), 0, W * x, H * y, W * 0.7);
      rg.addColorStop(0, hexA(c, mode === "lock" ? .55 : .25)); rg.addColorStop(1, hexA(c, 0));
      ctx.fillStyle = rg; ctx.fillRect(0, 0, W, H);
    });
  }
  // status bar + island
  ctx.fillStyle = "#fff"; ctx.font = "700 24px Inter"; ctx.fillText("9:41", 62, 62);
  rr(ctx, W / 2 - 96, 24, 192, 56, 28); ctx.fillStyle = "#000"; ctx.fill();  // Dynamic Island
  ctx.beginPath(); ctx.arc(W / 2 + 62, 52, 10, 0, 7); ctx.fillStyle = "#0b0e1c"; ctx.fill();
  ctx.beginPath(); ctx.arc(W / 2 + 59, 49, 3, 0, 7); ctx.fillStyle = "rgba(90,110,200,.55)"; ctx.fill();

  if (mode === "lock") {
    ctx.textAlign = "center"; ctx.fillStyle = "rgba(255,255,255,.9)"; ctx.font = "600 26px Inter";
    ctx.fillText(data.date_label || "", W / 2, 150);
    ctx.font = "800 120px Inter"; ctx.fillText("9:41", W / 2, 270); ctx.textAlign = "left";
    (data.alerts || []).slice(0, 3).forEach((a, i) => {
      const k = back((t - 0.25 - i * 0.35) / 0.4);
      if (k <= 0) return;
      const y = H - 430 + i * 118;
      ctx.save(); ctx.globalAlpha = clamp(k); ctx.translate(0, (1 - k) * 60);
      rr(ctx, 24, y, W - 48, 104, 26); ctx.fillStyle = "rgba(30,30,40,.72)"; ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,.15)"; ctx.lineWidth = 1; ctx.stroke();
      rr(ctx, 44, y + 22, 58, 58, 14); ctx.fillStyle = "#ff4d6d"; ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = "900 34px Inter"; ctx.textAlign = "center"; ctx.fillText("!", 73, y + 63); ctx.textAlign = "left";
      ctx.font = "700 20px Inter"; ctx.fillStyle = "rgba(255,255,255,.6)"; ctx.fillText((data.app_name || "Work").toUpperCase(), 120, y + 42);
      ctx.fillStyle = "#fff"; fitText(ctx, a, W - 190, 26, 700); ctx.fillText(a, 120, y + 76);
      ctx.restore();
    });
  } else if (mode === "result") {
    const k = back((t - 0.2) / 0.6);
    ctx.save(); ctx.globalAlpha = clamp(k); ctx.translate(W / 2, H / 2 - 40); ctx.scale(0.8 + 0.2 * k, 0.8 + 0.2 * k);
    ctx.beginPath(); ctx.arc(0, -150, 90, 0, 7);
    const cg = ctx.createLinearGradient(-90, -240, 90, -60); cg.addColorStop(0, pal.accent); cg.addColorStop(1, pal.accent2);
    ctx.fillStyle = cg; ctx.fill();
    ctx.strokeStyle = "#06121a"; ctx.lineWidth = 16; ctx.lineCap = "round"; ctx.beginPath();
    ctx.moveTo(-38, -150); ctx.lineTo(-10, -120); ctx.lineTo(42, -178); ctx.stroke();
    ctx.textAlign = "center"; ctx.fillStyle = "#fff";
    ctx.font = "800 40px Inter"; const lines = wrap(ctx, String(data.result || "Done.").replace(/\*/g, ""), W - 120);
    lines.slice(0, 4).forEach((l, i) => ctx.fillText(l, 0, 0 + i * 50));
    ctx.restore(); ctx.textAlign = "left";
  } else if (mode === "steps" || mode === "app") {
    ctx.fillStyle = "#fff"; ctx.font = "800 44px Inter"; ctx.fillText(data.app_name || "Today", 44, 150);
    ctx.fillStyle = hexA(pal.accent, .9); ctx.font = "700 24px Inter";
    const steps = data.steps || [], shown = st.stepsShown ?? steps.length;
    ctx.fillText(shown >= steps.length - 0.01 ? "All done ✓" : `${Math.floor(shown)}/${steps.length} automated`, 44, 192);
    steps.forEach((s, i) => {
      const k = clamp(shown - i), y = 240 + i * 150;
      ctx.save(); ctx.globalAlpha = 0.45 + 0.55 * k;
      rr(ctx, 30, y, W - 60, 128, 30); ctx.fillStyle = k > 0 ? hexA(pal.accent, .12 + .1 * k) : "rgba(255,255,255,.06)"; ctx.fill();
      ctx.strokeStyle = hexA(pal.accent, .5 * k); ctx.lineWidth = 2; ctx.stroke();
      ctx.beginPath(); ctx.arc(88, y + 64, 28, 0, 7); ctx.fillStyle = k > 0.5 ? pal.accent : "rgba(255,255,255,.14)"; ctx.fill();
      if (k > 0.5) { ctx.strokeStyle = "#071018"; ctx.lineWidth = 6; ctx.lineCap = "round"; ctx.beginPath(); ctx.moveTo(74, y + 64); ctx.lineTo(84, y + 75); ctx.lineTo(103, y + 52); ctx.stroke(); }
      ctx.fillStyle = "#fff"; fitText(ctx, s.title, W - 200, 30, 800); ctx.fillText(s.title, 136, y + 56);
      ctx.fillStyle = "rgba(255,255,255,.6)"; fitText(ctx, s.text, W - 200, 21, 500); ctx.fillText(s.text, 136, y + 92);
      ctx.restore();
    });
    // bar chart growing at the bottom
    const by = H - 300;
    for (let i = 0; i < 7; i++) {
      const v = (0.25 + 0.1 * i) * (0.3 + 0.7 * clamp(shown / Math.max(1, steps.length)));
      rr(ctx, 50 + i * 72, by + 200 - 200 * v, 44, 200 * v, 12);
      ctx.fillStyle = i === 6 ? pal.accent : hexA(pal.accent2, .55); ctx.fill();
    }
  } else if (mode === "profile") {
    const acc = st.account || {}, img = st.img || {};
    const k = ease(t / 0.6);
    ctx.globalAlpha = k;
    // avatar (real logo when available) with gradient story ring
    const ax = W / 2, ay = 280, ar = 112;
    const ag = ctx.createLinearGradient(ax - ar, ay - ar, ax + ar, ay + ar); ag.addColorStop(0, pal.accent); ag.addColorStop(1, pal.accent2);
    ctx.beginPath(); ctx.arc(ax, ay, ar + 12, 0, 7); ctx.fillStyle = ag; ctx.fill();
    ctx.beginPath(); ctx.arc(ax, ay, ar + 5, 0, 7); ctx.fillStyle = "#0b0b12"; ctx.fill();
    ctx.save(); ctx.beginPath(); ctx.arc(ax, ay, ar, 0, 7); ctx.clip();
    if (img.avatar) ctx.drawImage(img.avatar, ax - ar, ay - ar, ar * 2, ar * 2);
    else { ctx.fillStyle = ag; ctx.fillRect(ax - ar, ay - ar, ar * 2, ar * 2); ctx.fillStyle = "#0b0a1f"; ctx.font = "900 120px Inter"; ctx.textAlign = "center"; ctx.fillText((brand.name || "V")[0].toUpperCase(), ax, ay + 43); }
    ctx.restore();
    ctx.textAlign = "center";
    ctx.fillStyle = "#fff"; fitText(ctx, acc.name || brand.name, W - 80, 42, 800); ctx.fillText(acc.name || brand.name, W / 2, 460);
    ctx.fillStyle = "rgba(255,255,255,.6)"; ctx.font = "600 26px Inter"; ctx.fillText(acc.username ? "@" + acc.username : brand.handle, W / 2, 500);
    // stats
    const fmt = (n) => n == null ? "—" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e4 ? Math.round(n / 1e3) + "K" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K" : String(n);
    [[acc.posts, "posts"], [acc.followers, "followers"]].forEach(([n, l], i) => {
      const x = W / 2 + (i ? 110 : -110);
      ctx.fillStyle = "#fff"; ctx.font = "800 34px Inter"; ctx.fillText(fmt(n), x, 560);
      ctx.fillStyle = "rgba(255,255,255,.55)"; ctx.font = "500 21px Inter"; ctx.fillText(l, x, 590);
    });
    // follow button: pulses, then gets "tapped" and turns into Following
    const tapped = t > 1.75;
    const pulse = tapped ? 1 : 1 + 0.04 * Math.sin(t * 7);
    const press = t > 1.6 && t < 1.85 ? 0.92 : 1;
    ctx.save(); ctx.translate(W / 2, 665); ctx.scale(pulse * press, pulse * press);
    rr(ctx, -175, -40, 350, 80, 40); ctx.fillStyle = tapped ? "rgba(255,255,255,.16)" : "#0095f6"; ctx.fill();
    ctx.fillStyle = "#fff"; ctx.font = "800 32px Inter"; ctx.fillText(tapped ? "Following ✓" : "Follow", 0, 12); ctx.restore();
    if (t > 1.55 && t < 2.3) { // tap ripple
      const q = (t - 1.55) / 0.75;
      ctx.beginPath(); ctx.arc(W / 2 + 60, 670, 20 + 90 * q, 0, 7); ctx.strokeStyle = `rgba(255,255,255,${0.7 * (1 - q)})`; ctx.lineWidth = 6; ctx.stroke();
      ctx.beginPath(); ctx.arc(W / 2 + 60, 670, 26, 0, 7); ctx.fillStyle = `rgba(255,255,255,${0.55 * (1 - q)})`; ctx.fill();
    }
    // grid: the account's real latest posts
    const cw = (W - 48) / 3;
    for (let i = 0; i < 9; i++) {
      const x = 24 + (i % 3) * cw, y = 750 + Math.floor(i / 3) * (cw + 4);
      const g = img.grid && img.grid[i];
      if (g) {
        const s0 = Math.max(cw / g.width, cw / g.height), sw = cw / s0, sh = cw / s0;
        ctx.drawImage(g, (g.width - sw) / 2, (g.height - sh) / 2, sw, sh, x + 2, y + 2, cw - 4, cw - 4);
      } else {
        const tg = ctx.createLinearGradient(x, y, x + cw, y + cw);
        tg.addColorStop(0, hexA(i % 2 ? pal.accent : pal.accent2, .5)); tg.addColorStop(1, "rgba(255,255,255,.05)");
        ctx.fillStyle = tg; ctx.fillRect(x + 2, y + 2, cw - 4, cw - 4);
      }
    }
    ctx.textAlign = "left"; ctx.globalAlpha = 1;
  }
  ctx.restore();
  ctx.restore();
}
