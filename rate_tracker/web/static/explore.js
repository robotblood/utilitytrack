/* Shared helpers for the /explore charts: one floating tooltip and number formats.
   Tooltip text goes in with textContent only; tract names come from the Census API. */
const tip = (() => {
  const box = document.createElement("div");
  box.className = "tip";
  box.hidden = true;
  document.body.append(box);
  function show(x, y, title, rows) {
    const head = document.createElement("div");
    head.className = "tip-title";
    head.textContent = title;
    box.replaceChildren(head, ...rows.map(([value, label]) => {
      const row = document.createElement("div"), v = document.createElement("strong"), l = document.createElement("span");
      row.className = "tip-row";
      v.textContent = value;
      l.textContent = label;
      row.append(v, l);
      return row;
    }));
    box.hidden = false;
    const w = box.offsetWidth, h = box.offsetHeight;
    box.style.left = `${Math.max(8, Math.min(x + 14, innerWidth - w - 8))}px`;
    box.style.top = `${y + 14 + h > innerHeight ? y - h - 14 : y + 14}px`;
  }
  return { show, hide: () => { box.hidden = true; } };
})();

const fmt = {
  pct: (v, d = 1) => (v == null ? "–" : `${(v * 100).toFixed(d)}%`),
  money: (v) => (v == null ? "–" : `$${Math.round(v).toLocaleString()}`),
  k: (v) => (v == null ? "–" : `$${Math.round(v / 1000)}k`),
};
