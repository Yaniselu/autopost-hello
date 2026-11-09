# Velosyntech Auto-Poster — în cloud, cu panou cu parolă

Postează singur Reels în stil **Liquid Glass** pe @velosyntech, **fără să-ți ții calculatorul pornit**.

```
 Tu (telefon/PC) ──parolă──▶  PANOU pe Vercel  ──▶  GitHub (face video-ul + postează)  ──▶  Instagram
```
- **Panoul** (pe Vercel, gratuit) e un site al tău cu parolă. Din el:
  postezi acum, pui pe pauză, vezi istoricul, schimbi orele, temele, culorile și cheile.
- **GitHub Actions** (gratuit) face video-ul, scrie caption-ul cu AI și îl postează la orele setate.
- Totul e gratuit: Vercel Hobby, GitHub Free și Gemini free tier.

---

## Instalare

**Deja făcut:** codul e în repo-ul `Yaniselu/autopost-hello`, iar panoul e online pe
**https://autopost-hello.vercel.app**, cu parolă (`PANEL_PASSWORD` în Vercel).

### Mai trebuie: cheia GitHub pentru panou (2 minute)
1. Deschide https://github.com/settings/tokens/new?scopes=repo,workflow&description=autopost-panel
   (Expiration: **No expiration**; `repo` și `workflow` sunt deja bifate) → **Generate token** → copiază `ghp_…`.
2. Deschide https://vercel.com/yaniselus-projects/autopost-hello/settings/environment-variables
   → **Add** → Key: `GITHUB_TOKEN`, Value: token-ul → Save.
3. Vercel → **Deployments** → la ultimul deploy: **⋯ → Redeploy**.

### 4. În panou (intri cu parola)
Panoul îți arată ce mai e de făcut, bifă cu bifă:
1. **Instalează**: un singur buton.
2. **Cheia Gemini**: gratuită, de pe https://aistudio.google.com/apikey.
3. **Conectează Instagram**:
   - contul de Instagram trebuie să fie **Business/Creator** și legat de o **pagină de Facebook**;
   - fă o aplicație pe https://developers.facebook.com/apps (Create App → Business / use case Instagram);
   - din App settings → Basic copiezi **App ID** și **App Secret**;
   - din **Graph API Explorer** iei un token cu permisiunile scrise în panou;
   - panoul îl transformă singur într-un token **care nu expiră**.
4. **🎬 Video de test**: după ~5 minute îl poți descărca și vedea.

Gata. De acum postează singur la orele din panou, chiar dacă PC-ul e închis.

---

## Bine de știut
- **Orele** sunt ora României (fusul se poate schimba din panou). GitHub pornește uneori cu 5–20 de minute întârziere. E normal.
- **Cheile** se salvează criptat în GitHub Secrets. Nici panoul nu le mai poate citi după aceea.
- **Parola panoului** o schimbi din Vercel → Settings → Environment Variables → `PANEL_PASSWORD` → Redeploy.
  După schimbare ești delogat de peste tot.
- **Minute gratuite**: un repo privat are 2000 de minute pe lună pe GitHub. 8 postări pe zi folosesc ~1500.
  Dacă pui mai multe, fă repo-ul public (cheile rămân secrete) sau postează mai rar.
- **Sfat**: 8 Reels pe zi e mult pentru Instagram. 3–4 pe zi dau de obicei reach mai bun.
- Dacă o postare dă eroare, apare cu roșu în **Istoric** și primești email de la GitHub.

## Varianta pe calculator (opțional)
Dacă vrei totuși să ruleze de pe PC: dublu-click pe `START-Windows.bat` (sau `start-mac-linux.command`).
Te întreabă cheile și postează cât timp e deschis.

## Structura
```
autoposter/   programul (AI text, video Liquid Glass, muzică, postare)
panel/        panoul web cu parolă (se pune pe Vercel)
settings.json setările (le modifică panoul)
data/         istoricul postărilor
.github/      programarea automată (o generează panoul)
```
