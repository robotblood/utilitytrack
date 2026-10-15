/* Shared helpers for the /explore charts: one floating tooltip and number formats.
   Tooltip text goes in with textContent only; tract names come from the Census API. */
const tip = (() => {
  const box = document.createElement("div");
  box.className = "tip";
  box.hidden = true;
  document.body.append(box);
  let pinned = false;
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
  function hide() { if (!pinned) box.hidden = true; }
  function unpin() { pinned = false; box.hidden = true; }

  // Touch: a tap shows what hovering shows. Touch pointers fire pointerleave as soon as the
  // finger lifts, so a tapped tooltip stays until the next tap or a scroll.
  document.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse") return;
    unpin();
    e.target.dispatchEvent(new PointerEvent("pointermove", {
      bubbles: true, clientX: e.clientX, clientY: e.clientY, pointerType: e.pointerType }));
    pinned = !box.hidden;
  });
  addEventListener("scroll", () => { if (pinned) unpin(); }, { passive: true });
  return { show, hide };
})();

const fmt = {
  pct: (v, d = 1) => (v == null ? "–" : `${(v * 100).toFixed(d)}%`),
  money: (v) => (v == null ? "–" : `$${Math.round(v).toLocaleString()}`),
  k: (v) => (v == null ? "–" : `$${Math.round(v / 1000)}k`),
};
