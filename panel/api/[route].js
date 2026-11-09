// Single serverless function handling every panel action: /api/<route>
const auth = require("../lib/auth");
const gh = require("../lib/github");
const { buildWorkflow } = require("../lib/workflow");

const GRAPH = "https://graph.facebook.com/v23.0";

const DEFAULT_SETTINGS = {
  paused: false,
  timezone: "Europe/Bucharest",
  times: ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00", "22:00"],
  language: "English",
  hashtags_count: 8,
  brand: {
    name: "Velosyntech",
    handle: "@velosyntech",
    description:
      "Velosyntech is a technology company building modern software, automation and AI solutions for businesses.",
    audience: "founders, developers, tech enthusiasts and small business owners",
    tone: "confident, smart, concise, slightly bold — never cringe, no emojis spam",
    call_to_action: "Follow @velosyntech for more",
  },
  content_pillars: [
    "practical AI tips that save time at work",
    "little-known tech facts that surprise people",
    "automation ideas for small businesses",
    "software development best practices and developer tips",
    "future of technology: short bold predictions",
    "cybersecurity tips everyone should know",
    "productivity tools and workflows for tech teams",
    "myths vs facts about AI and software",
  ],
  video: { style: "cinematic", palette: "random", background: "liquid" },
  carousel_times: ["13:00"],
  story_times: ["09:30", "19:30"],
  stories_per_slot: 1,
  post_to_facebook: true,
  repost_to_story: true,
  comments: { enabled: true, every_hours: 1, max_per_run: 20, instructions: "" },
  instagram_username: "",
  facebook_page: "",
};

const PALETTES = ["random", "aurora", "sunset", "ocean", "neon", "mint"];
const SECRET_NAMES = ["GEMINI_API_KEY", "IG_USER_ID", "IG_ACCESS_TOKEN", "FB_PAGE_ID", "BLOB_READ_WRITE_TOKEN", "PEXELS_API_KEY"];
const KINDS = ["reel", "carousel", "story", "comments"];

class UserError extends Error {}

const str = (v, max) => String(v ?? "").trim().slice(0, max);

function merge(base, extra) {
  const out = { ...base };
  for (const [k, v] of Object.entries(extra || {})) {
    out[k] = v && typeof v === "object" && !Array.isArray(v) ? merge(base[k] || {}, v) : v;
  }
  return out;
}

function validateSettings(input, current) {
  const s = merge(current, {});
  const cleanTimes = (arr, max) => {
    const t = [...new Set((arr || []).map((x) => str(x, 5)))].filter((x) => /^([01]\d|2[0-3]):[0-5]\d$/.test(x));
    if (t.length > max) throw new UserError(`Maxim ${max} ore pe zi pentru un tip de postare.`);
    return t.sort();
  };
  if (input.times !== undefined) s.times = cleanTimes(input.times, 24);
  if (input.carousel_times !== undefined) s.carousel_times = cleanTimes(input.carousel_times, 6);
  if (input.story_times !== undefined) s.story_times = cleanTimes(input.story_times, 12);
  if (input.stories_per_slot !== undefined) s.stories_per_slot = Math.max(1, Math.min(5, parseInt(input.stories_per_slot, 10) || 1));
  if (input.post_to_facebook !== undefined) s.post_to_facebook = !!input.post_to_facebook;
  if (input.repost_to_story !== undefined) s.repost_to_story = !!input.repost_to_story;
  if (input.comments) {
    s.comments = { ...(s.comments || {}) };
    if (input.comments.enabled !== undefined) s.comments.enabled = !!input.comments.enabled;
    if (input.comments.every_hours !== undefined) s.comments.every_hours = Math.max(1, Math.min(12, parseInt(input.comments.every_hours, 10) || 1));
    if (input.comments.max_per_run !== undefined) s.comments.max_per_run = Math.max(1, Math.min(50, parseInt(input.comments.max_per_run, 10) || 20));
    if (input.comments.instructions !== undefined) s.comments.instructions = str(input.comments.instructions, 500);
  }
  if (input.timezone !== undefined) {
    const tz = str(input.timezone, 64);
    try {
      new Intl.DateTimeFormat("en-US", { timeZone: tz });
    } catch {
      throw new UserError(`Fus orar invalid: ${tz}`);
    }
    s.timezone = tz;
  }
  if (input.paused !== undefined) s.paused = !!input.paused;
  if (input.language !== undefined) s.language = str(input.language, 40) || "English";
  if (input.hashtags_count !== undefined)
    s.hashtags_count = Math.max(0, Math.min(30, parseInt(input.hashtags_count, 10) || 0));
  if (input.brand) {
    for (const k of Object.keys(DEFAULT_SETTINGS.brand)) {
      if (input.brand[k] !== undefined) s.brand[k] = str(input.brand[k], 600);
    }
  }
  if (input.content_pillars !== undefined) {
    const p = (input.content_pillars || []).map((x) => str(x, 200)).filter(Boolean).slice(0, 40);
    if (!p.length) throw new UserError("Pune măcar o temă de postare.");
    s.content_pillars = p;
  }
  if (input.video) {
    if (["cinematic", "liquid_glass", "classic"].includes(input.video.style)) s.video.style = input.video.style;
    if (PALETTES.includes(input.video.palette)) s.video.palette = input.video.palette;
    if (["liquid", "pexels", "gradient"].includes(input.video.background)) s.video.background = input.video.background;
  }
  return s;
}

