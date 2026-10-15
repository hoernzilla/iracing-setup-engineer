// Upload mit Drag & Drop, Fortschrittsanzeige und automatischer Aktualisierung des Auswertungsstands.
(() => {
  const form = document.getElementById("upload-form");
  if (!form) return;
  const input = document.getElementById("file-input");
  const zone = document.getElementById("dropzone");
  const picked = document.getElementById("picked");
  const btn = document.getElementById("upload-btn");
  const msg = document.getElementById("form-msg");
  const progress = document.getElementById("progress");
  const fill = document.getElementById("progress-fill");
  const ptext = document.getElementById("progress-text");
  const csrf = form.querySelector('input[name="csrf"]').value;
  let files = [];

  const mb = (n) => (n / 1024 / 1024).toLocaleString("de-DE", { maximumFractionDigits: 1 }) + " MB";
  const testType = () => form.querySelector('input[name="test_type"]:checked').value;

  function setMessage(html, cls = "") {
    msg.className = "form-msg " + cls;
    msg.innerHTML = html;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function render() {
    picked.innerHTML = files
      .map((f) => `<li><span>${escapeHtml(f.name)}</span><span>${mb(f.size)}</span></li>`)
      .join("");
    const garage = testType() === "garage";
    let problem = "";
    if (files.some((f) => !f.name.toLowerCase().endsWith(".ibt"))) problem = "Nur .ibt-Dateien aus Dokumente\\iRacing\\telemetry.";
    else if (garage && files.length && files.length !== 2) problem = "Für einen Garage-Test bitte genau zwei Dateien wählen: vorher und nachher.";
    btn.disabled = !files.length || !!problem;
    btn.textContent = files.length > 1 ? `${files.length} Dateien hochladen` : "Hochladen";
    setMessage(problem ? escapeHtml(problem) : "", problem ? "error" : "");
  }

  function addFiles(list) {
    const incoming = Array.from(list);
    const known = new Set(files.map((f) => f.name + f.size));
    files = files.concat(incoming.filter((f) => !known.has(f.name + f.size)));
    render();
  }

  input.addEventListener("change", () => { files = []; addFiles(input.files); });
  form.querySelectorAll('input[name="test_type"]').forEach((r) => r.addEventListener("change", render));

  ["dragenter", "dragover"].forEach((ev) =>
    zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("drag"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("drag"); })
  );
  zone.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!files.length) return;
    // Vorab prüfen, ob die Anmeldung noch gilt – erspart einen langen Upload ins Leere.
    try {
      const check = await fetch("/api/status", { headers: { Accept: "application/json" } });
      if (check.status === 401) {
        const body = await check.json().catch(() => ({}));
        setMessage(escapeHtml(body.error || "Bitte neu anmelden."), "error");
        return;
      }
    } catch (_) { /* Server kurz nicht erreichbar – Upload trotzdem versuchen */ }
    const data = new FormData();
    files.forEach((f) => data.append("files", f, f.name));
    data.append("test_type", testType());
    data.append("description", form.description.value);
    data.append("feeling", form.feeling.value);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.setRequestHeader("X-CSRF-Token", csrf);
    btn.disabled = true;
    progress.hidden = false;
    fill.style.width = "0%";
    setMessage("");
    xhr.upload.addEventListener("progress", (ev) => {
      if (!ev.lengthComputable) return;
      const pct = Math.round((ev.loaded / ev.total) * 100);
      fill.style.width = pct + "%";
      ptext.textContent = pct < 100 ? `${pct} % – ${mb(ev.loaded)} von ${mb(ev.total)}` : "Wird geprüft …";
    });
    xhr.addEventListener("load", () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch (_) {}
      progress.hidden = true;
      if (body.error) {
        setMessage(escapeHtml(body.error), "error");
        btn.disabled = false;
        return;
      }
      const items = body.items || [];
      const list = items
        .map((i) => `<li class="${i.ok ? "good" : "bad"}">${escapeHtml(i.filename)}: ${escapeHtml(i.message)}</li>`)
        .join("");
      setMessage(`<ul>${list}</ul>`);
      if (items.some((i) => i.ok)) setTimeout(() => location.reload(), 1200);
      else btn.disabled = false;
    });
    xhr.addEventListener("error", () => {
      progress.hidden = true;
      setMessage("Verbindung abgebrochen. Bitte die Seite neu laden und erneut versuchen.", "error");
      btn.disabled = false;
    });
    xhr.send(data);
  });

  // Laufende Auswertungen beobachten und die Seite aktualisieren, sobald sie fertig sind.
  const pending = () => Array.from(document.querySelectorAll('tr[data-status="wartet"], tr[data-status="läuft"]'));
  if (pending().length) {
    const timer = setInterval(async () => {
      try {
        const r = await fetch("/api/status", { headers: { Accept: "application/json" } });
        const { uploads = [] } = await r.json();
        const open = new Set(pending().map((tr) => tr.dataset.id));
        const changed = uploads.some((u) => open.has(u.id) && u.status !== "wartet" && u.status !== "läuft");
        if (changed) { clearInterval(timer); location.reload(); }
      } catch (_) { /* nächster Versuch */ }
    }, 2500);
  }
})();
