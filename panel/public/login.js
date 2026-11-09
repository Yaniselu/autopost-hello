(function () {
  var f = document.getElementById("f"), pw = document.getElementById("pw"), msg = document.getElementById("msg"), go = document.getElementById("go");
  fetch("/api/session", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.loggedIn) location.replace("/app");
    else if (d.passwordConfigured === false) { msg.textContent = "Parola panoului nu e setată (PANEL_PASSWORD în Vercel)."; msg.className = "err"; }
  }).catch(function () {});
  f.addEventListener("submit", function (e) {
    e.preventDefault(); go.disabled = true;
    fetch("/api/login", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pw.value }) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (x.ok) { location.replace("/app"); return; }
        msg.textContent = (x.d && x.d.error) || "Eroare"; msg.className = "err"; pw.value = ""; pw.focus();
      })
      .catch(function () { msg.textContent = "Nu mă pot conecta la server."; msg.className = "err"; })
      .then(function () { go.disabled = false; });
  });
})();