async function loadSettings() {
  const { sha, data } = await gh.readJson("settings.json", null);
  return { sha, settings: merge(DEFAULT_SETTINGS, data || {}), exists: !!data };
}

async function saveSettings(settings, sha, message) {
  await gh.writeFile("settings.json", JSON.stringify(settings, null, 2) + "\n", message, sha);
}

async function saveWorkflow(settings) {
  await gh.writeFile(".github/workflows/post.yml", buildWorkflow(settings), "Update posting schedule");
}

// ---------------------------------------------------------------- Instagram
async function graph(path, params) {
  const url = `${GRAPH}${path}?${new URLSearchParams(params)}`;
  const r = await fetch(url);
  const data = await r.json().catch(() => ({}));
  if (!r.ok || data.error) {
    throw new UserError(`Facebook: ${(data.error && data.error.message) || r.status}`);
  }
  return data;
}

const REQUIRED = ["instagram_basic", "instagram_content_publish", "pages_show_list", "pages_read_engagement"];
const OPTIONAL = {
  instagram_manage_comments: "răspunsuri la comentarii pe Instagram",
  pages_manage_posts: "postare pe Facebook",
  pages_manage_engagement: "răspunsuri la comentarii pe Facebook",
  pages_read_user_content: "citirea comentariilor de pe Facebook",
  business_management: "pagini gestionate prin Business Manager",
};

