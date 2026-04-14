export function eventSalesProgress(ev) {
  const totalDirect = Number(ev?.stock_total);
  const soldDirect = Number(ev?.stock_sold);
  if (
    Number.isFinite(totalDirect) &&
    totalDirect > 0 &&
    Number.isFinite(soldDirect) &&
    soldDirect >= 0
  ) {
    const pct = Math.max(0, Math.min(100, (soldDirect / totalDirect) * 100));
    return { sold: soldDirect, total: totalDirect, pct };
  }

  const items = Array.isArray(ev?.items) ? ev.items : [];
  const totals = items.reduce(
    (acc, it) => {
      const t = Number(it?.stock);
      const s = Number(it?.sold);
      acc.total += Number.isFinite(t) && t > 0 ? t : 0;
      acc.sold += Number.isFinite(s) && s > 0 ? s : 0;
      return acc;
    },
    { total: 0, sold: 0 }
  );

  if (totals.total > 0) {
    const pct = Math.max(0, Math.min(100, (totals.sold / totals.total) * 100));
    return { ...totals, pct };
  }

  return { sold: 0, total: 0, pct: 0 };
}

export function isEventSoldOut(ev) {
  if (Boolean(ev?.sold_out)) return true;
  const p = eventSalesProgress(ev);
  return p.total > 0 && p.sold >= p.total;
}

export function formatEventDateText(dateISO, timeStr) {
  if (!dateISO) return "";
  const [y, m, d] = String(dateISO || "").split("-").map((n) => Number(n));
  if (!y || !m || !d) return "";

  const [hh, mm] = String(timeStr || "").split(":").map((n) => Number(n));
  const hasTime = Number.isFinite(hh) && Number.isFinite(mm);

  const dt = hasTime ? new Date(y, m - 1, d, hh, mm) : new Date(y, m - 1, d);
  if (Number.isNaN(dt.getTime())) return "";

  const weekday = dt.toLocaleDateString("es-AR", { weekday: "short" }).replace(".", "");
  const day = String(dt.getDate()).padStart(2, "0");
  const month = dt.toLocaleDateString("es-AR", { month: "long" });
  const base = `${weekday.charAt(0).toUpperCase() + weekday.slice(1)}, ${day} de ${month.charAt(0).toUpperCase() + month.slice(1)}`;

  if (!hasTime) return base;
  return `${base}, ${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}hs`;
}
