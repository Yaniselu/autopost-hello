// Drives the 3D scene in headless Chromium and records it.
// usage: node render.mjs job.json outDir
//   job.mode = "reel"  -> outDir/frames/00000.jpg… (3D only) + outDir/timeline.json
//   job.mode = "stills"-> outDir/<name>.jpg for every job.stills[i]
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".otf": "font/otf", ".ttf": "font/ttf", ".json": "application/json" };

function resolveFont(name) {
  for (const p of [path.join(ROOT, "assets/fonts", name), path.join("/usr/share/fonts/opentype/inter", name)]) if (fs.existsSync(p)) return p;
  return null;
}

function localFile(urlPath) {
  if (urlPath === "/" || urlPath === "/index.html") return path.join(HERE, "scene/index.html");
  if (urlPath.startsWith("/scene/")) return path.join(HERE, urlPath);
  if (urlPath.startsWith("/three/")) return path.join(HERE, "node_modules", urlPath);
  if (urlPath.startsWith("/fonts/")) return resolveFont(path.basename(urlPath));
  return null;
}

async function openPage(browser, job) {
  const page = await browser.newPage({ viewport: { width: job.width, height: job.height }, deviceScaleFactor: 1 });
  page.on("pageerror", (e) => console.error("[page error]", e.message));
  page.on("console", (m) => { if (m.type() === "error") console.error("[page]", m.text()); });
  await page.route("http://render.local/**", async (route) => {
    const p = localFile(new URL(route.request().url()).pathname);
    if (!p || !fs.existsSync(p)) return route.fulfill({ status: 404, body: "not found" });
    return route.fulfill({ status: 200, contentType: TYPES[path.extname(p)] || "application/octet-stream", body: fs.readFileSync(p) });
  });
  await page.goto("http://render.local/");
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 60000 });
  const tl = await page.evaluate((j) => window.setup(j), job);
  return { page, tl };
}

const LAUNCH = {
  executablePath: process.env.CHROMIUM_PATH || undefined,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--disable-gpu-vsync",
    "--disable-accelerated-2d-canvas", "--font-render-hinting=none"],
};

// each worker gets its own browser (= its own GPU process), so they really run in parallel
async function renderRange(job, from, to, dir, tag) {
  const browser = await chromium.launch(LAUNCH);
  const { page } = await openPage(browser, job);
  const t0 = Date.now();
  for (let f = from; f < to; f++) {
    const url = await page.evaluate((t) => window.renderFrame(t), f / job.fps);
    fs.writeFileSync(path.join(dir, String(f).padStart(5, "0") + ".jpg"), Buffer.from(url.slice(url.indexOf(",") + 1), "base64"));
    if ((f - from) % 90 === 0) console.log(`[render ${tag}] ${f - from}/${to - from} frames (${((Date.now() - t0) / (f - from + 1)).toFixed(0)} ms/frame)`);
  }
  await browser.close();
}

async function main() {
  const [jobFile, outDir] = process.argv.slice(2);
  const job = JSON.parse(fs.readFileSync(jobFile, "utf8"));
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch(LAUNCH);
  try {
    if (job.mode === "reel") {
      const { page, tl } = await openPage(browser, job);
      await page.close();
      fs.writeFileSync(path.join(outDir, "timeline.json"), JSON.stringify(tl, null, 1));
      const frames = Math.ceil(tl.total * job.fps);
      if (job.only_times) { // quick previews: just a few moments
        const dir = path.join(outDir, "frames"); fs.mkdirSync(dir, { recursive: true });
        const { page } = await openPage(browser, job);
        for (const tt of job.only_times) {
          const f = Math.min(frames - 1, Math.round(tt * job.fps));
          const url = await page.evaluate((x) => window.renderFrame(x), f / job.fps);
          fs.writeFileSync(path.join(dir, String(f).padStart(5, "0") + ".jpg"), Buffer.from(url.slice(url.indexOf(",") + 1), "base64"));
        }
        await page.close();
        return;
      }
      const workers = Math.max(1, Math.min(job.workers || os.cpus().length, 6));
      const dir = path.join(outDir, "frames"); fs.mkdirSync(dir, { recursive: true });
      const per = Math.ceil(frames / workers);
      console.log(`[render] ${frames} frames, ${workers} workers`);
      await Promise.all(Array.from({ length: workers }, (_, k) => {
        const from = k * per, to = Math.min(frames, (k + 1) * per);
        return from < to ? renderRange(job, from, to, dir, k) : null;
      }));
      console.log("[render] 3D frames done");
    } else {
      const { page } = await openPage(browser, job);
      for (const s of job.stills) {
        await page.evaluate((spec) => window.renderStill(spec), s);
        await page.evaluate(() => document.fonts.ready);
        await page.screenshot({ type: "jpeg", quality: 95, path: path.join(outDir, `${s.name}.jpg`) });
        console.log(`[render] ${s.name}.jpg`);
      }
    }
  } finally {
    await browser.close();
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