async function connectInstagram({ appId, appSecret, token, igId }) {
  if (!appId || !appSecret || !token) throw new UserError("Completează App ID, App Secret și token-ul.");
  if (/^IG/.test(token)) {
    throw new UserError(
      "Ai lipit un token „Instagram Login” (începe cu IG…). Pentru postare și pe Facebook trebuie token din " +
        "Graph API Explorer → „Get User Access Token” (începe cu EAA…), cu aplicația ta selectată sus-dreapta.",
    );
  }
  // 1) what is this token? (app, validity, permissions, which pages were granted)
  let dbg;
  try {
    dbg = (await graph("/debug_token", { input_token: token, access_token: `${appId}|${appSecret}` })).data || {};
  } catch (e) {
    throw new UserError(`App ID sau App Secret greșit (${e.message.replace("Facebook: ", "")}).`);
  }
  if (!dbg.is_valid) throw new UserError("Token-ul a expirat sau e invalid. Generează altul în Graph API Explorer și lipește-l imediat.");
  if (String(dbg.app_id) !== String(appId)) {
    throw new UserError(`Token-ul e generat pentru altă aplicație (${dbg.application || dbg.app_id}). În Graph API Explorer, sus-dreapta la „Meta App”, alege aplicația ta.`);
  }
  const scopes = dbg.scopes || [];
  const missing = REQUIRED.filter((p) => !scopes.includes(p));
  if (missing.length) {
    throw new UserError(`Token-ului îi lipsesc permisiunile: ${missing.join(", ")}. În Graph API Explorer → Permissions, adaugă-le și apasă din nou „Generate Access Token” (bifează pagina și contul de Instagram în fereastra Facebook).`);
  }
  const warnings = Object.entries(OPTIONAL).filter(([p]) => !scopes.includes(p)).map(([p, why]) => `${p} (${why})`);

  // 2) long-lived user token -> page tokens that never expire
  const long = await graph("/oauth/access_token", {
    grant_type: "fb_exchange_token", client_id: appId, client_secret: appSecret, fb_exchange_token: token,
  });
  const fields = "name,access_token,instagram_business_account{id,username}";
  const pages = new Map();
  const acc = await graph("/me/accounts", { fields, access_token: long.access_token, limit: "100" });
  for (const p of acc.data || []) pages.set(p.id, p);
  // pages granted through Business Manager don't always show in /me/accounts
  const granted = new Set();
  for (const g of dbg.granular_scopes || []) for (const id of g.target_ids || []) granted.add(String(id));
  for (const id of granted) {
    if (pages.has(id)) continue;
    try { const p = await graph(`/${id}`, { fields, access_token: long.access_token }); if (p.access_token) pages.set(id, p); } catch {}
  }
  if (!pages.size) {
    throw new UserError("Token-ul nu are acces la nicio pagină de Facebook. Când generezi token-ul, în fereastra Facebook apasă „Edit access / Editează accesul” și bifează pagina ta și contul de Instagram.");
  }
  const accounts = [...pages.values()].filter((p) => p.instagram_business_account).map((p) => ({
    page: p.name, pageId: p.id, username: p.instagram_business_account.username,
    id: p.instagram_business_account.id, token: p.access_token,
  }));
  if (!accounts.length) {
    const names = [...pages.values()].map((p) => p.name).join(", ");
    throw new UserError(`Am găsit pagina/paginile: ${names}, dar niciuna nu are un cont Instagram Business/Creator legat. În Instagram → Setări → Cont → „Partajare către alte aplicații”/„Pagină”, leagă contul de pagină (sau din Meta Business Suite → Setări → Conturi Instagram).`);
  }
  const chosen = igId ? accounts.find((a) => a.id === igId) : accounts.length === 1 ? accounts[0] : null;
  if (!chosen) return { choose: accounts.map(({ page, username, id }) => ({ page, username, id })) };

  const check = await graph(`/${chosen.id}`, { fields: "username", access_token: chosen.token });
  await gh.setSecret("IG_USER_ID", chosen.id);
  await gh.setSecret("IG_ACCESS_TOKEN", chosen.token);
  await gh.setSecret("FB_PAGE_ID", chosen.pageId);
  const { sha, settings } = await loadSettings();
  settings.instagram_username = check.username || chosen.username || "";
  settings.facebook_page = chosen.page;
  await saveSettings(settings, sha, "Instagram + Facebook connected");
  return { connected: settings.instagram_username, page: chosen.page, warnings };
}

// ---------------------------------------------------------------- routes
async function state() {
  const missingEnv = ["GITHUB_TOKEN", "GITHUB_REPO"].filter((k) => !(process.env[k] || "").trim());
  if (missingEnv.length) return { missingEnv };
  const repo = await gh.getRepo();
  if (!repo) return { repoMissing: gh.repoName() };
  const [codeFile, wf, settingsRes, history, runs, secrets, comments] = await Promise.all([
    gh.readFile("autoposter/__main__.py"),
    gh.readFile(".github/workflows/post.yml"),
    loadSettings(),
    gh.readJson("data/history.json", []),
    gh.listRuns(10).catch(() => []),
    gh.listSecretNames().catch(() => []),
    gh.readJson("data/comments.json", { log: [] }),
  ]);
  const style = await gh.readJson("data/style_guide.json", null).catch(() => ({ data: null }));
  // media storage key lives on Vercel; copy it to GitHub once so the worker can upload images
  if (process.env.BLOB_READ_WRITE_TOKEN && !secrets.includes("BLOB_READ_WRITE_TOKEN")) {
    try { await gh.setSecret("BLOB_READ_WRITE_TOKEN", process.env.BLOB_READ_WRITE_TOKEN); secrets.push("BLOB_READ_WRITE_TOKEN"); } catch {}
  }
  return {
    repo: gh.repoName(),
    repoUrl: repo.html_url,
    codeUploaded: !!codeFile,
    installed: !!(wf && wf.content.includes("autoposter.due") && settingsRes.exists),
    workflowCurrent: !!(wf && wf.content.includes("--kind")),
    settings: settingsRes.settings,
    history: (Array.isArray(history.data) ? history.data : []).slice(-60).reverse(),
    comments: ((comments.data && comments.data.log) || []).slice(-30).reverse(),
    styleGuide: style && style.data ? { time: style.data.time, guide: style.data.guide } : null,
    runs,
    secrets: SECRET_NAMES.filter((n) => secrets.includes(n)),
  };
}

