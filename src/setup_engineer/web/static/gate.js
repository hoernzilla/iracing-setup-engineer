// Leitfaden-Bestätigung: Häkchen erst freigeben, wenn bis zum Ende gelesen wurde.
// Robust gegen Zoom/Rundung: Freigabe, sobald das Ende der Box (mit Toleranz) erreicht ist.
(() => {
  const box = document.getElementById("gate-scroll");
  const check = document.getElementById("gate-check");
  const hint = document.getElementById("gate-hint");
  if (!box || !check) return;
  let open = false;
  const unlock = () => {
    if (open) return;
    open = true;
    check.disabled = false;
    if (hint) hint.textContent = "Danke fürs Lesen – jetzt das Häkchen setzen.";
  };
  const atEnd = () => box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
  const test = () => { if (atEnd()) unlock(); };
  check.disabled = true;
  box.addEventListener("scroll", test, { passive: true });
  window.addEventListener("resize", test);
  test(); // Box ohne Scrollbalken (großer Bildschirm) -> sofort frei
  // Klick auf das gesperrte Häkchen: erklären statt nichts tun
  check.closest("label")?.addEventListener("click", () => {
    if (!open && hint) {
      hint.textContent = "Bitte zuerst den Leitfaden oben bis zum Ende durchscrollen.";
      hint.classList.add("form-msg", "error");
    }
  });
})();
