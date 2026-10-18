// Archiv-Upload: .ibt-Dateien im Browser vorprüfen (Auto, Klasse, Runden) und nur passende einzeln hochladen.
(() => {
  const root = document.getElementById("archive");
  if (!root) return;
  const markers = JSON.parse(root.dataset.markers);
  const csrf = root.dataset.csrf;
  const maxBytes = Number(root.dataset.maxMb) * 1024 * 1024;
  const MIN_LAPS = 7; // inkl. Outlap und Aufwärmrunde; der Server zählt danach saubere Runden
  const $ = (id) => document.getElementById(id);
  const rowsEl = $("arch-rows"), msg = $("arch-msg"), btn = $("arch-upload");
  let items = [];

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  function carClass(name) {
    const n = (name || "").toLowerCase();
    if (markers.gtp.some((m) => n.includes(m))) return "GTP";
    if (n.includes(markers.gt3) && !markers.gt3_exclude.some((x) => n.includes(x))) return "GT3";
    return null;
  }

  async function inspect(file) {
    const head = new DataView(await file.slice(0, 144).arrayBuffer());
    if (head.byteLength < 144) throw new Error("zu kurz");
    const infoLen = head.getInt32(16, true), infoOff = head.getInt32(20, true);
    const laps = head.getInt32(136, true);
    if (infoOff <= 0 || infoLen <= 0 || infoOff + infoLen > file.size) throw new Error("kein iRacing-Format");
    const yaml = new TextDecoder("latin1").decode(await file.slice(infoOff, infoOff + infoLen).arrayBuffer());
    const idx = (yaml.match(/DriverCarIdx:\s*(\d+)/) || [])[1];
    let car = "?";
    for (const part of yaml.split(/\n\s*- CarIdx:\s*/).slice(1)) {
      if (part.startsWith(idx + "\n") || part.startsWith(idx + "\r")) {
        car = ((part.match(/CarScreenName:\s*(.+)/) || [])[1] || "?").trim();
        break;
      }
    }
    const track = ((yaml.match(/TrackDisplayName:\s*(.+)/) || [])[1] || "?").trim();
    return { car, track, laps, klass: carClass(car) };
  }

  async function pick(fileList) {
    const files = [...fileList].filter((f) => f.name.toLowerCase().endsWith(".ibt"));
    items = [];
    rowsEl.innerHTML = "";
    $("arch-table-wrap").hidden = files.length === 0;
    if (!files.length) {
      msg.textContent = "Keine .ibt-Dateien gefunden.";
      $("arch-actions").hidden = true;
      return;
    }
    msg.textContent = `Prüfe ${files.length} Dateien …`;
    for (const f of files) {
      let info, ok = false, note;
      try {
        info = await inspect(f);
        if (!info.klass) note = "kein GT3/GTP";
        else if (info.laps < MIN_LAPS) note = "zu wenige Runden";
        else if (f.size > maxBytes) note = "zu groß";
        else { ok = true; note = "passt"; }
      } catch (e) {
        info = { car: "?", track: "?", laps: "–", klass: null };
        note = "nicht lesbar";
      }
      items.push({ file: f, ok, info, note });
    }
    items.sort((a, b) => Number(b.ok) - Number(a.ok));
    rowsEl.innerHTML = items.map((it, i) => `<tr id="arch-r${i}" class="${it.ok ? "" : "is-excluded"}">
      <td>${esc(it.file.name)}</td><td>${esc(it.info.car)}</td><td>${it.info.klass || "–"}</td>
      <td>${esc(it.info.track)}</td><td class="num">${it.info.laps}</td>
      <td class="arch-state">${it.ok ? '<span class="state state-fertig">passt</span>' : `<span class="state">${it.note}</span>`}</td></tr>`).join("");
    const good = items.filter((i) => i.ok);
    const mb = good.reduce((s, i) => s + i.file.size, 0) / 1048576;
    msg.innerHTML = `<b>${good.length} von ${files.length}</b> Dateien sind GT3 oder GTP mit genug Runden` +
      (good.length ? ` (${mb.toLocaleString("de-DE", { maximumFractionDigits: 0 })} MB).` : ".");
    $("arch-actions").hidden = good.length === 0;
    btn.disabled = good.length === 0;
  }

  function send(file) {
    return new Promise((resolve) => {
      const fd = new FormData();
      fd.append("test_type", "archiv");
      fd.append("files", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload?art=archiv");
      xhr.setRequestHeader("X-CSRF-Token", csrf);
      xhr.upload.onprogress = (e) => send.onprogress && e.lengthComputable && send.onprogress(e.loaded / e.total);
      xhr.onload = () => {
        let body = {};
        try { body = JSON.parse(xhr.responseText); } catch (e) { /* leer */ }
        const item = (body.items || [])[0];
        resolve({ ok: xhr.status === 200 && item && item.ok, text: (item && item.message) || body.error || `Fehler ${xhr.status}` });
      };
      xhr.onerror = () => resolve({ ok: false, text: "Verbindung abgebrochen" });
      xhr.send(fd);
    });
  }

  btn.addEventListener("click", async () => {
    const good = items.map((it, i) => ({ ...it, i })).filter((it) => it.ok);
    btn.disabled = true;
    $("arch-progress").hidden = false;
    let done = 0, failed = 0;
    for (const it of good) {
      const cell = document.querySelector(`#arch-r${it.i} .arch-state`);
      cell.innerHTML = '<span class="state">lädt …</span>';
      send.onprogress = (p) => {
        $("arch-fill").style.width = `${((done + p) / good.length) * 100}%`;
        $("arch-ptext").textContent = `${done + 1} von ${good.length}`;
      };
      const r = await send(it.file);
      done += 1;
      if (!r.ok) failed += 1;
      cell.innerHTML = r.ok ? `<span class="state state-fertig">${esc(r.text.startsWith("Schon") ? "schon da" : "hochgeladen")}</span>`
                            : `<span class="state state-fehler">${esc(r.text)}</span>`;
      if (!r.ok && /angemeldet|Sitzung|geschlossen|pausiert/.test(r.text)) break;
    }
    $("arch-fill").style.width = "100%";
    $("arch-ptext").textContent = `${done - failed} hochgeladen` + (failed ? `, ${failed} mit Fehler` : "");
    msg.innerHTML = `Fertig. Die Auswertung läuft im Hintergrund – den Stand siehst du unter <a href="/meine-daten">Meine Daten</a> und oben auf dieser Seite.`;
  });

  $("arch-dir").addEventListener("change", (e) => pick(e.target.files));
  $("arch-files").addEventListener("change", (e) => pick(e.target.files));
})();