const routes = {
  async login(req, res) {
    if (!auth.passwordConfigured()) {
      throw new UserError("Parola panoului nu e setată pe Vercel (PANEL_PASSWORD, minim 8 caractere).");
    }
    if (!auth.checkPassword((req.body || {}).password)) {
      await new Promise((r) => setTimeout(r, 900)); // slow down guessing
      res.status(401).json({ error: "Parolă greșită." });
      return null;
    }
    auth.setSession(res);
    return { ok: true };
  },
  async logout(req, res) {
    auth.clearSession(res);
    return { ok: true };
  },
  state,
  async install() {
    const repo = await gh.getRepo();
    if (!repo) throw new UserError(`Repo-ul ${gh.repoName()} nu există sau token-ul nu are acces la el.`);
    if (!(await gh.readFile("autoposter/__main__.py"))) {
      throw new UserError("Nu găsesc codul programului în repo. Urcă întâi fișierele (vezi pașii).");
    }
    const { sha, settings, exists } = await loadSettings();
    if (!exists) await saveSettings(settings, sha, "Create settings");
    await saveWorkflow(settings);
    return { ok: true };
  },
  async settings(req) {
    const { sha, settings } = await loadSettings();
    const next = validateSettings((req.body || {}).settings || {}, settings);
    await saveSettings(next, sha, "Update settings from panel");
    const sched = (x) => JSON.stringify([x.times, x.carousel_times, x.story_times, x.timezone, x.comments]);
    if (sched(next) !== sched(settings)) await saveWorkflow(next);
    return { ok: true, settings: next };
  },
  async pause(req) {
    const { sha, settings } = await loadSettings();
    settings.paused = !!(req.body || {}).paused;
    await saveSettings(settings, sha, settings.paused ? "Pause posting" : "Resume posting");
    return { ok: true, paused: settings.paused };
  },
  async run(req) {
    const b = req.body || {};
    const mode = b.mode === "now" ? "now" : "test";
    const kind = KINDS.includes(b.kind) ? b.kind : "reel";
    await gh.dispatch(mode, kind);
    return { ok: true, mode, kind };
  },
  async gemini(req) {
    const key = str((req.body || {}).key, 200);
    if (!key) throw new UserError("Lipește cheia Gemini.");
    const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models?key=${encodeURIComponent(key)}`);
    if (!r.ok) throw new UserError(`Cheia Gemini nu funcționează (${r.status}). Verifică dacă ai copiat-o complet.`);
    await gh.setSecret("GEMINI_API_KEY", key);
    return { ok: true };
  },
  async pexels(req) {
    const key = str((req.body || {}).key, 200);
    if (!key) throw new UserError("Lipește cheia Pexels.");
    const r = await fetch("https://api.pexels.com/videos/search?query=technology&per_page=1", {
      headers: { Authorization: key },
    });
    if (!r.ok) throw new UserError(`Cheia Pexels nu funcționează (${r.status}).`);
    await gh.setSecret("PEXELS_API_KEY", key);
    return { ok: true };
  },
  async instagram(req) {
    const b = req.body || {};
    return connectInstagram({
      appId: str(b.appId, 64), appSecret: str(b.appSecret, 128), token: str(b.token, 1000), igId: str(b.igId, 64),
    });
  },
};

const PUBLIC = new Set(["login", "logout"]);

module.exports = async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  const route = String((req.query && req.query.route) || "");
  const fn = routes[route];
  if (!fn) return res.status(404).json({ error: "Not found" });
  if (route === "state" ? req.method !== "GET" : req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }
  if (req.method === "POST" && !String(req.headers["content-type"] || "").includes("application/json")) {
    return res.status(415).json({ error: "JSON only" });
  }
  if (!PUBLIC.has(route) && !auth.isLoggedIn(req)) {
    return res.status(401).json({ error: "login", passwordConfigured: auth.passwordConfigured() });
  }
  try {
    const out = await fn(req, res);
    if (out !== null && !res.headersSent) res.status(200).json(out);
  } catch (e) {
    if (e instanceof UserError) return res.status(400).json({ error: e.message });
    if (e instanceof gh.GitHubError) {
      const hint =
        e.status === 401 ? " (token-ul GitHub e greșit sau expirat)" :
        e.status === 403 || e.status === 404 ? " (token-ul GitHub nu are permisiunile repo + workflow)" : "";
      return res.status(502).json({ error: e.message + hint });
    }
    console.error(e);
    return res.status(500).json({ error: "Eroare internă: " + e.message });
  }
};
