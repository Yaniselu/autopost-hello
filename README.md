# Velosyntech Auto-Poster

Postează singur, fără să-ți ții calculatorul pornit, pe **Instagram și pe pagina de Facebook**:
- **Reels cinematice 3D**: laptop și telefon animate, structura HOOK → PROBLEMA → SOLUȚIA (3 pași) → REZULTATUL → CTA, cu text Liquid Glass, muzică cinematică și efecte sonore
- **Carusel** (1 pe zi în mod implicit): copertă 3D, 5 slide-uri cu idei, slide final cu Follow
- **Stories** (sfat, întrebare, fapt), cu imagini 3D
- **Răspunsuri automate la comentarii**, pe Instagram și Facebook
- Textele le scrie Google Gemini (gratuit). Modelul se alege automat, iar răspunsurile la comentarii folosesc modelul mai ieftin.

**Panoul** (cu parolă): https://autopost-hello.vercel.app

```
Panou (Vercel)  ──▶  GitHub Actions (face conținutul + postează)  ──▶  Instagram + Facebook
                         └── imaginile trec prin Vercel Blob (link public temporar, șters după postare)
```

## Configurare (în panou)
1. **Instalează / actualizează** programarea, cu un singur buton.
2. **Cheia Gemini** (gratuită): https://aistudio.google.com/apikey
3. **Conectează Instagram + Facebook**:
   - contul de Instagram trebuie să fie **Business/Creator** și legat de **pagina de Facebook**;
   - din aplicația Meta (developers.facebook.com → aplicația ta → App settings → Basic) copiezi **App ID** și **App Secret**;
   - în **Graph API Explorer** alegi aplicația ta sus-dreapta, adaugi permisiunile afișate în panou și apeși
     **Generate Access Token**;
   - în fereastra Facebook apasă **Editează accesul** și **bifează pagina și contul de Instagram**;
   - lipește token-ul (începe cu `EAA…`). Panoul spune exact ce lipsește dacă ceva nu e în regulă.
4. **Previzualizare**: alegi tipul (Reel, Carusel, Story) și apeși. Rezultatul apare direct în Istoric, în ~5–8 minute.

## Bine de știut
- **Minute GitHub**: un Reel cinematic durează ~6–10 minute de rulare. Repo-urile **private** au 2000 de minute
  gratuite pe lună, adică aproximativ 3–4 reels pe zi plus carusel, stories și comentarii.
  Pentru 8 reels pe zi, fă repo-ul **public** (Settings → General → Change visibility): minutele devin nelimitate,
  iar cheile rămân secrete în GitHub Secrets.
- **Modelele 3D** (laptop + telefon) sunt construite din cod, în stilul MacBook/iPhone, dar fără logo Apple.
  Așa nu ai probleme de licență sau de marcă înregistrată pe un cont de business.
- Muzica e compusă automat, fără copyright. Poți pune melodiile tale în `assets/music/`.
- Dacă o postare pe Facebook eșuează, cea de pe Instagram rămâne. Eroarea apare separat în Istoric.

## Structura
```
autoposter/   Python: texte (llm.py, content.py), reel cinematic (cinematic.py), carusel/stories (stills.py),
              publicare IG+FB (publish.py), comentarii (comments.py), programare (due.py)
renderer/     scena 3D (three.js în Chromium headless)
panel/        panoul web cu parolă (Vercel)
settings.json setările (le modifică panoul)
data/         istoric postări, comentarii la care s-a răspuns
```
