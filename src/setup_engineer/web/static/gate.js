// Leitfaden-Bestätigung: Häkchen erst freigeben, wenn bis zum Ende gelesen wurde.
(() => {
  const box = document.getElementById("gate-scroll");
  const check = document.getElementById("gate-check");
  const hint = document.getElementById("gate-hint");
  const end = document.getElementById("gate-end");
  if (!box || !check || !end) return;
  check.disabled = true;
  const unlock = () => {
    check.disabled = false;
    hint.textContent = "Danke fürs Lesen.";
  };
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { unlock(); io.disconnect(); }
    }, { root: box, threshold: 1 });
    io.observe(end);
  } else {
    unlock();
  }
})();
