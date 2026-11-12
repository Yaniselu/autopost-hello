# Velosyntech Auto-Poster

Postează singur, fără să-ți ții calculatorul pornit, pe **Instagram și pe pagina de Facebook**:
- **Trei stiluri în mix** (setarea „Mix”): din 5 reels pe zi, 3 sunt **povești animate** (personaje 3D cartoon într-un orășel:
  afacerea are o problemă care crește, Velosyntech o rezolvă, final fericit; un cuvânt pe ecran sincronizat cu vocea, bară de
  iconițe care se umple, notificări, chat AI live pe telefon, card de final cu Follow și buclă perfectă la început),
  iar celelalte alternează Cinematic 3D (iPhone + Mac) și Liquid Glass.
- **Temă deschisă** (fundal alb murdar) pentru reels, carusele și stories, cu mult motion design.
- **Fiecare reel arată altfel**: un „regizor” automat alege la fiecare video alte unghiuri de cameră (14 variante), alt fundal
  (bokeh, grilă tech, spot de lumină), alt stil de text (cinetic, subtitrări tip CapCut, mașină de scris), alte tranziții
  (whip, zoom, glitch, flash), alte culori, altă muzică și alte finisaje de iPhone/Mac. Nu repetă combinația videoclipului anterior.
- **Reels cinematice 3D**: mockup-uri tip MacBook (notch, difuzoare, Space Black/Silver) și iPhone Pro (titan natural/negru/alb/deșert/albastru, 3 camere), animate, structura HOOK → PROBLEMA → SOLUȚIA (3 pași) → REZULTATUL → CTA, cu text Liquid Glass, muzică cinematică și efecte sonore
- **Carusel** (1 pe zi în mod implicit): copertă 3D, 5 slide-uri cu idei, slide final cu Follow
- **Stories** (sfat, întrebare, fapt), cu imagini 3D
- **Folosește contul real**: înainte de fiecare postare citește profilul (logo, urmăritori, ultimele postări) și analizează
  reel-urile/caruselurile existente (texte, like-uri, comentarii, imagini) ca să scrie în stilul care merge la voi.
  Logo-ul apare în video, iar la final telefonul arată profilul real cu grid-ul real și un tap pe „Follow” → „Following ✓”.
- **Voce AI în engleză** (voci neurale gratuite, alternate) cu subtitrări sincronizate cuvânt cu cuvânt; muzica scade sub voce.
- **Învață din rezultate**: vizualizări, salvări, distribuiri, like-uri, comentarii pentru fiecare postare → alege mai des
  temele, tipurile de hook și stilul care merg; recomandă orele; raport în panou („Ce funcționează”).
- **Test A/B de hook-uri**: 3 variante (întrebare, cifră, afirmație…) la fiecare reel; alege tipul care performează.
- **Comentariu „DEMO” → DM automat** cu link-ul (Instagram + Facebook) + răspuns public „Just sent you a DM 📩”.
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
