/* Trophäen: Zeichnungen, Pokalschrank-Vorschaubilder und Freischalt-Pop-up.
   Die Daten (welche Trophäe, Material, Punkte) kommen vom Server; hier wird nur gezeichnet und gefeiert. */
(() => {
  // ================================================================ Materialien
  const MAT = {
    bronze: { name: "Bronze", hi: "#efb27a", mid: "#c8834a", lo: "#6f4224", ray: "rgba(200,131,74,.55)" },
    silber: { name: "Silber", hi: "#ffffff", mid: "#c9d2dc", lo: "#6f7c8b", ray: "rgba(201,210,220,.5)" },
    gold:   { name: "Gold",   hi: "#fff0a8", mid: "#f3c33b", lo: "#9c6f08", ray: "rgba(243,195,59,.55)" },
    lila:   { name: "Amethyst", hi: "#efe4ff", mid: "#b18cf6", lo: "#5a35b0", ray: "rgba(177,140,246,.6)" },
    chrom:  { name: "Chrom",  hi: "#ffffff", mid: "#9fb0c2", lo: "#3c4a5a", ray: "rgba(159,176,194,.5)" },
    kristall: { name: "Kristall", hi: "rgba(235,248,255,.95)", mid: "rgba(143,211,255,.45)", lo: "rgba(80,150,210,.75)", ray: "rgba(143,211,255,.55)", glass: true },
    smaragd: { name: "Smaragd", hi: "#c9f7de", mid: "#3dbb84", lo: "#11603f", ray: "rgba(61,187,132,.55)" },
    rot:    { name: "Emaille", hi: "#ffb3ad", mid: "#ef5d55", lo: "#8e2620", ray: "rgba(239,93,85,.5)" },
    blech:  { name: "Blech", hi: "#d4dbe3", mid: "#8593a3", lo: "#46525f", ray: "rgba(156,169,184,.45)" },
    nacht:  { name: "Emaille", hi: "#8fa8ff", mid: "#2b3f8f", lo: "#141d45", ray: "rgba(120,140,255,.5)" },
  };
  let uid = 0;
  // Liefert Farbverlauf-Definitionen und Referenzen für ein Material
  function M(key) {
    const m = MAT[key], id = `m${++uid}`;
    const defs = `<linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${m.hi}"/><stop offset=".5" stop-color="${m.mid}"/><stop offset="1" stop-color="${m.lo}"/></linearGradient>
      <linearGradient id="${id}v" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${m.hi}"/><stop offset=".55" stop-color="${m.mid}"/><stop offset="1" stop-color="${m.lo}"/></linearGradient>`;
    return { ...m, key, defs, f: `url(#${id})`, fv: `url(#${id}v)` };
  }
  const T = (x, y, txt, size, fill, extra = "") =>
    `<text x="${x}" y="${y}" text-anchor="middle" font-family="Saira, sans-serif" font-weight="800" font-size="${size}" font-stretch="62%" fill="${fill}" ${extra}>${txt}</text>`;
  // Sockel in drei Varianten
  function base(m, kind = "block", label = "") {
    if (kind === "rund") return `<ellipse cx="80" cy="184" rx="44" ry="10" fill="#141a22"/><path d="M36 176v8c0 6 20 10 44 10s44-4 44-10v-8z" fill="#161d26"/>
      <ellipse cx="80" cy="176" rx="44" ry="10" fill="#222c39" stroke="${m.lo}" stroke-width="2"/>${label ? T(80, 190, label, 9, m.mid) : ""}`;
    if (kind === "holz") return `<path d="M34 172h92l6 22H28z" fill="#5b3b24"/><path d="M34 172h92l2 6H32z" fill="#7a5233"/>
      <rect x="56" y="180" width="48" height="10" rx="2" fill="${m.f}"/>${label ? T(80, 188.5, label, 8, "#1b232e") : ""}`;
    return `<rect x="38" y="168" width="84" height="26" rx="3" fill="#161d26" stroke="${m.lo}" stroke-width="2"/>
      <rect x="50" y="174" width="60" height="14" rx="2" fill="${m.f}"/>${label ? T(80, 185, label, 10, "#1b232e") : ""}`;
  }
  // Stufen-Details: Silber Gravurlinien, Gold Edelstein, Amethyst Funkeln
  function extras(tier) {
    let s = "";
    if (tier === "silber" || tier === "gold" || tier === "lila") s += `<path d="M42 192h76" stroke="#e9edf1" stroke-opacity=".25" stroke-width="1"/>`;
    if (tier === "gold" || tier === "lila") s += `<path d="M80 160l6 6-6 6-6-6z" fill="#ef5d55" stroke="#fff" stroke-opacity=".6"/>`;
    if (tier === "lila") s += [[22, 40], [138, 30], [140, 120], [18, 128], [118, 8]].map(([x, y], i) =>
      `<path d="M${x} ${y - 7}l2 5 5 2-5 2-2 5-2-5-5-2 5-2z" fill="#efe4ff" opacity="${.6 + (i % 2) * .4}"/>`).join("");
    return s;
  }
  const shine = (d) => `<path d="${d}" fill="none" stroke="#fff" stroke-opacity=".38" stroke-width="4" stroke-linecap="round"/>`;

  // ================================================================ Formen
  const DRAW = {
    // A-B-A: drei Säulen, B höher – wie ein Siegerpodest der Messwerte
    testfahrer(m) {
      return `${m.defs}${base(m, "block", "A · B · A")}
        <rect x="40" y="88" width="24" height="80" rx="3" fill="${m.fv}"/><rect x="68" y="52" width="24" height="116" rx="3" fill="${m.fv}"/><rect x="96" y="88" width="24" height="80" rx="3" fill="${m.fv}"/>
        ${T(52, 108, "A", 18, "#1b232e")}${T(80, 72, "B", 18, "#1b232e")}${T(108, 108, "A", 18, "#1b232e")}
        <path d="M40 84h80" stroke="${m.hi}" stroke-width="2" stroke-dasharray="4 4"/>
        <circle cx="80" cy="36" r="10" fill="${m.f}" stroke="${m.lo}" stroke-width="2"/>${shine("M44 96v60")}`;
    },
    // Radmutter-Felge auf Ständer
    boxencrew(m) {
      const spokes = [0, 72, 144, 216, 288].map(a => `<path d="M80 92l0-30" stroke="#1b232e" stroke-width="7" stroke-linecap="round" transform="rotate(${a} 80 92)"/>`).join("");
      return `${m.defs}${base(m, "rund")}<path d="M66 176l8-40h12l8 40z" fill="${m.fv}"/>
        <circle cx="80" cy="92" r="50" fill="#0f141b"/>${[...Array(24)].map((_, i) => `<rect x="77" y="40" width="6" height="7" fill="#2a3646" transform="rotate(${i * 15} 80 92)"/>`).join("")}
        <circle cx="80" cy="92" r="38" fill="${m.f}"/>${spokes}<circle cx="80" cy="92" r="13" fill="${m.fv}" stroke="#1b232e" stroke-width="2"/>
        <path d="M80 84l7 4v8l-7 4-7-4v-8z" fill="#1b232e"/>${shine("M54 70a36 36 0 0 1 22-14")}`;
    },
    // Drehzahlmesser-Skulptur
    kilometer(m) {
      const ticks = [...Array(11)].map((_, i) => { const a = (-210 + i * 24) * Math.PI / 180, r1 = 44, r2 = i % 2 ? 38 : 34;
        return `<line x1="${80 + r1 * Math.cos(a)}" y1="${96 + r1 * Math.sin(a)}" x2="${80 + r2 * Math.cos(a)}" y2="${96 + r2 * Math.sin(a)}" stroke="${i > 8 ? "#ef5d55" : "#e9edf1"}" stroke-width="3"/>`; }).join("");
      return `${m.defs}${base(m, "block", "KM")}<path d="M70 168l4-24h12l4 24z" fill="${m.fv}"/>
        <circle cx="80" cy="96" r="58" fill="${m.f}"/><circle cx="80" cy="96" r="50" fill="#11161d"/>${ticks}
        <path d="M80 96L112 70" stroke="#f3c33b" stroke-width="4" stroke-linecap="round"/><circle cx="80" cy="96" r="7" fill="${m.f}"/>
        <rect x="64" y="112" width="32" height="13" rx="2" fill="#222c39"/>${T(80, 122.5, "99999", 10, "#3dbb84")}${shine("M38 74a46 46 0 0 1 24-30")}`;
    },
    // Fackel mit echtem Feuer
    dauerbrenner(m) {
      return `${m.defs}<defs><linearGradient id="fl${uid}" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#ef5d55"/><stop offset=".5" stop-color="#ff9a3d"/><stop offset="1" stop-color="#ffe28a"/></linearGradient></defs>
        ${base(m, "block")}<path d="M70 168l-4-74h28l-4 74z" fill="${m.fv}"/>
        <path d="M66 112h28M67 132h26M68 150h24" stroke="${m.lo}" stroke-width="3"/><ellipse cx="80" cy="94" rx="20" ry="7" fill="${m.f}" stroke="${m.lo}" stroke-width="2"/>
        <path d="M80 90c-18 0-24-14-20-26 4-12 14-16 12-34 12 8 16 20 12 30 6-4 8-10 8-16 10 10 12 22 8 32-3 8-10 14-20 14z" fill="url(#fl${uid})"/>
        <path d="M80 90c-8 0-11-6-9-12 2-6 7-8 7-15 6 5 9 10 8 16-1 7-3 11-6 11z" fill="#fff6c9"/>${shine("M71 104l2 56")}`;
    },
    // Prototyp-Silhouette auf zwei Stelzen
    garage(m) {
      return `${m.defs}${base(m, "block")}<rect x="54" y="122" width="8" height="46" fill="${m.fv}"/><rect x="98" y="122" width="8" height="46" fill="${m.fv}"/>
        <path d="M14 116c6-6 16-8 30-9l16-15c10-6 26-7 36-3l12 12c14 0 26 2 34 6l4 10H14z" fill="${m.f}"/>
        <path d="M66 94c8-4 20-5 28-2l8 10H60z" fill="#1b232e"/><circle cx="44" cy="120" r="11" fill="#11161d" stroke="${m.hi}" stroke-width="3"/>
        <circle cx="118" cy="120" r="11" fill="#11161d" stroke="${m.hi}" stroke-width="3"/><path d="M132 98l12-4v12" fill="none" stroke="${m.lo}" stroke-width="4"/>
        ${shine("M30 110c20-4 70-6 100-2")}`;
    },
    // Strecke als Drahtskulptur
    strecke(m) {
      return `${m.defs}${base(m, "rund")}<path d="M80 176v-22" stroke="${m.lo}" stroke-width="6"/>
        <path d="M34 120c-10-8-6-24 6-26l26-4c10-2 10-14 18-20 10-8 26-4 28 8 2 10-8 14-6 22 2 8 16 6 22 14 8 10 0 28-14 28H52c-8 0-12-14-18-22z" fill="none" stroke="${m.f}" stroke-width="9" stroke-linejoin="round"/>
        <path d="M34 120c-10-8-6-24 6-26l26-4c10-2 10-14 18-20 10-8 26-4 28 8 2 10-8 14-6 22 2 8 16 6 22 14 8 10 0 28-14 28H52c-8 0-12-14-18-22z" fill="none" stroke="${m.hi}" stroke-opacity=".5" stroke-width="2"/>
        <path d="M86 142v-30" stroke="#e9edf1" stroke-width="2"/><path d="M86 112h14v10H86z" fill="#e9edf1"/><path d="M86 112h7v5h-7zM93 117h7v5h-7z" fill="#1b232e"/>`;
    },
    // Federbein
    ingenieur(m) {
      let coil = "";
      for (let i = 0; i < 8; i++) coil += `<path d="M58 ${56 + i * 12}c8 6 36 6 44 0" fill="none" stroke="${m.f}" stroke-width="7" stroke-linecap="round"/>`;
      return `${m.defs}${base(m, "block", "SETUP")}<rect x="72" y="40" width="16" height="122" rx="4" fill="#2a3646"/><rect x="75" y="40" width="10" height="70" fill="${m.fv}"/>
        <circle cx="80" cy="30" r="12" fill="none" stroke="${m.f}" stroke-width="7"/><path d="M56 50h48M56 152h48" stroke="${m.f}" stroke-width="8" stroke-linecap="round"/>${coil}`;
    },
    // Daten-Turm aus Scheiben
    archivar(m) {
      let discs = "";
      for (let i = 0; i < 5; i++) { const y = 150 - i * 24, dx = (i % 2 ? 4 : -4);
        discs += `<path d="M${40 + dx} ${y}v-12c0-7 18-12 40-12s40 5 40 12v12c0 7-18 12-40 12s-40-5-40-12z" fill="${m.fv}"/><ellipse cx="${80 + dx}" cy="${y - 12}" rx="40" ry="12" fill="${m.f}" stroke="${m.lo}" stroke-width="1.5"/><ellipse cx="${80 + dx}" cy="${y - 12}" rx="10" ry="3" fill="#1b232e"/>`; }
      return `${m.defs}${base(m, "rund")}${discs}`;
    },
    // Taschen-Stoppuhr in Halterung
    uhrwerk(m) {
      const ticks = [...Array(12)].map((_, i) => `<line x1="80" y1="62" x2="80" y2="${i % 3 ? 67 : 71}" stroke="#1b232e" stroke-width="${i % 3 ? 2 : 3}" transform="rotate(${i * 30} 80 104)"/>`).join("");
      return `${m.defs}${base(m, "holz")}<path d="M48 170c0-20 10-24 32-24s32 4 32 24" fill="none" stroke="${m.lo}" stroke-width="5"/>
        <rect x="74" y="34" width="12" height="14" rx="3" fill="${m.fv}"/><circle cx="80" cy="30" r="8" fill="none" stroke="${m.f}" stroke-width="4"/><path d="M110 64l8-8" stroke="${m.f}" stroke-width="7" stroke-linecap="round"/>
        <circle cx="80" cy="104" r="50" fill="${m.f}"/><circle cx="80" cy="104" r="42" fill="#e9edf1"/>${ticks}
        <path d="M80 104V72M80 104l18 10" stroke="#1b232e" stroke-width="3" stroke-linecap="round"/><path d="M80 104l-14-26" stroke="#ef5d55" stroke-width="2"/><circle cx="80" cy="104" r="4" fill="#1b232e"/>${shine("M46 84a40 40 0 0 1 20-22")}`;
    },
    // Kristall-Obelisk (fest)
    gtp(m) {
      return `${m.defs}<rect x="36" y="166" width="88" height="28" rx="3" fill="#161d26" stroke="#f3c33b" stroke-width="2"/>${T(80, 186, "5 / 5 GTP", 12, "#f3c33b")}
        <path d="M54 166l-6-104 32-46 32 46-6 104z" fill="${m.f}" stroke="rgba(255,255,255,.8)" stroke-width="1.5"/>
        <path d="M80 16v150M48 62l32 20 32-20M54 166l26-84 26 84" fill="none" stroke="rgba(255,255,255,.45)" stroke-width="1.2"/>
        ${T(80, 128, "GTP", 22, "rgba(255,255,255,.85)")}<path d="M60 56l20-30" stroke="#fff" stroke-opacity=".8" stroke-width="3" stroke-linecap="round"/>`;
    },
    // Carbon-Wappen mit elf Sternen (fest)
    gt3(m) {
      const stars = [...Array(11)].map((_, i) => { const a = (-160 + i * 14) * Math.PI / 180; return `<circle cx="${80 + 46 * Math.cos(a)}" cy="${96 + 46 * Math.sin(a)}" r="3" fill="#f3c33b"/>`; }).join("");
      const g = M("gold");
      return `${g.defs}<defs><pattern id="cf${++uid}" width="8" height="8" patternUnits="userSpaceOnUse"><rect width="8" height="8" fill="#151b23"/><rect width="4" height="4" fill="#26303d"/><rect x="4" y="4" width="4" height="4" fill="#26303d"/></pattern></defs>
        ${base(g, "block")}<path d="M28 36h104v56c0 40-24 62-52 74-28-12-52-34-52-74z" fill="url(#cf${uid})" stroke="#f3c33b" stroke-width="5"/>
        ${stars}${T(80, 118, "GT3", 34, "#e9edf1")}<path d="M50 128h60" stroke="#f3c33b" stroke-width="3"/>`;
    },
    // Doppelpokal Gold + Chrom (fest)
    allrounder() {
      const g = M("gold"), c = M("chrom");
      const cupAt = (x, mm, flip) => `<path d="M${x - 24} 46h48c0 34-8 52-24 58-16-6-24-24-24-58z" fill="${mm.f}"/><path d="M${x + (flip ? -24 : 24)} 54c${flip ? -14 : 14} 0 ${flip ? -14 : 14} 24 ${flip ? 4 : -4} 28" fill="none" stroke="${mm.f}" stroke-width="5"/><rect x="${x - 5}" y="104" width="10" height="24" fill="${mm.fv}"/>`;
      return `${g.defs}${c.defs}${base(g, "block", "2 IN 1")}<path d="M44 128h72l6 40H38z" fill="#222c39"/>${cupAt(56, g, true)}${cupAt(104, c, false)}
        <path d="M56 74l48 0" stroke="#e9edf1" stroke-width="2" stroke-dasharray="3 3"/>${shine("M40 52c0 20 4 32 10 40")}`;
    },
    // Gipfelflagge (fest)
    pionier(m) {
      return `${m.defs}<path d="M14 194L62 92l22 30 18-24 44 96z" fill="#3a4757"/><path d="M62 92l22 30 18-24 10 22-20-6-14 14-22-16z" fill="#e9edf1"/>
        <path d="M84 120V20" stroke="${m.mid}" stroke-width="5"/><circle cx="84" cy="18" r="5" fill="${m.f}"/>
        <path d="M86 24c14-6 28 6 44 0v34c-16 6-30-6-44 0z" fill="#e9edf1"/>${[0, 1, 2, 3].map(r => [0, 1, 2, 3, 4].map(c => (r + c) % 2 ? "" :
          `<rect x="${86 + c * 8.8}" y="${25 + r * 8.5 + (c % 2 ? 1 : 0)}" width="8.8" height="8.5" fill="#1b232e"/>`).join("")).join("")}
        <rect x="46" y="176" width="70" height="14" rx="2" fill="${m.f}"/>${T(81, 186.5, "ERSTER TEST", 9, "#1b232e")}`;
    },
    // Grundstein mit Kelle (fest)
    grundstein(m) {
      return `${m.defs}<path d="M24 120l56-20 56 20v52l-56 22-56-22z" fill="#5c6878"/><path d="M24 120l56 20 56-20-56-20z" fill="#7d8a99"/><path d="M80 140v54" stroke="#3a4757" stroke-width="2"/>
        ${T(52, 168, "S1", 22, m.mid, 'transform="skewY(18) translate(0 -18)"')}<path d="M98 84l26-40 8 6-24 38z" fill="${m.f}"/><path d="M92 92l18-10 6 8-18 12z" fill="#5b3b24"/>`;
    },
    // Globus (fest)
    kartograf(m) {
      return `${m.defs}${base(m, "holz", "STUFE 2")}<path d="M80 166v-20" stroke="${m.lo}" stroke-width="7"/><path d="M30 92a50 50 0 0 0 100 0" fill="none" stroke="${m.f}" stroke-width="6"/>
        <circle cx="80" cy="88" r="44" fill="#2b5f8f"/><path d="M50 70c10-6 22 2 30-6s20-4 24 4-6 16 2 22 4 18-8 20-10-10-20-6-18 10-24 2 2-14-6-20 0-12 2-16z" fill="#3dbb84"/>
        <path d="M36 88h88M80 44v88M44 66h72M44 110h72" stroke="#e9edf1" stroke-opacity=".35" stroke-width="1.5"/><ellipse cx="80" cy="88" rx="20" ry="44" fill="none" stroke="#e9edf1" stroke-opacity=".35" stroke-width="1.5"/>
        ${shine("M50 60a36 36 0 0 1 22-12")}`;
    },
    // ---------------- geheim
    waage(m) {
      return `${m.defs}${base(m, "block", "±0")}<path d="M76 168l2-118h4l2 118z" fill="${m.fv}"/><circle cx="80" cy="46" r="7" fill="${m.f}"/>
        <path d="M30 58h100" stroke="${m.f}" stroke-width="6" stroke-linecap="round"/>
        ${[34, 126].map(x => `<path d="M${x} 58l-16 46M${x} 58l16 46" stroke="${m.hi}" stroke-width="1.5"/><path d="M${x - 22} 104h44c-4 12-12 16-22 16s-18-4-22-16z" fill="${m.f}"/>`).join("")}
        <path d="M72 168h16l-8-12z" fill="${m.lo}"/>`;
    },
    nachtschicht() {
      const m = M("nacht"), g = M("gold");
      return `${m.defs}${g.defs}${base(g, "rund")}<path d="M80 172v-30" stroke="${g.f}" stroke-width="6"/>
        <path d="M96 26a62 62 0 1 0 22 104 48 48 0 1 1-22-104z" fill="${m.f}" stroke="${g.f}" stroke-width="5"/>
        ${[[110, 52, 7], [128, 86, 5], [104, 96, 4], [124, 30, 4]].map(([x, y, r]) => `<path d="M${x} ${y - r * 2}l${r * .6} ${r * 1.4} ${r * 1.4} ${r * .6}-${r * 1.4} ${r * .6}-${r * .6} ${r * 1.4}-${r * .6}-${r * 1.4}-${r * 1.4}-${r * .6} ${r * 1.4}-${r * .6}z" fill="${g.f}"/>`).join("")}
        ${T(70, 92, "0–5", 16, "#e9edf1", 'opacity=".8"')}`;
    },
    comeback(m) {
      return `${m.defs}${base(m, "rund")}<path d="M80 172v-24" stroke="${m.lo}" stroke-width="6"/>
        <path d="M26 128c10-50 40-86 88-96l14 14c-40 10-64 40-70 82z" fill="${m.f}"/><path d="M58 128c6-42 30-72 70-82l6 18c-34 6-52 30-56 64z" fill="${m.fv}" opacity=".7"/>
        <path d="M34 110c12-36 36-62 72-72" fill="none" stroke="#f3c33b" stroke-width="4"/><path d="M40 112c12-34 34-58 68-68" fill="none" stroke="#1b232e" stroke-width="2"/>`;
    },
    lenkrad(m) {
      return `${m.defs}${base(m, "block")}<path d="M74 168l2-36h8l2 36z" fill="${m.fv}"/>
        <path d="M22 70c0-18 14-30 30-30h56c16 0 30 12 30 30v20c0 22-14 38-30 40H52c-16-2-30-18-30-40z" fill="#11161d" stroke="${m.f}" stroke-width="6"/>
        <path d="M22 70c0-10 4-18 10-22v62c-6-6-10-14-10-20zM138 70c0-10-4-18-10-22v62c6-6 10-14 10-20z" fill="#2a3646"/>
        <rect x="52" y="62" width="56" height="34" rx="5" fill="#0b0f14" stroke="${m.lo}" stroke-width="2"/>${T(80, 88, "2×", 26, "#3dbb84")}
        ${[40, 120].map(x => `<circle cx="${x}" cy="104" r="5" fill="#ef5d55"/><circle cx="${x}" cy="88" r="5" fill="#f3c33b"/>`).join("")}<path d="M44 40h72" stroke="#ef5d55" stroke-width="5"/>`;
    },
    fruehaufsteher(m) {
      const rays = [...Array(9)].map((_, i) => { const a = Math.PI + i * Math.PI / 8; return `<line x1="${80 + 40 * Math.cos(a)}" y1="${120 + 40 * Math.sin(a)}" x2="${80 + 62 * Math.cos(a)}" y2="${120 + 62 * Math.sin(a)}" stroke="${m.f}" stroke-width="6" stroke-linecap="round"/>`; }).join("");
      return `${m.defs}${base(m, "block", "5–7 UHR")}${rays}<path d="M44 120a36 36 0 0 1 72 0z" fill="${m.f}"/><path d="M20 122h120" stroke="#e9edf1" stroke-width="4"/>
        <path d="M32 136h96M46 150h68" stroke="#8fd3ff" stroke-width="3" stroke-linecap="round" opacity=".7"/>${shine("M56 108a26 26 0 0 1 14-14")}`;
    },
    wochenende(m) {
      const flag = (rot) => `<g transform="rotate(${rot} 80 150)"><path d="M80 150V36" stroke="${m.mid}" stroke-width="5"/><path d="M82 38h44v30H82z" fill="#e9edf1"/>
        ${[0, 1, 2].map(r => [0, 1, 2, 3, 4].map(c => (r + c) % 2 ? "" : `<rect x="${82 + c * 8.8}" y="${38 + r * 10}" width="8.8" height="10" fill="#1b232e"/>`).join("")).join("")}</g>`;
      return `${m.defs}${base(m, "block", "SA + SO")}${flag(-22)}<g transform="translate(160 0) scale(-1 1)">${flag(-22)}</g><circle cx="80" cy="150" r="7" fill="${m.f}"/>`;
    },
    metronom(m) {
      return `${m.defs}<path d="M50 190l22-170h16l22 170z" fill="#5b3b24"/><path d="M56 186l18-150h12l18 150z" fill="#7a5233"/>
        ${[...Array(9)].map((_, i) => `<path d="M${74 + i * .2} ${50 + i * 12}h${12 - i * .4}" stroke="#e9edf1" stroke-opacity=".5" stroke-width="1.5"/>`).join("")}
        <path d="M80 166L64 40" stroke="${m.f}" stroke-width="4" stroke-linecap="round"/><rect x="62" y="80" width="12" height="16" rx="2" fill="${m.f}" transform="rotate(-7 68 88)"/>
        <rect x="60" y="164" width="40" height="18" rx="2" fill="${m.f}"/>${T(80, 177, "0,1 s", 11, "#1b232e")}`;
    },
    spiegel(m) {
      return `${m.defs}${base(m, "rund")}<path d="M80 176v-30" stroke="${m.f}" stroke-width="6"/><ellipse cx="80" cy="86" rx="44" ry="58" fill="${m.f}"/>
        <ellipse cx="80" cy="86" rx="36" ry="50" fill="#8fd3ff" opacity=".35"/><ellipse cx="80" cy="86" rx="36" ry="50" fill="none" stroke="#fff" stroke-opacity=".5"/>
        <g transform="translate(160 0) scale(-1 1)">${T(80, 80, "GEFÜHL", 13, "#e9edf1")}</g>${T(80, 104, "MESSUNG", 13, "#1b232e")}
        <path d="M58 46l-10 20M64 52l-12 26" stroke="#fff" stroke-opacity=".7" stroke-width="2.5" stroke-linecap="round"/>`;
    },
    volltreffer(m) {
      return `${m.defs}${base(m, "block", "p < 0,001")}<path d="M74 168l6-34 6 34z" fill="${m.fv}"/>
        ${[56, 44, 32, 20, 9].map((r, i) => `<circle cx="80" cy="84" r="${r}" fill="${i % 2 ? "#e9edf1" : "#ef5d55"}"/>`).join("")}<circle cx="80" cy="84" r="56" fill="none" stroke="${m.f}" stroke-width="5"/>
        <path d="M80 84l52-46" stroke="${m.f}" stroke-width="4"/><path d="M132 38l-4 14 10-4 4-10z" fill="#3dbb84"/>`;
    },
    gruenehoelle(m) {
      const g = M("gold");
      return `${m.defs}${g.defs}${base(g, "holz", "N-SCHLEIFE")}
        <circle cx="80" cy="94" r="56" fill="none" stroke="${m.f}" stroke-width="18"/><circle cx="80" cy="94" r="56" fill="none" stroke="${m.hi}" stroke-opacity=".5" stroke-width="2"/>
        <path d="M80 26l14 12-14 12-14-12z" fill="${m.hi}" stroke="${m.lo}" stroke-width="2"/>${T(80, 104, "A·B·A", 18, m.mid)}`;
    },
    zeitreisender(m) {
      return `${m.defs}${base(m, "holz", "2+ JAHRE")}<rect x="40" y="22" width="80" height="10" rx="3" fill="${m.f}"/><rect x="40" y="156" width="80" height="10" rx="3" fill="${m.f}"/>
        <path d="M44 32v124M116 32v124" stroke="${m.f}" stroke-width="5"/><path d="M54 32c0 40 22 46 22 62s-22 22-22 62h52c0-40-22-46-22-62s22-22 22-62z" fill="#8fd3ff" fill-opacity=".25" stroke="#e9edf1" stroke-opacity=".7" stroke-width="2"/>
        <path d="M60 44h40c-4 18-14 26-20 34-6-8-16-16-20-34zM62 150c4-18 12-24 18-28 6 4 14 10 18 28z" fill="#f3c33b"/><path d="M80 78v44" stroke="#f3c33b" stroke-width="2" stroke-dasharray="2 3"/>`;
    },
    kleeblatt(m) {
      const leaf = (rot) => `<path d="M80 92c-30-6-34-40-12-44 8-2 12 4 12 10 0-6 4-12 12-10 22 4 18 38-12 44z" fill="${m.f}" stroke="${m.lo}" stroke-width="2" transform="rotate(${rot} 80 92)"/>`;
      const g = M("gold");
      return `${m.defs}${g.defs}${base(g, "block", "1.000.")}<path d="M80 96c4 28 0 50-8 72" stroke="${m.lo}" stroke-width="6" fill="none" stroke-linecap="round"/>${[0, 90, 180, 270].map(leaf).join("")}<circle cx="80" cy="92" r="6" fill="#f3c33b"/>`;
    },
    synchron(m) {
      const helmet = (x, c1, c2, flip) => `<g transform="translate(${x} 0)${flip ? " scale(-1 1)" : ""}"><path d="M-30 120c-4-40 12-66 34-66s36 20 36 50v16H-6l-8 12h-16z" fill="${c1}"/>
        <path d="M4 88h34v18H8z" fill="#11161d"/><path d="M-26 100c10-4 30-4 40 0" stroke="${c2}" stroke-width="6" fill="none"/></g>`;
      return `${m.defs}${base(m, "block", "1 TAG")}${helmet(46, "#ef5d55", "#e9edf1", false)}${helmet(114, "#3dbb84", "#f3c33b", true)}${T(80, 152, "=", 30, m.mid)}`;
    },
    kanister(m) {
      return `${m.defs}${base(m, "block", "50 RUNDEN")}<path d="M38 52h62l22 22v86H38z" fill="${m.fv}" stroke="${m.lo}" stroke-width="2"/>
        <path d="M54 40h28v14H54z" fill="none" stroke="${m.f}" stroke-width="6"/><path d="M104 56l12-14 8 8-12 14z" fill="#e9edf1"/>
        <path d="M52 76l54 70M106 76l-54 70" stroke="${m.lo}" stroke-width="5"/><path d="M48 66v84" stroke="#fff" stroke-opacity=".35" stroke-width="4"/>`;
    },
    // ---------------- Pannen
    dejavu(m) {
      const file = (x, y, o) => `<g transform="translate(${x} ${y})" opacity="${o}"><path d="M0 0h44l16 16v62H0z" fill="#e9edf1" stroke="${m.lo}" stroke-width="2"/><path d="M44 0v16h16" fill="#c9d2dc"/>${T(30, 50, ".ibt", 14, "#1b232e")}</g>`;
      return `${m.defs}${base(m, "block", "2×")}${file(30, 30, .55)}${file(56, 60, 1)}<path d="M40 140h28M40 150h28" stroke="${m.mid}" stroke-width="4"/>`;
    },
    kaffee(m) {
      return `${m.defs}${base(m, "block", "F5 F5 F5")}<path d="M40 74h70l-8 76c-1 8-8 12-27 12s-26-4-27-12z" fill="${m.f}"/><path d="M110 88c18 0 18 34-6 34" fill="none" stroke="${m.f}" stroke-width="7"/>
        <ellipse cx="75" cy="76" rx="35" ry="7" fill="#5b3b24"/>${[56, 74, 92].map((x, i) => `<path d="M${x} 62c-8-10 8-16 0-28" fill="none" stroke="#e9edf1" stroke-opacity=".6" stroke-width="3" stroke-linecap="round"/>`).join("")}
        ${T(73, 124, "WARTET…", 11, "#1b232e")}`;
    },
    fingerabdruck(m) {
      return `${m.defs}${base(m, "block", "BB 56,3 %")}<circle cx="80" cy="92" r="52" fill="#11161d" stroke="${m.f}" stroke-width="6"/>
        ${[10, 18, 26, 34, 42].map(r => `<path d="M${80 - r} 96a${r} ${r + 4} 0 0 1 ${r * 2} 0" fill="none" stroke="${m.mid}" stroke-width="2.5" stroke-linecap="round"/>`).join("")}
        <path d="M80 40v14" stroke="#ef5d55" stroke-width="5" stroke-linecap="round"/>${T(80, 136, "NUR KURZ…", 10, "#ef5d55")}`;
    },
    verfall(m) {
      return `${m.defs}${base(m, "block", "2× WEG")}<rect x="30" y="34" width="100" height="112" rx="6" fill="#e9edf1"/><rect x="30" y="34" width="100" height="28" rx="6" fill="#ef5d55"/>
        <rect x="30" y="54" width="100" height="8" fill="#ef5d55"/>${[52, 80, 108].map(x => `<rect x="${x - 3}" y="24" width="6" height="18" rx="3" fill="${m.mid}"/>`).join("")}
        ${T(80, 54, "TAG X", 15, "#e9edf1")}<path d="M44 76h20v16H44zM70 76h20v16H70zM96 76h20v16H96zM44 98h20v16H44zM70 98h20v16H70z" fill="#c9d2dc"/>
        ${T(54, 89, "A", 12, "#1b232e")}${T(80, 89, "B", 12, "#1b232e")}
        <g transform="rotate(-14 80 110)"><rect x="26" y="96" width="108" height="26" rx="4" fill="#e9edf1" fill-opacity=".85" stroke="#ef5d55" stroke-width="4"/>${T(80, 114, "ABGELAUFEN", 12, "#ef5d55", 'letter-spacing="1"')}</g>`;
    },
    pylone(m) {
      return `${m.defs}<path d="M30 180h100v14H30z" fill="#11161d"/><path d="M68 24h24l30 156H38z" fill="#ff8a3d"/><path d="M60 64h40l6 30H54zM50 116h60l6 30H44z" fill="#e9edf1"/>
        <path d="M30 186c20-8 30 6 50-2s32 4 50-4" stroke="#9ca9b8" stroke-width="5" fill="none" stroke-dasharray="2 6" stroke-linecap="round"/>${T(80, 175, "5× KIES", 11, "#1b232e")}`;
    },
    // ---------------- Team
    meisterschale(m, tier) {
      let names = "";
      for (let r = 0; r < 3; r++) for (let i = 0; i < 12; i++) names += `<rect x="78" y="${34 + r * 9}" width="4" height="5" fill="${m.lo}" opacity=".7" transform="rotate(${i * 30 + r * 15} 80 96)"/>`;
      return `${m.defs}<ellipse cx="80" cy="186" rx="40" ry="7" fill="#141a22"/>
        <circle cx="80" cy="96" r="70" fill="${m.f}" stroke="${m.lo}" stroke-width="2"/><circle cx="80" cy="96" r="62" fill="none" stroke="${m.hi}" stroke-width="2"/>
        ${names}<circle cx="80" cy="96" r="34" fill="${m.fv}" stroke="${m.lo}" stroke-width="2"/>
        <circle cx="80" cy="96" r="26" fill="#1b232e"/>${T(80, 102, {bronze: "250", silber: "500", gold: "1.000", lila: "2.000"}[tier], 16, m.hi)}${T(80, 115, "DATEIEN", 7, m.mid)}
        ${[...Array(8)].map((_, i) => `<circle cx="${80 + 48 * Math.cos(i * Math.PI / 4)}" cy="${96 + 48 * Math.sin(i * Math.PI / 4)}" r="4" fill="#ef5d55" stroke="${m.hi}" stroke-width="1"/>`).join("")}
        ${shine("M28 70a56 56 0 0 1 30-36")}`;
    },
    kolben(m, tier) {
      const piston = (rot) => `<g transform="rotate(${rot} 80 110)"><rect x="66" y="40" width="28" height="30" rx="4" fill="${m.f}"/><path d="M66 48h28M66 54h28" stroke="${m.lo}" stroke-width="2"/>
        <path d="M74 70l-4 70h20l-4-70z" fill="${m.fv}"/><circle cx="80" cy="146" r="10" fill="none" stroke="${m.f}" stroke-width="6"/></g>`;
      return `${m.defs}${base(m, "block", {bronze: "1.000", silber: "2.500", gold: "5.000", lila: "10.000"}[tier])}${piston(-24)}${piston(24)}<circle cx="80" cy="110" r="8" fill="#ef5d55"/>`;
    },
    stufe1(_m, _k, it) {
      const k = M("kristall"), g = M("silber");
      return `${k.defs}${g.defs}<rect x="34" y="164" width="92" height="30" rx="3" fill="#161d26" stroke="${g.mid}" stroke-width="2"/>${T(80, 178, it.plate, 10, g.hi)}${T(80, 190, "STUFE 1 · 30 TESTS", 8, "#9ca9b8")}
        <path d="M40 40h80l-12 64c-4 18-16 26-28 26s-24-8-28-26z" fill="${k.f}" stroke="rgba(255,255,255,.8)" stroke-width="1.5"/>
        <path d="M40 40l40 30 40-30M60 40l20 90M100 40l-20 90M52 104h56" fill="none" stroke="rgba(255,255,255,.4)" stroke-width="1.2"/>
        <path d="M72 130h16l4 34H68z" fill="${k.f}" stroke="rgba(255,255,255,.6)"/>${T(80, 92, "1", 30, "rgba(255,255,255,.9)")}<path d="M50 48l8 40" stroke="#fff" stroke-opacity=".8" stroke-width="3" stroke-linecap="round"/>`;
    },
    stufe2(_m, _k, it) {
      const k = M("kristall"), g = M("gold");
      const crown = `<path d="M44 46l10-22 14 16 12-24 12 24 14-16 10 22z" fill="${g.f}" stroke="${g.lo}" stroke-width="1.5"/>${[54, 80, 106].map(x => `<circle cx="${x}" cy="${x === 80 ? 14 : 22}" r="4" fill="#ef5d55"/>`).join("")}`;
      return `${k.defs}${g.defs}<rect x="30" y="162" width="100" height="32" rx="3" fill="#161d26" stroke="${g.mid}" stroke-width="2.5"/>${T(80, 177, it.plate, 11, g.hi)}${T(80, 189, "STUFE 2 · 70 TESTS", 8, g.mid)}
        <path d="M34 50h92l-6 50c-4 30-20 42-40 42s-36-12-40-42z" fill="${k.f}" stroke="${g.f}" stroke-width="4"/>
        <path d="M34 50l46 40 46-40M56 50l24 92M104 50l-24 92" fill="none" stroke="rgba(255,255,255,.4)" stroke-width="1.2"/>
        ${crown}<path d="M70 142h20l6 20H64z" fill="${g.fv}"/>${T(80, 112, "2", 34, "rgba(255,255,255,.92)")}<path d="M44 58l8 42" stroke="#fff" stroke-opacity=".8" stroke-width="3" stroke-linecap="round"/>`;
    },
    krone(_m, _k, it) {
      const g = M("gold"), v = M(it.cls === "GT3" ? "smaragd" : "lila");
      return `${g.defs}${v.defs}<path d="M28 150c0-14 24-22 52-22s52 8 52 22v16c0 10-24 18-52 18s-52-8-52-18z" fill="#7a2230"/><ellipse cx="80" cy="150" rx="52" ry="18" fill="#a03040"/>
        ${[[30, 166], [130, 166], [80, 186]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="5" fill="${g.f}"/>`).join("")}
        <path d="M34 138l-8-82 30 30 24-50 24 50 30-30-8 82c-14 6-32 8-46 8s-32-2-46-8z" fill="${g.f}" stroke="${g.lo}" stroke-width="2"/>
        ${[[26, 54], [56, 84], [80, 34], [104, 84], [134, 54]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="6" fill="${v.f}" stroke="#fff" stroke-opacity=".6"/>`).join("")}
        <path d="M38 120c26 8 58 8 84 0" stroke="${g.lo}" stroke-width="3" fill="none"/>${T(80, 136, it.cls, 16, "#7a2230")}${shine("M44 72l6 52")}`;
    },
    // Fahrzeug-Champion: Lorbeerring mit Silhouette der Klasse, Akzentfarbe je Auto
    champion(m, _k, it) {
      const sil = it.cls === "GTP"
        ? `<path d="M34 104c6-6 14-8 24-9l12-12c8-5 20-6 28-2l9 10c11 0 20 2 26 5l3 8H34z" fill="${m.f}"/><path d="M76 84c6-3 14-3 20-1l6 8H72z" fill="#1b232e"/>`
        : `<path d="M34 104c2-6 8-9 18-10l14-10c10-4 26-4 36 0l12 10c8 1 12 4 14 10z" fill="${m.f}"/><path d="M70 86c8-3 20-3 28 0l6 7H64z" fill="#1b232e"/><path d="M118 92l8-6v8" fill="none" stroke="${m.lo}" stroke-width="3"/>`;
      let leaves = "";
      for (const side of [-1, 1]) for (let i = 0; i < 9; i++) {
        const th = (side < 0 ? 100 + i * 17 : 80 - i * 17) * Math.PI / 180, x = 80 + 58 * Math.cos(th), y = 96 + 58 * Math.sin(th);
        leaves += `<ellipse cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" rx="9" ry="4" transform="rotate(${(th * 180 / Math.PI + 90 + side * 30).toFixed(0)} ${x.toFixed(1)} ${y.toFixed(1)})" fill="${i % 2 ? m.mid : m.hi}"/>`;
      }
      return `${m.defs}<rect x="30" y="164" width="100" height="30" rx="3" fill="#161d26" stroke="${it.accent}" stroke-width="3"/>${T(80, 179, it.plate, 11, m.hi)}${T(80, 190, "CHAMPION", 8, it.accent, 'letter-spacing="2"')}
        <path d="M70 164l4-16h12l4 16z" fill="${m.fv}"/><circle cx="80" cy="96" r="50" fill="#11161d"/><circle cx="80" cy="96" r="50" fill="none" stroke="${it.accent}" stroke-width="4"/>
        ${leaves}${sil}<path d="M42 112h76" stroke="${it.accent}" stroke-width="4"/>
        <path d="M80 18l5 10 11 2-8 8 2 11-10-5-10 5 2-11-8-8 11-2z" fill="${m.f}" stroke="${m.lo}"/>`;
    },
    // Klassen-Champion: Meistergürtel
    guertel(m, _k, it) {
      return `${m.defs}<path d="M4 92c20-6 36-6 44-4v40c-8-2-24-2-44 4z" fill="#3a2418"/><path d="M156 92c-20-6-36-6-44-4v40c8-2 24-2 44 4z" fill="#3a2418"/>
        <path d="M4 100c20-6 36-6 44-4M4 120c20-6 36-6 44-4M156 100c-20-6-36-6-44-4M156 120c-20-6-36-6-44-4" stroke="#5b3b24" stroke-width="2" fill="none" stroke-dasharray="3 3"/>
        <path d="M44 70c12-10 60-10 72 0l10 40-10 40c-12 10-60 10-72 0l-10-40z" fill="${m.f}" stroke="${m.lo}" stroke-width="3"/>
        <ellipse cx="80" cy="110" rx="30" ry="34" fill="#1b232e" stroke="${m.hi}" stroke-width="2"/>${T(80, 108, it.cls, 22, m.hi)}${T(80, 124, "CHAMPION", 8, m.mid, 'letter-spacing="2"')}
        ${[[50, 80], [110, 80], [50, 140], [110, 140]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="5" fill="#ef5d55" stroke="${m.hi}"/>`).join("")}
        ${shine("M52 78c10-6 30-8 44-6")}`;
    },
  };


  function svgFor(def) {
    const m = M(def.mat);
    return DRAW[def.draw](m, def.mat, def) + (def.tiered ? extras(def.mat) : "");
  }
  function fill(root) {
    (root || document).querySelectorAll("svg[data-trophy]").forEach(el => {
      try { el.innerHTML = svgFor(JSON.parse(el.dataset.trophy)); } catch (e) { /* Zeichnung fehlt: Platz bleibt leer */ }
    });
  }

  // ================================================================ Effekte
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let back, front, bctx, fctx;
  function canvases() {
    if (back) return true;
    const b = document.getElementById("fx-back"), f = document.getElementById("fx-front");
    if (!b || !f) return false;
    back = b; front = f; bctx = back.getContext("2d"); fctx = front.getContext("2d");
    return true;
  }
  let parts = [], sparks = [], rockets = [], raf = 0, until = 0, fireworks = false;
  const CONF = ["#f3c33b", "#e9edf1", "#3dbb84", "#b18cf6", "#ef5d55", "#8fd3ff"];
  function size() { if (!canvases()) return; const dpr = Math.min(devicePixelRatio || 1, 2);
    for (const c of [back, front]) { c.width = innerWidth * dpr; c.height = innerHeight * dpr; c.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0); } }
  addEventListener("resize", size);
  let palette = CONF;
  function confetti(n) { const cx = innerWidth / 2, cy = innerHeight * .42;
    for (let i = 0; i < n; i++) { const a = -Math.PI / 2 + (Math.random() - .5) * 2.4, v = 7 + Math.random() * 10;
      parts.push({ x: cx, y: cy, vx: Math.cos(a) * v, vy: Math.sin(a) * v, w: 6 + Math.random() * 6, h: 3 + Math.random() * 4, r: Math.random() * 6, vr: (Math.random() - .5) * .35, c: palette[i % palette.length], life: 1 }); } }
  function rocket() { rockets.push({ x: innerWidth * (.12 + Math.random() * .76), y: innerHeight + 10, vx: (Math.random() - .5) * 1.5, vy: -(11 + Math.random() * 4), ty: innerHeight * (.1 + Math.random() * .32), c: CONF[Math.floor(Math.random() * CONF.length)] }); }
  function burst(x, y, c) { for (let i = 0; i < 70; i++) { const a = (i / 70) * Math.PI * 2, v = 2 + Math.random() * 4.5;
      sparks.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, c: Math.random() < .25 ? "#e9edf1" : c, life: 1 }); } }
  function tick(now) {
    bctx.clearRect(0, 0, innerWidth, innerHeight); fctx.clearRect(0, 0, innerWidth, innerHeight);
    for (const r of rockets) { r.x += r.vx; r.y += r.vy; r.vy *= .985; bctx.fillStyle = r.c; bctx.fillRect(r.x - 1.5, r.y, 3, 10); if (r.y <= r.ty) { burst(r.x, r.y, r.c); r.done = true; } }
    rockets = rockets.filter(r => !r.done);
    for (const s of sparks) { s.x += s.vx; s.y += s.vy; s.vx *= .97; s.vy = s.vy * .97 + .05; s.life -= .012;
      bctx.globalAlpha = Math.max(s.life, 0); bctx.fillStyle = s.c; bctx.beginPath(); bctx.arc(s.x, s.y, 2.2, 0, Math.PI * 2); bctx.fill(); }
    bctx.globalAlpha = 1; sparks = sparks.filter(s => s.life > 0);
    if (fireworks && now < until && Math.random() < .05) rocket();
    for (const p of parts) { p.x += p.vx; p.y += p.vy; p.vx *= .985; p.vy = p.vy * .985 + .22; p.r += p.vr; if (p.y > innerHeight * .75) p.life -= .02;
      fctx.save(); fctx.globalAlpha = Math.max(p.life, 0); fctx.translate(p.x, p.y); fctx.rotate(p.r); fctx.scale(1, Math.cos(p.r * 2)); fctx.fillStyle = p.c; fctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h); fctx.restore(); }
    parts = parts.filter(p => p.life > 0 && p.y < innerHeight + 40);
    raf = (parts.length || sparks.length || rockets.length || (fireworks && now < until)) ? requestAnimationFrame(tick) : 0;
  }
  function startFx(big, panne) { if (reduce) return; palette = panne ? ["#9ca9b8", "#ef5d55", "#e9edf1", "#36455a"] : CONF; size(); fireworks = big; until = performance.now() + (big ? 6500 : 0); parts = []; sparks = []; rockets = [];
    setTimeout(() => confetti(big ? 220 : panne ? 70 : 160), panne ? 700 : 380); if (big) for (let i = 0; i < 4; i++) setTimeout(rocket, i * 260); if (!raf) raf = requestAnimationFrame(tick); }
  function stopFx() { if (!back) return; cancelAnimationFrame(raf); raf = 0; parts = []; sparks = []; rockets = []; fireworks = false;
    bctx.clearRect(0, 0, innerWidth, innerHeight); fctx.clearRect(0, 0, innerWidth, innerHeight); }


  // ================================================================ Pop-up
  function buildStage() {
    let stage = document.getElementById("trophy-stage");
    if (stage) return stage;
    stage = document.createElement("div");
    stage.id = "trophy-stage"; stage.className = "trophy-stage"; stage.hidden = true;
    stage.setAttribute("role", "dialog"); stage.setAttribute("aria-modal", "true"); stage.setAttribute("aria-labelledby", "pop-title");
    stage.innerHTML = `<canvas id="fx-back"></canvas><div class="rays"></div>
      <div class="trophy-card"><svg class="trophy-big" id="pop-svg" viewBox="0 0 160 200" aria-hidden="true"></svg>
        <span class="kicker" id="pop-kicker"></span><h2 id="pop-title"></h2><span class="tier-name" id="pop-tier"></span>
        <span class="pts" id="pop-pts"></span><p id="pop-desc"></p><span class="trophy-count" id="pop-count"></span>
        <button class="btn btn-primary" type="button" id="pop-close">Weiter</button></div><canvas id="fx-front"></canvas>`;
    document.body.appendChild(stage);
    return stage;
  }
  function popup(list, onDone) {
    if (!list || !list.length) return;
    const stage = buildStage();
    let i = 0;
    const lastFocus = document.activeElement;
    function show() {
      const d = list[i], m = MAT[d.mat] || MAT.gold;
      const team = d.kind === "team", panne = d.kind === "panne", secret = d.kind === "geheim", champ = d.kind === "auto";
      const big = team || secret || champ;
      stage.style.setProperty("--ray", panne ? "rgba(156,169,184,.35)" : m.ray);
      stage.style.setProperty("--ray-solid", panne ? "#ef5d55" : m.glass ? "#8fd3ff" : m.mid);
      stage.classList.toggle("big", big); stage.classList.toggle("panne", panne);
      document.getElementById("pop-svg").innerHTML = svgFor(d);
      document.getElementById("pop-kicker").textContent = team ? "Team-Trophäe für alle!" : panne ? "Hoppla – Pannen-Trophäe!" : secret ? "Geheime Trophäe gefunden!" : champ ? "Champion!" : "Trophäe freigeschaltet";
      document.getElementById("pop-title").textContent = d.name;
      document.getElementById("pop-tier").textContent = d.tier || (panne ? "Passiert jedem mal" : secret ? "Geheim" : team ? "Gemeinsam geschafft" : champ ? "Champion" : "Einmalig");
      document.getElementById("pop-pts").textContent = `+${d.pts} Punkte`;
      document.getElementById("pop-desc").textContent = d.desc;
      document.getElementById("pop-count").textContent = list.length > 1 ? `${i + 1} von ${list.length}` : "";
      document.getElementById("pop-close").textContent = i < list.length - 1 ? "Nächste Trophäe" : "Weiter";
      stage.hidden = true; void stage.offsetWidth; stage.hidden = false;
      document.getElementById("pop-close").focus();
      stopFx(); startFx(big, panne);
    }
    function next() {
      i += 1;
      if (i < list.length) { show(); return; }
      stage.hidden = true; stopFx();
      document.removeEventListener("keydown", onKey);
      if (lastFocus && lastFocus.focus) lastFocus.focus();
      if (onDone) onDone();
    }
    function onKey(e) { if (e.key === "Escape" && !stage.hidden) next(); }
    document.getElementById("pop-close").onclick = next;
    document.addEventListener("keydown", onKey);
    show();
  }

  window.Trophies = { fill, popup, svgFor };
  document.addEventListener("DOMContentLoaded", () => {
    fill();
    const data = document.getElementById("new-trophies");
    if (!data) return;
    let list = [];
    try { list = JSON.parse(data.textContent); } catch (e) { return; }
    popup(list, () => {
      fetch("/api/pokale/gesehen", { method: "POST", headers: { "x-csrf-token": data.dataset.csrf } }).catch(() => {});
    });
  });
})();
