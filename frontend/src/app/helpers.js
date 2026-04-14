import { EVENT_DRAFT_KEY, FALLBACK_FLYER } from "./constants";

export const saveDraft = (data) => {
  try {
    localStorage.setItem(
      EVENT_DRAFT_KEY,
      JSON.stringify({ ...data, _savedAt: Date.now() })
    );
  } catch {
    // ignore storage errors
  }
};

export const loadDraft = () => {
  try {
    const r = localStorage.getItem(EVENT_DRAFT_KEY);
    return r ? JSON.parse(r) : null;
  } catch {
    return null;
  }
};

export const clearDraft = () => {
  localStorage.removeItem(EVENT_DRAFT_KEY);
};

export function slugify(input) {
  const str = String(input ?? "");
  const noDiacritics = str.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  return noDiacritics
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

export function normalizeImgUrl(raw) {
  if (!raw) return "";
  const v =
    typeof raw === "string"
      ? raw.trim()
      : raw.url
        ? String(raw.url).trim()
        : "";
  if (!v) return "";
  if (/^https?:\/\//i.test(v)) return v;
  const withSlash = v.startsWith("/") ? v : `/${v}`;
  return `${window.location.origin}${withSlash}`;
}

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

export function minPositivePrice(items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const nums = items
    .map((it) => Number(it?.price))
    .filter((n) => Number.isFinite(n) && n > 0);
  if (!nums.length) return null;
  return Math.min(...nums);
}

export function priceLabelForEvent(ev, formatMoneyFn) {
  const p = minPositivePrice(ev?.items);
  if (p == null) return "Entradas";
  return `Desde ${formatMoneyFn(p)} / Entradas`;
}

export const normalizeAssetUrl = (u, opts = {}) => {
  if (!u) return "";
  const s = String(u).trim();
  if (!s) return "";
  const allowBlob = !!opts.allowBlob;

  if (s.startsWith("blob:")) return allowBlob ? s : "";

  if (/^(https?:)?\/\//i.test(s) || s.startsWith("data:")) return s;

  return s.startsWith("/") ? s : `/${s}`;
};

export function flyerSrc(ev) {
  return (
    normalizeAssetUrl(ev?.flyer_url || ev?.hero_bg || ev?.image_url) || FALLBACK_FLYER
  );
}

export async function readJsonOrText(response) {
  const ct = (response.headers.get("content-type") || "").toLowerCase();
  if (ct.includes("application/json")) {
    return await response.json();
  }
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    return { ok: response.ok, detail: text };
  }
}

export const qrImgUrl = (payload, size = 220) => {
  const s = Math.max(120, Math.min(600, Number(size) || 220));
  const enc = encodeURIComponent(payload || "");
  return `https://api.qrserver.com/v1/create-qr-code/?size=${s}x${s}&data=${enc}`;
};

export const downloadQrPng = async (payload, filename = "qr.png", size = 420) => {
  const url = qrImgUrl(payload, size);
  const r = await fetch(url);
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1500);
};

export const downloadTicketsPdf = async (
  tenant,
  ticketIds = [],
  filename = "tickets.pdf"
) => {
  try {
    if (!ticketIds || ticketIds.length === 0) return;
    const idsParam = encodeURIComponent(ticketIds.join(","));
    const url = `/api/orders/tickets.pdf?tenant=${encodeURIComponent(tenant || "default")}&ids=${idsParam}`;
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(blobUrl);
  } catch (e) {
    console.error("downloadTicketsPdf error:", e);
    alert("No se pudo descargar el PDF.");
  }
};

export const sendTicketsByEmail = async (tenant, ticketIds = []) => {
  try {
    if (!ticketIds || ticketIds.length === 0) return;
    const idsParam = encodeURIComponent(ticketIds.join(","));
    const url = `/api/orders/tickets.pdf?tenant=${encodeURIComponent(tenant || "default")}&ids=${idsParam}&deliver=1`;
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`${res.status} ${t}`);
    }
    const data = await readJsonOrText(res);
    alert(`Listo ✅ Te lo mandamos a: ${data.sent_to}`);
    return data;
  } catch (e) {
    console.error("sendTicketsByEmail error:", e);
    alert("No se pudo enviar el mail (revisá SMTP o el login). ");
  }
};
