// Minimal GitHub REST client used by the panel (server side only).
const API = "https://api.github.com";

class GitHubError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function repoName() {
  return (process.env.GITHUB_REPO || "").trim().replace(/^https?:\/\/github\.com\//, "").replace(/\.git$/, "");
}

async function gh(path, { method = "GET", body, raw = false, allow404 = false } = {}) {
  const token = (process.env.GITHUB_TOKEN || "").trim();
  const res = await fetch(API + path, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: raw ? "application/vnd.github.raw+json" : "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "velosyntech-panel",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 404 && allow404) return null;
  if (res.status === 204) return {};
  const text = await res.text();
  if (!res.ok) {
    let msg = text;
    try { msg = JSON.parse(text).message || text; } catch {}
    throw new GitHubError(res.status, `GitHub ${res.status}: ${msg}`);
  }
  if (raw) return text;
  return text ? JSON.parse(text) : {};
}

const repo = () => `/repos/${repoName()}`;

async function getRepo() {
  return gh(repo(), { allow404: true });
}

async function readFile(path) {
  const meta = await gh(`${repo()}/contents/${path}`, { allow404: true });
  if (!meta) return null;
  let content;
  if (meta.content && meta.encoding === "base64") {
    content = Buffer.from(meta.content, "base64").toString("utf8");
  } else {
    content = await gh(`${repo()}/contents/${path}`, { raw: true });
  }
  return { sha: meta.sha, content };
}

async function readJson(path, fallback) {
  const f = await readFile(path);
  if (!f) return { sha: null, data: fallback };
  try {
    return { sha: f.sha, data: JSON.parse(f.content) };
  } catch {
    return { sha: f.sha, data: fallback };
  }
}

async function writeFile(path, content, message, sha) {
  if (sha === undefined) {
    const existing = await gh(`${repo()}/contents/${path}`, { allow404: true });
    sha = existing ? existing.sha : null;
  }
  return gh(`${repo()}/contents/${path}`, {
    method: "PUT",
    body: {
      message,
      content: Buffer.from(content, "utf8").toString("base64"),
      ...(sha ? { sha } : {}),
    },
  });
}

async function dispatch(mode) {
  const r = await getRepo();
  return gh(`${repo()}/actions/workflows/post.yml/dispatches`, {
    method: "POST",
    body: { ref: r.default_branch, inputs: { mode } },
  });
}

async function listRuns(n = 8) {
  const data = await gh(`${repo()}/actions/workflows/post.yml/runs?per_page=${n}`, { allow404: true });
  return (data && data.workflow_runs ? data.workflow_runs : []).map((r) => ({
    id: r.id,
    title: r.display_title,
    event: r.event,
    status: r.status,
    conclusion: r.conclusion,
    created_at: r.created_at,
    url: r.html_url,
  }));
}

async function listSecretNames() {
  const data = await gh(`${repo()}/actions/secrets?per_page=100`, { allow404: true });
  return data && data.secrets ? data.secrets.map((s) => s.name) : [];
}

async function setSecret(name, value) {
  const sodium = require("libsodium-wrappers");
  await sodium.ready;
  const key = await gh(`${repo()}/actions/secrets/public-key`);
  const sealed = sodium.crypto_box_seal(
    sodium.from_string(value),
    sodium.from_base64(key.key, sodium.base64_variants.ORIGINAL),
  );
  return gh(`${repo()}/actions/secrets/${name}`, {
    method: "PUT",
    body: { encrypted_value: sodium.to_base64(sealed, sodium.base64_variants.ORIGINAL), key_id: key.key_id },
  });
}

module.exports = {
  GitHubError, repoName, getRepo, readFile, readJson, writeFile, dispatch, listRuns, listSecretNames, setSecret,
};
