// Password login with an HMAC-signed, HttpOnly session cookie.
const crypto = require("crypto");

const COOKIE = "vs_session";
const MAX_AGE = 60 * 60 * 24 * 30; // 30 days

function password() {
  return (process.env.PANEL_PASSWORD || "").trim();
}

function key() {
  return crypto
    .createHash("sha256")
    .update(`velosyntech-panel|${password()}|${process.env.SESSION_SECRET || process.env.GITHUB_TOKEN || ""}`)
    .digest();
}

function sign(value) {
  return crypto.createHmac("sha256", key()).update(value).digest("base64url");
}

function safeEqual(a, b) {
  const ha = crypto.createHash("sha256").update(String(a)).digest();
  const hb = crypto.createHash("sha256").update(String(b)).digest();
  return crypto.timingSafeEqual(ha, hb);
}

function passwordConfigured() {
  return password().length >= 8;
}

function checkPassword(input) {
  return passwordConfigured() && safeEqual(input || "", password());
}

function parseCookies(req) {
  const out = {};
  for (const part of (req.headers.cookie || "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
  }
  return out;
}

function isLoggedIn(req) {
  if (!passwordConfigured()) return false;
  const raw = parseCookies(req)[COOKIE];
  if (!raw) return false;
  const [exp, sig] = raw.split(".");
  if (!exp || !sig || Number(exp) < Date.now() / 1000) return false;
  return safeEqual(sig, sign(exp));
}

function setSession(res) {
  const exp = String(Math.floor(Date.now() / 1000) + MAX_AGE);
  res.setHeader(
    "Set-Cookie",
    `${COOKIE}=${exp}.${sign(exp)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${MAX_AGE}`,
  );
}

function clearSession(res) {
  res.setHeader("Set-Cookie", `${COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`);
}

module.exports = { passwordConfigured, checkPassword, isLoggedIn, setSession, clearSession };
