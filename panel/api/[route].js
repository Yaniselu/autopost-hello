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
  video: { style: "liquid_glass", palette: "random", background: "liquid" },
  instagram_username: "",
};

const PALETTES = ["random", "aurora", "sunset", "ocean", "neon", "mint"];
const SECRET_NAMES = ["GEMINI_API_KEY", "IG_USER_ID", "IG_ACCESS_TOKEN", "PEXELS_API_KEY"];

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
  if (input.times !== undefined) {
    const times = [...new Set((input.times || []).map((t) => str(t, 5)))].filter((t) =>
      /^([01]\d|2[0-3]):[0-5]\d$/.test(t),
    );
    if (times.length > 24) throw new UserError("Maxim 24 de postări pe zi.");
    s.times = times.sort();
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
    if (["liquid_glass", "classic"].includes(input.video.style)) s.video.style = input.video.style;
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

async function connectInstagram({ appId, appSecret, token, igId }) {
  if (!appId || !appSecret || !token) throw new UserError("Completează App ID, App Secret și token-ul.");
  const long = await graph("/oauth/access_token", {
    grant_type: "fb_exchange_token", client_id: appId, client_secret: appSecret, fb_exchange_token: token,
  });
  const pages = await graph("/me/accounts", {
    fields: "name,access_token,instagram_business_account{id,username}",
    access_token: long.access_token, limit: "100",
  });
  const accounts = (pages.data || [])
    .filter((p) => p.instagram_business_account)
    .map((p) => ({
      page: p.name, username: p.instagram_business_account.username,
      id: p.instagram_business_account.id, token: p.access_token,
    }));
  if (!accounts.length) {
    throw new UserError(
      "N-am găsit niciun cont Instagram Business/Creator legat de paginile tale de Facebook. " +
        "Verifică legătura Instagram ↔ pagină și permisiunile token-ului.",
    );
  }
  const chosen = igId ? accounts.find((a) => a.id === igId) : accounts.length === 1 ? accounts[0] : null;
  if (!chosen) {
    return { choose: accounts.map(({ page, username, id }) => ({ page, username, id })) };
  }
  const check = await graph(`/${chosen.id}`, { fields: "username", access_token: chosen.token });
  await gh.setSecret("IG_USER_ID", chosen.id);
  await gh.setSecret("IG_ACCESS_TOKEN", chosen.token);
  const { sha, settings } = await loadSettings();
  settings.instagram_username = check.username || chosen.username || "";
  await saveSettings(settings, sha, "Instagram account connected");
  return { connected: settings.instagram_username };
}

// ---------------------------------------------------------------- routes
async function state() {
  const missingEnv = ["GITHUB_TOKEN", "GITHUB_REPO"].filter((k) => !(process.env[k] || "").trim());
  if (missingEnv.length) return { missingEnv };
  const repo = await gh.getRepo();
  if (!repo) return { repoMissing: gh.repoName() };
  const [codeFile, wf, settingsRes, history, runs, secrets] = await Promise.all([
    gh.readFile("autoposter/__main__.py"),
    gh.readFile(".github/workflows/post.yml"),
    loadSettings(),
    gh.readJson("data/history.json", []),
    gh.listRuns(8).catch(() => []),
    gh.listSecretNames().catch(() => []),
  ]);
  return {
    repo: gh.repoName(),
    repoUrl: repo.html_url,
    codeUploaded: !!codeFile,
    installed: !!(wf && wf.content.includes("autoposter.due") && settingsRes.exists),
    settings: settingsRes.settings,
    history: (Array.isArray(history.data) ? history.data : []).slice(-60).reverse(),
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
    if (JSON.stringify(next.times) !== JSON.stringify(settings.times) || next.timezone !== settings.timezone) {
      await saveWorkflow(next);
    }
    return { ok: true, settings: next };
  },
  async pause(req) {
    const { sha, settings } = await loadSettings();
    settings.paused = !!(req.body || {}).paused;
    await saveSettings(settings, sha, settings.paused ? "Pause posting" : "Resume posting");
    return { ok: true, paused: settings.paused };
  },
  async run(req) {
    const mode = (req.body || {}).mode === "now" ? "now" : "test";
    await gh.dispatch(mode);
    return { ok: true, mode };
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
