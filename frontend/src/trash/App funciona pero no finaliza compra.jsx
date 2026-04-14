
// Wizard Draft & Steps Helpers
const EVENT_DRAFT_KEY = "ticketera.newEventDraft.v1";
const saveDraft = (data)=>{try{localStorage.setItem(EVENT_DRAFT_KEY,JSON.stringify({...data,_savedAt:Date.now()}));}catch(e){}}
const loadDraft = ()=>{try{const r=localStorage.getItem(EVENT_DRAFT_KEY);return r?JSON.parse(r):null;}catch{return null}}
const clearDraft = ()=>{localStorage.removeItem(EVENT_DRAFT_KEY)};

import React, { useEffect, useMemo, useState } from "react";

// -------------------------
// Slug helper (sin dependencias)
// Convierte texto a: minúsculas, sin tildes, solo [a-z0-9-]
// -------------------------
function slugify(input) {
  const str = String(input ?? "");
  const noDiacritics = str
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
  return noDiacritics
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}


// -------------------------
// Producer: progreso de ventas
// - Soporta payloads distintos (stock_total/stock_sold o items[].stock/items[].sold)
// - Devuelve { sold, total, pct }
// -------------------------
function eventSalesProgress(ev) {
  // Caso 1: campos directos
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

  // Caso 2: derivado de items
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
import {
  Loader2,
  MapPin,
  Ticket,
  Search,
  ChevronLeft,
  CreditCard,
  CheckCircle2,
  User,
  Share2,
  Calendar,
  Info,
  Plus,
  Users,
  ShoppingCart,
  Edit3,
  DollarSign,
  Smartphone,
  QrCode,
  Download,
  Wallet,
  Instagram,
  Twitter,
  ShieldCheck,
  Image as ImageIcon,
  PlusCircle,
  Minus,
  Trash2,
	  Check,
  X,
  Save,
  Mail,
  RefreshCw,
} from "lucide-react";

// --- ESTILOS CONSTANTES ---
const UI = {
  bg: "bg-[#050508]",
  card: "bg-neutral-900/40 border border-white/5 backdrop-blur-md",
  button:
    "bg-indigo-600 hover:bg-indigo-500 transition-all duration-300 shadow-[0_0_20px_rgba(79,70,229,0.3)]",
  buttonGhost:
    "bg-white/5 hover:bg-white/10 transition-all duration-300 border border-white/10",
};


// --- HELPERS RESPONSIVE / PRECIO / IMÁGENES ---
function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined" ? window.innerWidth < breakpoint : false
  );
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < breakpoint);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [breakpoint]);
  return isMobile;
}

function minPositivePrice(items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const nums = items
    .map((it) => Number(it?.price))
    .filter((n) => Number.isFinite(n) && n > 0);
  if (!nums.length) return null;
  return Math.min(...nums);
}

function priceLabelForEvent(ev, formatMoneyFn) {
  const p = minPositivePrice(ev?.items);
  if (p == null) return "Consultar";
  return `Desde ${formatMoneyFn(p)} / Consultar`;
}

const FALLBACK_FLYER =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(`
  <svg xmlns='http://www.w3.org/2000/svg' width='1200' height='800'>
    <defs>
      <linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>
        <stop offset='0' stop-color='#0b0b12'/>
        <stop offset='0.55' stop-color='#141429'/>
        <stop offset='1' stop-color='#4f46e5'/>
      </linearGradient>
    </defs>
    <rect width='1200' height='800' fill='url(#g)'/>
    <circle cx='980' cy='260' r='160' fill='rgba(255,255,255,0.10)'/>
    <circle cx='820' cy='480' r='220' fill='rgba(255,255,255,0.06)'/>
    <text x='80' y='160' fill='rgba(255,255,255,0.78)' font-size='54' font-family='Inter,Arial' font-weight='900'>TICKETERA</text>
    <text x='80' y='225' fill='rgba(255,255,255,0.90)' font-size='86' font-family='Inter,Arial' font-weight='900'>TicketPro</text>
    <text x='80' y='315' fill='rgba(255,255,255,0.55)' font-size='22' font-family='Inter,Arial' font-weight='700'>EVENTO · IMAGEN NO DISPONIBLE</text>
  </svg>
`);

function flyerSrc(ev) {
  return ev?.flyer_url || ev?.hero_bg || ev?.image_url || FALLBACK_FLYER;
}
// Helper: safely read JSON (or fallback to text) from a fetch Response
async function readJsonOrText(response) {
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



// -------------------------
// QR helpers (sin dependencias)
// Usa un servicio público para renderizar QR (image), y permite descargar.
// -------------------------
const qrImgUrl = (payload, size = 220) => {
  const s = Math.max(120, Math.min(600, Number(size) || 220));
  const enc = encodeURIComponent(payload || "");
  // qrserver es simple y soporta PNG
  return `https://api.qrserver.com/v1/create-qr-code/?size=${s}x${s}&data=${enc}`;
};

const downloadQrPng = async (payload, filename = "qr.png", size = 420) => {
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

// PDF rápido (para test): abre una ventana imprimible con los QRs y permite "Guardar como PDF".
// No requiere dependencias. "config" permite ajustar tamaño/estilo.
const openPrintableTicketsPdf = ({ title = "Mis Tickets", holder = "", tickets = [], config = {} }) => {
  const size = Math.max(180, Math.min(520, Number(config.qrSize) || 320));
  const cols = Number(config.cols) === 2 ? 2 : 1;

  const rowsHtml = (tickets || [])
    .map((t, i) => {
      const payload = (t.qr_payload || t.ticket_id || t.id || "").toString();
      const label = (t.label || t.title || `Ticket #${i + 1}`).toString();
      const eventTitle = (t.event_title || t.title || "").toString();
      const venue = (t.venue || "").toString();
      const city = (t.city || "").toString();
      const date = (t.date_text || "").toString();
      const img = payload ? qrImgUrl(payload, size) : "";
      return `
        <div class="card">
          <div class="qrwrap">
            ${img ? `<img src="${img}" alt="QR" />` : `<div class="noqr">SIN QR</div>`}
          </div>
          <div class="meta">
            <div class="label">${escapeHtml(label)}</div>
            ${eventTitle ? `<div class="event">${escapeHtml(eventTitle)}</div>` : ""}
            <div class="sub">${escapeHtml([date, venue, city].filter(Boolean).join(" · "))}</div>
            <div class="mono">${escapeHtml(payload)}</div>
          </div>
        </div>
      `;
    })
    .join("");

  const html = `
  <!doctype html>
  <html>
    <head>
      <meta charset="utf-8" />
      <title>${escapeHtml(title)}</title>
      <style>
        *{ box-sizing:border-box; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; }
        body{ margin:24px; color:#0b0b10; }
        h1{ margin:0 0 6px 0; font-size:18px; }
        .holder{ margin:0 0 18px 0; color:#444; font-size:12px; }
        .grid{ display:grid; grid-template-columns: repeat(${cols}, minmax(0, 1fr)); gap:16px; }
        .card{ border:1px solid #ddd; border-radius:16px; padding:12px; display:flex; gap:12px; align-items:center; }
        .qrwrap{ width:${size+12}px; height:${size+12}px; background:#fff; border:1px solid #eee; border-radius:14px; padding:6px; display:flex; align-items:center; justify-content:center; }
        .qrwrap img{ width:100%; height:100%; object-fit:contain; }
        .noqr{ font-size:12px; color:#666; font-weight:700; }
        .meta{ flex:1; min-width:0; }
        .label{ font-weight:900; font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:#111; }
        .event{ margin-top:4px; font-weight:800; font-size:14px; }
        .sub{ margin-top:4px; color:#555; font-size:12px; }
        .mono{ margin-top:8px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; font-size:10px; color:#333; word-break:break-all; }
        @media print{
          body{ margin:10mm; }
          .card{ break-inside: avoid; }
        }
      </style>
    </head>
    <body>
      <h1>${escapeHtml(title)}</h1>
      ${holder ? `<div class="holder">Titular: <b>${escapeHtml(holder)}</b></div>` : ""}
      <div class="grid">${rowsHtml}</div>
      <script>window.onload = () => setTimeout(() => window.print(), 200);</script>
    </body>
  </html>
  `;

  const w = window.open("", "_blank", "noopener,noreferrer");
  if (!w) {
    alert("No pude abrir la ventana de PDF (popup bloqueado).");
    return;
  }
  w.document.open();
  w.document.write(html);
  w.document.close();
};

const escapeHtml = (s) =>
  String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");



function FeaturedCarousel({ events = [], onOpen, formatMoneyFn }) {
  const scrollerRef = React.useRef(null);
  const wrapRef = React.useRef(null);
  const [active, setActive] = useState(0);

  const items = (events || []).slice(0, 8);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;

    const onScroll = () => {
      const first = scroller.querySelector("[data-card='1']");
      const cardW = first ? first.getBoundingClientRect().width : 1;
      const style = window.getComputedStyle(scroller);
      const gap = parseFloat(style.columnGap || style.gap || "0") || 0;
      const idx = Math.round(scroller.scrollLeft / (cardW + gap));
      setActive(Math.max(0, Math.min(idx, items.length - 1)));
    };

    scroller.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => scroller.removeEventListener("scroll", onScroll);
  }, [items.length]);

  const jumpTo = (i) => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const first = scroller.querySelector("[data-card='1']");
    const cardW = first ? first.getBoundingClientRect().width : 0;
    const style = window.getComputedStyle(scroller);
    const gap = parseFloat(style.columnGap || style.gap || "0") || 0;
    scroller.scrollTo({ left: i * (cardW + gap), behavior: "smooth" });
  };

  // ancho real del contenedor (evita overflow de 100vw)
  const [wrapW, setWrapW] = useState(0);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWrapW(el.clientWidth || 0));
    ro.observe(el);
    setWrapW(el.clientWidth || 0);
    return () => ro.disconnect();
  }, []);

  const peek = 56; // cuánto se ve de la próxima card
  const side = 16; // padding lateral
  const cardWidth = wrapW ? Math.max(220, Math.min(520, wrapW - side * 2 - peek)) : 320;

  if (!items.length) return null;

  return (
    <div ref={wrapRef} className="w-full">
      <div
        ref={scrollerRef}
        className="no-scrollbar flex w-full gap-4 overflow-x-auto overflow-y-hidden px-4 pb-3"
        style={{
          scrollSnapType: "x mandatory",
          WebkitOverflowScrolling: "touch",
          overscrollBehaviorX: "contain",
        }}
      >
        {items.map((ev, idx) => (
          <button
            key={ev.id || ev.slug || idx}
            data-card={idx === 0 ? "1" : "0"}
            onClick={() => onOpen?.(ev)}
            className={`shrink-0 text-left rounded-[2.25rem] ${UI.card} overflow-hidden`}
            style={{
              width: cardWidth,
              scrollSnapAlign: "start",
            }}
          >
            <div className="relative h-40">
              <img
                src={flyerSrc(ev)}
                onError={(e) => {
                  e.currentTarget.onerror = null;
                  e.currentTarget.src = FALLBACK_FLYER;
                }}
                alt={ev.title}
                className="w-full h-full object-cover opacity-90"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />
              <div className="absolute bottom-0 left-0 p-4">
                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-300">
                  {ev.category} · {ev.city}
                </div>
                <div className="text-lg font-black uppercase italic mt-1 line-clamp-1">
                  {ev.title}
                </div>
                <div className="text-[11px] text-neutral-300 mt-2 flex items-center gap-2">
                  <Calendar size={14} /> {ev.date_text}
                </div>
              </div>
            </div>
            <div className="p-4 flex items-center justify-between">
              <div>
                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                  Desde
                </div>
                <div className="text-base font-black text-indigo-300 italic">
                  {priceLabelForEvent(ev, formatMoneyFn)}
                </div>
              </div>
              <div className="text-right">
                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                  Stock
                </div>
                <div className="text-[11px] font-black">
                  {(ev.stock_total || 0) - (ev.stock_sold || 0)} / {ev.stock_total || 0}
                </div>
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* dots (solo mobile) */}
      <div className="md:hidden flex items-center justify-center gap-2 pb-2">
        {items.map((_, i) => (
          <button
            key={i}
            onClick={() => jumpTo(i)}
            className={`h-2 rounded-full transition-all ${
              i === active ? "w-6 bg-white/80" : "w-2 bg-white/25"
            }`}
            aria-label={`Ir a destacado ${i + 1}`}
          />
        ))}
      </div>
    </div>
  );
}


// -------------------------
// Helpers (demo / placeholders)
// -------------------------
const formatMoney = (n) => {
  const v = Number(n || 0);
  return `$${v.toLocaleString()}`;
};

const buildUberLink = (ev) => {
  if (!ev) return null;
  const lat = ev.lat ?? ev.latitude;
  const lng = ev.lng ?? ev.longitude;

  // Si no tenemos coords, intentamos con dirección/venue (demo-friendly).
  const addressGuess = (ev.address || "")
    || [ev.venue, ev.city].filter(Boolean).join(", ")
    || "";

  // Deep link oficial (web/mobile). Pickup se define por el usuario en la app.
  const params = new URLSearchParams({ action: "setPickup" });
  if (lat != null && lng != null) {
    params.set("dropoff[latitude]", String(lat));
    params.set("dropoff[longitude]", String(lng));
  }

  params.set("dropoff[nickname]", ev.title || "Evento");
  if (addressGuess) {
    // Uber acepta diferentes variantes según plataforma; dejamos ambas para máxima compat.
    params.set("dropoff[formatted_address]", addressGuess);
    params.set("dropoff[address]", addressGuess);
  }

  // Si no hay ni coords ni dirección, no mostramos.
  if (lat == null || lng == null) {
    if (!addressGuess) return null;
  }

  return `https://m.uber.com/ul/?${params.toString()}`;
};

const Footer = () => {
  return (
    <footer className="w-full border-t border-white/5 py-10 px-6 text-center text-neutral-500 text-[10px] font-black uppercase tracking-widest">
      Ticketera · Powered by <span className="text-white/70">TicketPro</span>
    </footer>
  );
};

const GoogleLoginModal = ({ open, onClose, onLoggedIn, googleClientId }) => {
  const [ready, setReady] = React.useState(false);

  useEffect(() => {
    if (!open) return;

    // Cargar Google Identity Services
    const ensureScript = () =>
      new Promise((resolve, reject) => {
        if (window.google?.accounts?.id) return resolve();
        const id = "google-identity-script";
        if (document.getElementById(id)) return resolve();
        const s = document.createElement("script");
        s.id = id;
        s.src = "https://accounts.google.com/gsi/client";
        s.async = true;
        s.defer = true;
        s.onload = () => resolve();
        s.onerror = () => reject(new Error("No se pudo cargar Google"));
        document.head.appendChild(s);
      });

    (async () => {
      try {
        await ensureScript();
        setReady(true);
        // Render button si hay client_id
        if (googleClientId && window.google?.accounts?.id) {
          window.google.accounts.id.initialize({
            client_id: googleClientId,
            callback: async (resp) => {
              try {
                const r = await fetch("/api/auth/google", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  credentials: "include",
                  body: JSON.stringify({ credential: resp.credential }),
                });
                const data = await readJsonOrText(r);
                if (!r.ok) throw new Error((data && data.detail) || "Login falló");

                // Algunos backends setean la cookie aunque no devuelvan {ok:true}
                let u = (data && data.user) ? data.user : (data || {});
                if (!u || (!u.email && !u.name && !u.meaningful_name)) {
                  try {
                    const meR = await fetch("/api/auth/me", { credentials: "include" });
                    if (meR.ok) {
                      const me = await meR.json();
                      u = (me && me.user) ? me.user : (me || u);
                    }
                  } catch {}
                }

                onLoggedIn({
                  fullName: u?.name || u?.meaningful_name || "User",
                  email: u?.email || "",
                  picture: u?.picture || "",
                  sub: u?.sub,
                });
              } catch (e) {
                console.error(e);
                alert("No se pudo iniciar sesión con Google.");
              }
            },
          });

          const el = document.getElementById("googleBtn");
          if (el) {
            el.innerHTML = "";
            window.google.accounts.id.renderButton(el, {
              theme: "outline",
              size: "large",
              shape: "pill",
              text: "continue_with",
              width: 340,
            });
          }
        }
      } catch (e) {
        console.error(e);
        setReady(false);
      }
    })();
  }, [open, googleClientId]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] bg-black/80 backdrop-blur-sm flex items-center justify-center p-6">
      <div className={`w-full max-w-md p-8 rounded-[2.5rem] ${UI.card} text-white`}>
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
              Login requerido
            </div>
            <div className="text-2xl font-black uppercase italic">Ingresar</div>
            <div className="text-[11px] text-neutral-400 mt-2">
              Iniciá sesión para comprar o gestionar eventos.
            </div>
          </div>
          <button onClick={onClose} className="p-2 rounded-2xl hover:bg-white/5 transition-all">
            <X />
          </button>
        </div>

        <div className="space-y-4">
          <div className="w-full flex justify-center">
            <div id="googleBtn" className="min-h-[44px]" />
          </div>

          {!googleClientId && (
            <div className="text-[11px] text-neutral-400 text-center">
              Falta configurar <span className="text-white/90 font-bold">GOOGLE_CLIENT_ID</span> en el backend.
            </div>
          )}

          

          <button
            onClick={onClose}
            className="w-full py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
          >
            Cancelar
          </button>
        </div>

        
      </div>
    </div>
  );
};

// -------------------------
// Editor modal (demo)
// -------------------------
const EditorModal = ({
  editFormData,
  setEditFormData,
  activeTab,
  setActiveTab,
  setIsEditing,
  saveEvent,
}) => {
  if (!editFormData) return null;

  const slugLocked = !editFormData?._is_new;

  const onClose = () => {
    setIsEditing(false);
    setEditFormData(null);
  };
  // --- Tickets (sale-items) & Sellers helpers ---
  const tenantId = editFormData?.tenant_id || "default";
  // Para evento nuevo, el slug NO se considera válido hasta que el backend lo persista.
  const eventSlug = editFormData?._is_new ? "" : (editFormData?.slug || "");

  const [saleItems, setSaleItems] = useState([]);
  const [sellers, setSellers] = useState([]);

  // Draft para crear "sale items".
  // Nota: el backend deduplica por (tenant, event_slug, kind, name), así que
  // conviene manejar bien el "kind" desde el front.
  const [saleDraft, setSaleDraft] = useState({
    kind: "ticket", // ticket | add_on | other (por ahora usamos ticket)
    name: "",
    price: "", // pesos (UI) -> se convierte en cents en backend
    currency: "ARS",
    stock_total: "",
    sort_order: "",
  });

  const [sellerDraft, setSellerDraft] = useState({
    code: "",
    name: "",
    // Algunos endpoints validan que el vendedor acepte términos.
    // Si el backend no lo usa, lo ignora; si lo usa, evita el 400 'terms_required'.
    accept_terms: true,
  });

	  // --- Aliases defensivos (histórico): algunas partes del wizard
	  // referenciaban `eventItemDraft` / `eventItems`.
	  // Mantenerlos evita crashes por refactors.
	  const eventItemDraft = saleDraft;
	  const setEventItemDraft = setSaleDraft;
	  const eventItems = saleItems;
	  const setEventItems = setSaleItems;
	  // alias alternativo (por si quedó algún uso viejo)
	  const salesItems = saleItems;

  const [tabBusy, setTabBusy] = useState(false);
  const [tabError, setTabError] = useState("");

  // -------------------------
  // Wizard (solo para evento nuevo)
  // -------------------------
  const isNewEvent = !!editFormData?._is_new;

  const [wizardStep, setWizardStep] = useState(0); // 0..4
  const [wizardTouched, setWizardTouched] = useState(false);
  const [flyerPreview, setFlyerPreview] = useState("");

  // Resetea wizard cuando cambia el evento
  useEffect(() => {
    if (isNewEvent) {
      setWizardStep(0);
      setWizardTouched(false);
      setFlyerPreview(editFormData?.flyer_url || "");
      // Asegura default de términos visible desde el paso 1
      if (typeof editFormData?.accept_terms === "undefined") {
        setEditFormData((p) => ({ ...p, accept_terms: false }));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editFormData?.id, editFormData?._is_new]);

  const clamp = (n, a, b) => Math.max(a, Math.min(b, n));

  const formatDateText = (dateISO, timeStr) => {
    if (!dateISO) return "";
    // dateISO: YYYY-MM-DD ; timeStr: HH:MM
    const t = (timeStr || "00:00").padStart(5, "0");
    return `${dateISO} ${t}`;
  };

  const mapEmbedUrl = (lat, lng) => {
    const la = Number(lat);
    const ln = Number(lng);
    if (!Number.isFinite(la) || !Number.isFinite(ln)) return "";
    const delta = 0.01; // ~1km (aprox)
    const left = ln - delta;
    const right = ln + delta;
    const top = la + delta;
    const bottom = la - delta;
    // OpenStreetMap embed
    const bbox = `${left}%2C${bottom}%2C${right}%2C${top}`;
    const marker = `${la}%2C${ln}`;
    return `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${marker}`;
  };

  const stepTitles = [
    "EVENTO",
    "UBICACIÓN Y FLYER",
    "TICKETS Y VENDEDORES",
    "CONFIRMACIÓN",
  ];
  const stepSubtitle = [
    "Nombre, slug, fecha/hora, cobro y términos",
    "Flyer con preview + ubicación en mapa",
    "Carga inicial de tickets y vendedores",
    "Revisá y confirmá",
  ];

  const getStepErrors = (step) => {
    const e = [];
    const title = String(editFormData?.title || "").trim();
    const slug = String(editFormData?.slug || "").trim();

    const date = String(editFormData?.start_date || "").trim();
    const time = String(editFormData?.start_time || "").trim();

    const payout = String(editFormData?.payout_alias || "").trim();
    const cuit = String(editFormData?.cuit || "").trim();

    const city = String(editFormData?.city || "").trim();
    const venue = String(editFormData?.venue || "").trim();
    const address = String(editFormData?.address || "").trim();
    const lat = editFormData?.lat;
    const lng = editFormData?.lng;

    if (step === 0) {
      if (!title) e.push("Falta el nombre del evento.");
      if (!slug) e.push("Falta el slug (URL corta).");
      if (!date) e.push("Falta la fecha.");
      if (!time) e.push("Falta el horario.");
      if (!payout) e.push("Falta el alias de cobro (CBU/alias/MercadoPago).");
      if (!cuit) e.push("Falta el CUIT.");

      // Venue/ubicación/flyer forman parte del alta (para evitar pasos mezclados)
      if (!city) e.push("Falta la ciudad.");
      if (!venue) e.push("Falta el venue/lugar.");
      if (!address) e.push("Falta la dirección.");
      if (!Number.isFinite(Number(lat))) e.push("Falta la latitud.");
      if (!Number.isFinite(Number(lng))) e.push("Falta la longitud.");

	      // El checkbox del paso 1 usa `accept_terms` (no `accepted_terms`)
	      if (!editFormData?.accept_terms) e.push("Tenés que aceptar Términos y Condiciones.");
    }

    if (step === 1) {
      // Paso desactivado: ahora Venue/ubicación se completa en el paso 1 (alta)
      return [];
    }


    return e;
  };

  const canGoNext = () => getStepErrors(wizardStep).length === 0;

  const onWizardNext = async () => {
    setWizardTouched(true);
    const errs = getStepErrors(wizardStep);
    if (errs.length) return;

    // ✅ Alta: creamos el evento (borrador) y saltamos directo al editor en "Tickets"
    // Esto evita mezclar pasos (crear vs editar).
    if (wizardStep === 0 && editFormData?._is_new) {
      // borrador: no finaliza/publica (solo asegura existencia del evento)
      const ok = await saveEvent(false, false);
      if (!ok) return;

      // Al guardar, el backend puede normalizar el slug. `saveEvent` ya actualiza editFormData y _is_new=false.
      // Forzamos que el editor arranque en la pestaña de tickets.
      setTimeout(() => setActiveTab("tickets"), 0);
      setWizardTouched(false);
      return;
    }

    // fallback (no debería ocurrir en alta)
    setWizardStep((s) => clamp(s + 1, 0, 3));
    setWizardTouched(false);
  };

  const onWizardBack = () => {
    setWizardStep((s) => clamp(s - 1, 0, 3));
    setWizardTouched(false);
  };

  const onPickFlyerFile = (file) => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    setFlyerPreview(url);
    // Guardamos la URL local para la preview (demo). En prod esto se sube a backend/storage.
    setEditFormData((p) => ({ ...p, flyer_url: url }));
  };

  const onUseMyLocation = () => {
    if (!navigator?.geolocation) {
      alert("Tu navegador no permite geolocalización.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const la = pos.coords.latitude;
        const ln = pos.coords.longitude;
        setEditFormData((p) => ({ ...p, lat: String(la), lng: String(ln) }));
      },
      () => alert("No se pudo obtener tu ubicación (permiso denegado o sin señal)."),
      { enableHighAccuracy: true, timeout: 8000 }
    );
  };

  const fetchJson = async (url, opts = {}) => {
    const res = await fetch(url, { credentials: "include", ...opts });
    const data = await readJsonOrText(res);
    if (!res.ok) {
      const detail = data && data.detail;
      const msg =
        (typeof detail === "string"
          ? detail
          : detail
          ? JSON.stringify(detail)
          : null) ||
        (typeof data === "string" ? data : JSON.stringify(data));

      // Mensajes humanos para los errores más frecuentes del MVP
      const m = String(msg || "");
      if (m === "terms_required") {
        throw new Error(
          "El backend pide términos aceptados/definidos para este evento. Entrá a INFO, tildá Aceptar términos y GUARDÁ (DEMO), y luego volvé a crear el vendedor."
        );
      }
      if (m.includes("duplicate key") || m.includes("unique")) {
        throw new Error("Ya existe un registro con esos datos (duplicado).");
      }

      throw new Error(msg || `HTTP ${res.status}`);
    }
    return data;
  };

  // -------------------------
  // Price helpers (single source of truth in UI)
  // -------------------------
  const getPriceCents = (it) => {
    if (!it) return 0;
    // canonical
    if (it.price_cents != null && it.price_cents !== "") return parseInt(String(it.price_cents), 10) || 0;
    // camelCase compat
    if (it.priceCents != null && it.priceCents !== "") return parseInt(String(it.priceCents), 10) || 0;
    // pesos float compat
    if (it.price != null && it.price !== "") {
      const p = Number(it.price);
      if (Number.isFinite(p)) return Math.round(p * 100);
    }
    return 0;
  };

  const formatARS = (cents) => {
    const value = (Number(cents) || 0) / 100;
    try {
      return new Intl.NumberFormat("es-AR", { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(value);
    } catch {
      return String(value);
    }
  };

  const priceLabel = (it) => {
    if (!it) return "0";
    if (it.price_display) return String(it.price_display).replace(/^\$\s?/, "");
    const cents = getPriceCents(it);
    return formatARS(cents);
  };



  const loadSaleItems = async () => {
    if (!eventSlug) return;
    setTabBusy(true);
    setTabError("");
    try {
      const qs = new URLSearchParams({
        tenant_id: tenantId,
        event_slug: eventSlug,
      });
      const data = await fetchJson(`/api/producer/sale-items?${qs.toString()}`);
      setSaleItems(data?.items || data || []);
    } catch (e) {
      setTabError(String(e.message || e));
    } finally {
      setTabBusy(false);
    }
  };

  const loadSellers = async () => {
    if (!eventSlug) return;
    setTabBusy(true);
    setTabError("");
    try {
      const qs = new URLSearchParams({
        tenant_id: tenantId,
        event_slug: eventSlug,
      });
      const data = await fetchJson(`/api/producer/sellers?${qs.toString()}`);
      const list =
        Array.isArray(data) ? data :
        Array.isArray(data?.items) ? data.items :
        Array.isArray(data?.rows) ? data.rows :
        [];
      setSellers(list);
    } catch (e) {
      setTabError(String(e.message || e));
    } finally {
      setTabBusy(false);
    }
  };

  useEffect(() => {
    if (!eventSlug) return;
    if (activeTab === "tickets") loadSaleItems();
    if (activeTab === "sellers") loadSellers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, eventSlug, tenantId]);

  const createSaleItem = async () => {
    if (!eventSlug) return;
    if (tabBusy) return; // evita doble click / doble POST
    setTabBusy(true);
    setTabError("");
    try {
      const name = (saleDraft.name || "").trim();
      const price = Number(saleDraft.price);
      const sort = Number.isFinite(Number(saleDraft.sort_order))
        ? parseInt(String(saleDraft.sort_order), 10)
        : 0;

      if (!name) {
        setTabError("El nombre del ticket no puede estar vacío.");
        return;
      }
      if (!Number.isFinite(price)) {
        setTabError("El precio debe ser un número válido.");
        return;
      }

      // Evitar duplicados (la DB tiene unique por tenant+event+kind+name)
      const exists = (saleItems || []).some((it) => {
        const itName = String(it?.name || "").trim().toLowerCase();
        return itName === name.toLowerCase();
      });
      if (exists) {
        setTabError(`Ya existe un ticket llamado "${name}".`);
        return;
      }

      const payload = {
        tenant_id: tenantId,
        event_slug: eventSlug,
        kind: saleDraft.kind || "ticket",
        name,
        price: Math.round(price * 100) / 100, // compat (pesos)
        price_cents: Math.round(price * 100), // canon
        currency: saleDraft.currency || "ARS",
        stock_total: saleDraft.stock_total === "" ? null : Number(saleDraft.stock_total),
        sort_order: Number.isFinite(sort) ? sort : 0,
      };

      const qsCreate = new URLSearchParams({ tenant_id: tenantId, event_slug: eventSlug });

      await fetchJson(`/api/producer/sale-items/create?${qsCreate.toString()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      setSaleDraft({ kind: "ticket", name: "", price: 10, currency: "ARS", stock_total: "", sort_order: 1 });
      await loadSaleItems();
    } catch (e) {
      const msg = String(e?.message || e || "");

      // Si el evento aún no está persistido en backend durante el wizard,
      // el backend puede responder 403 {detail:"forbidden_event"}. No lo
      // tratamos como fatal: guardamos el ticket localmente para seguir.
      if (msg === "forbidden_event") {
        const local = {
          tenant_id: tenantId,
          event_slug: eventSlug,
          kind: saleDraft?.kind || "ticket",
          name: String(saleDraft?.name || "").trim(),
          currency: saleDraft?.currency || "ARS",
          price: Number(saleDraft?.price ?? 0),
          price_cents: Math.round(Number(saleDraft?.price ?? 0) * 100),
          stock_total: Number(saleDraft?.stock_total ?? 0),
          sort_order: Number(saleDraft?.sort_order ?? 0),
          active: true,
        };

        setSaleItems((prev) => [
          ...prev,
          {
            id: `local-${Date.now()}`,
            ...local,
            _localOnly: true,
          },
        ]);
        setSaleDraft({ kind: "ticket", name: "", price: 10, currency: "ARS", stock_total: "", sort_order: 1 });
        // aviso suave (sin bloquear)
        setTabError("(Demo) Ticket guardado localmente. Se sincronizará al crear el evento.");
      } else if (msg.includes("duplicate key") || msg.includes("ux_sale_items")) {
        setTabError("Ese ticket ya existe para este evento (nombre duplicado).");
      } else {
        setTabError(msg);
      }
    } finally {
      setTabBusy(false);
    }
  };

  const toggleSaleItem = async (id, active) => {
    setTabBusy(true);
    setTabError("");
    try {
      await fetchJson(`/api/producer/sale-items/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId,
          event_slug: eventSlug,
          id,
          active: !!active,
        }),
      });
      await loadSaleItems();
    } catch (e) {
      setTabError(String(e.message || e));
    } finally {
      setTabBusy(false);
    }
  };

  const createSeller = async () => {
    if (!eventSlug) return;
    if (tabBusy) return; // evita doble click / doble POST
    setTabBusy(true);
    setTabError("");
    try {
      const code = (sellerDraft.code || "").trim();
      const name = (sellerDraft.name || "").trim();

      if (!code || !name) {
        setTabError("Completá código y nombre del vendedor.");
        return;
      }

      // Evitar duplicados simples en UI
      const exists = (sellers || []).some((s) => {
        const sc = String(s?.code || "").trim().toLowerCase();
        return sc === code.toLowerCase();
      });
      if (exists) {
        setTabError(`Ya existe un vendedor con código "${code}".`);
        return;
      }

      // Algunos backends validan que el vendedor "aceptó" términos.
      // En Ticketera lo usamos como flag simple para destrabar el alta.
      const payload = {
        tenant_id: tenantId,
        event_slug: eventSlug,
        code,
        name,
        email: (sellerDraft.email || "").trim() || null,
        accept_terms: true,
      };

      await fetchJson(`/api/producer/sellers/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      setSellerDraft({ code: "", name: "", email: "", accept_terms: true });
      await loadSellers();
    } catch (e) {
	      const msg = String(e?.message || e || "");

	      // Si el evento todavía no existe en backend (wizard de creación),
	      // el backend responde 403 {detail:"forbidden_event"}. En ese caso
	      // guardamos el vendedor localmente para que el usuario pueda avanzar.
	      if (msg === "forbidden_event") {
	        const local = {
	          id: `local-${Date.now()}`,
	          tenant_id: tenantId,
	          event_slug: eventSlug,
	          code: (sellerDraft.code || "").trim(),
	          name: (sellerDraft.name || "").trim(),
	          email: (sellerDraft.email || "").trim() || null,
	          active: true,
	          _localOnly: true,
	        };
	        setSellers((prev) => [local, ...(Array.isArray(prev) ? prev : [])]);
	        setSellerDraft({ code: "", name: "", email: "", accept_terms: true });
	        setTabError("No se pudo guardar en servidor (demo). Quedó en borrador local.");
	        return;
	      }

	      if (msg.includes("duplicate key") || msg.includes("ux_sellers")) {
	        setTabError("Ese vendedor ya existe para este evento (código duplicado).");
	      } else {
	        setTabError(msg);
	      }
    } finally {
      setTabBusy(false);
    }
  };

  const toggleSeller = async (id, active) => {
    setTabBusy(true);
    setTabError("");
    try {
      await fetchJson(`/api/producer/sellers/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId,
          event_slug: eventSlug,
          id,
          active: !!active,
        }),
      });
      await loadSellers();
    } catch (e) {
      setTabError(String(e.message || e));
    } finally {
      setTabBusy(false);
    }
  };


  return (
    <div className="fixed inset-0 z-[100] bg-black/80 backdrop-blur-sm flex items-center justify-center p-6">
      <div className={`w-full max-w-4xl p-6 md:p-8 rounded-[2.5rem] ${UI.card} text-white max-h-[90vh] overflow-y-auto`}>
        <div className="flex items-start justify-between gap-4 mb-8">
          <div>
            <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
              Editor (demo)
            </div>
            <div className="text-3xl font-black uppercase italic">
              {editFormData?.title || "Nuevo Evento"}
            </div>
            <div className="text-[11px] text-neutral-400 mt-2">
              Este editor es UI demo. Luego se conecta a /api/producer/events y /api/producer/dashboard.
            </div>
          </div>
          <button onClick={onClose} className="p-2 rounded-2xl hover:bg-white/5 transition-all">
            <X />
          </button>
        </div>


        {isNewEvent ? (
          <div>
            {/* Stepper */}
            <div className="mb-6">
              {/* Mobile header */}
              <div className="md:hidden">
                <div className="flex items-center justify-between text-[11px] font-black uppercase tracking-widest text-white/70">
                  <span>{`Paso ${wizardStep + 1}/4`}</span>
                  <span className="text-white truncate max-w-[55%] text-right">{stepTitles[wizardStep]}</span>
                </div>
                <div className="mt-2 h-2 rounded-full bg-white/10 overflow-hidden border border-white/10">
                  <div className="h-full bg-indigo-600" style={{ width: `${((wizardStep + 1) / 4) * 100}%` }} />
                </div>
              </div>

              {/* Desktop pills */}
              <div className="hidden md:flex items-center justify-between gap-2">
                {stepTitles.map((t, i) => {
                  const active = i === wizardStep;
                  const done = i < wizardStep;
                  return (
                    <button
                      key={t}
                      onClick={() => setWizardStep(i)}
                      className={`flex-1 min-w-[140px] rounded-2xl px-4 py-3 border transition-all ${
                        active
                          ? "bg-white/10 border-white/15"
                          : "bg-white/5 border-white/10 hover:bg-white/8"
                      }`}
                      title={t}
                    >
                      <div className="flex items-center gap-3">
                        <div
                          className={`h-7 w-7 rounded-xl flex items-center justify-center text-[11px] font-black ${
                            active ? "bg-indigo-600 text-white" : done ? "bg-white/10 text-white" : "bg-white/5 text-white/60"
                          }`}
                        >
                          {done ? <Check className="h-4 w-4" /> : i + 1}
                        </div>
                        <div className="min-w-0">
                          <div className={`text-[10px] font-black uppercase tracking-widest ${active ? "text-white" : "text-white/60"}`}>
                            {t}
                          </div>
                          <div className="text-[11px] text-white/45 truncate">{stepSubtitle[i]}</div>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Errors */}
            {wizardTouched && getStepErrors(wizardStep).length > 0 && (
              <div className="mb-5 rounded-2xl border border-red-500/20 bg-red-500/10 p-4">
                <div className="text-xs font-black uppercase tracking-widest text-red-100 mb-2">Revisá esto</div>
                <ul className="text-sm text-red-100/90 list-disc pl-5 space-y-1">
                  {getStepErrors(wizardStep).map((e, idx) => (
                    <li key={idx}>{e}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Step content */}
            {wizardStep === 0 && (
              <div className="grid md:grid-cols-2 gap-4">
                <div className="md:col-span-2">
                  <label className="text-[11px] font-black uppercase tracking-widest text-neutral-500">
                    Nombre del evento
                  </label>
                  <input
                    value={editFormData.title}
                    onChange={(e) =>
                      setEditFormData((s) => {
                        const nextTitle = e.target.value;
                        // Slug controlado por el sistema: para eventos nuevos se deriva del título.
                        const nextSlug = s?._is_new ? slugify(nextTitle) : s?.slug;
                        return { ...s, title: nextTitle, slug: nextSlug ?? s?.slug };
                      })
                    }
                    className={`mt-2 w-full px-4 py-3 rounded-2xl ${UI.input}`}
                    placeholder="Nuevo Evento"
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="text-[11px] font-black uppercase tracking-widest text-neutral-500">
                    Slug (URL corta)
                  </label>
                  <input
                    value={editFormData.slug}
                    readOnly
                    disabled
                    className={`mt-2 w-full px-4 py-3 rounded-2xl ${UI.input}`}
                    placeholder="auto (derivado del título)"
                  />
                  <div className="mt-2 text-[11px] text-neutral-500">
                    Tip: solo letras, números y guiones. Esto se usa en el link del evento.
                  </div>
                </div>

                <div>
                  <label className="text-[11px] font-black uppercase tracking-widest text-neutral-500">
                    Fecha
                  </label>
                  <input
                    type="date"
                    value={editFormData.start_date || ""}
                    onChange={(e) =>
                      setEditFormData((s) => ({
                        ...s,
                        start_date: e.target.value,
                      }))
                    }
                    className={`mt-2 w-full px-4 py-3 rounded-2xl ${UI.input}`}
                  />
                </div>
                <div>
                  <label className="text-[11px] font-black uppercase tracking-widest text-neutral-500">
                    Horario
                  </label>
                  <input
                    type="time"
                    value={editFormData.start_time || ""}
                    onChange={(e) =>
                      setEditFormData((s) => ({
                        ...s,
                        start_time: e.target.value,
                      }))
                    }
                    className={`mt-2 w-full px-4 py-3 rounded-2xl ${UI.input}`}
                  />
                </div>

                <div>
                  <label className="text-[11px] font-black uppercase tracking-widest text-neutral-500">
                    Alias para el cobro
                  </label>
                  <input
                    value={editFormData.payout_alias || ""}
                    onChange={(e) =>
                      setEditFormData((s) => ({
                        ...s,
                        payout_alias: e.target.value,
                      }))
                    }
                    className={`mt-2 w-full px-4 py-3 rounded-2xl ${UI.input}`}
                    placeholder="alias / CBU / Mercado Pago"
                  />
                </div>

                <div>
                  <label className="text-[11px] font-black uppercase tracking-widest text-neutral-500">
                    CUIT
                  </label>
                  <input
                    value={editFormData.cuit || ""}
                    onChange={(e) =>
                      setEditFormData((s) => ({ ...s, cuit: e.target.value }))
                    }
                    className={`mt-2 w-full px-4 py-3 rounded-2xl ${UI.input}`}
                    placeholder="20-XXXXXXXX-X"
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="flex items-start gap-3 p-4 rounded-2xl border border-white/10 bg-white/5">
                    <input
                      type="checkbox"
                      checked={!!editFormData.accept_terms}
                      onChange={(e) =>
                        setEditFormData((s) => ({
                          ...s,
                          accept_terms: e.target.checked,
                        }))
                      }
                      className="mt-1"
                    />
                    <div className="min-w-0">
                      <div className="text-[12px] font-black">
                        Acepto Términos y Condiciones
                      </div>
                      <div className="text-[11px] text-neutral-400">
                        Sin esto, el backend suele contestar &quot;terms_required&quot;.{" "}
                        <a
                          href="#"
                          onClick={(ev) => {
                            ev.preventDefault();
                            alert("Términos: (placeholder) Podés linkear a una página real.");
                          }}
                          className="underline text-neutral-300 hover:text-white"
                        >
                          Ver términos
                        </a>
                      </div>
                    </div>
                  </label>
                </div>
              </div>
            )}

            {wizardStep === 0 && (
              <div className="space-y-6">
<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="text-sm font-semibold mb-2 flex items-center gap-2">
                    <ImageIcon className="h-4 w-4" />
                    Subir flyer
                  </div>
                  <input
                    type="file"
                    accept="image/*"
                    className="w-full text-sm"
                    onChange={(e) => onPickFlyerFile(e.target.files?.[0])}
                  />
                  <div className="text-[11px] text-white/45 mt-2">
                    Demo: la imagen se previsualiza localmente. Luego lo conectamos a upload real (S3/Cloudinary/Render disk).
                  </div>

                  <div className="mt-4">
                    <div className="text-white/60 mb-1 text-sm">o pegar URL de imagen</div>
                    <input
                      className="w-full rounded-xl bg-black/20 border border-white/10 px-3 py-3 text-sm"
                      value={editFormData.flyer_url || ""}
                      onChange={(e) => {
                        setFlyerPreview(e.target.value);
                        setEditFormData({ ...editFormData, flyer_url: e.target.value });
                      }}
                      placeholder="https://..."
                    />
                  </div>
                </div>
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="text-sm font-semibold mb-2">Preview</div>
      <div className="aspect-[16/9] w-full rounded-2xl overflow-hidden bg-black/30 border border-white/10 flex items-center justify-center">
        {flyerPreview || editFormData.flyer_url ? (
          <img
            src={flyerPreview || editFormData.flyer_url}
            alt="Flyer preview"
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="text-sm text-white/50">Sin flyer todavía</div>
        )}
      </div>
    </div>
  </div>

  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
    <label className="text-sm md:col-span-2">
      <div className="text-white/60 mb-1">Domicilio completo</div>
      <input
        value={editFormData.address || ""}
        onChange={(e) => setEditFormData((p) => ({ ...p, address: e.target.value }))}
        className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 outline-none focus:ring-2 focus:ring-white/20"
        placeholder="Ej: Av. San Martín 1234"
      />
    </label>
    <label className="text-sm">
      <div className="text-white/60 mb-1">Ciudad</div>
      <input
        value={editFormData.city}
        onChange={(e) => setEditFormData((p) => ({ ...p, city: e.target.value }))}
        className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 outline-none focus:ring-2 focus:ring-white/20"
        placeholder="Mendoza"
      />
    </label>
    <label className="text-sm">
      <div className="text-white/60 mb-1">Venue</div>
      <input
        value={editFormData.venue}
        onChange={(e) => setEditFormData((p) => ({ ...p, venue: e.target.value }))}
        className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 outline-none focus:ring-2 focus:ring-white/20"
        placeholder="Arena / Bar / Club"
      />
    </label>

    <label className="text-sm">
      <div className="text-white/60 mb-1">Lat</div>
      <input
        value={editFormData.lat}
        onChange={(e) => setEditFormData((p) => ({ ...p, lat: e.target.value }))}
        className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 outline-none focus:ring-2 focus:ring-white/20"
        placeholder="-32.8896"
      />
    </label>
    <label className="text-sm">
      <div className="text-white/60 mb-1">Lng</div>
      <input
        value={editFormData.lng}
        onChange={(e) => setEditFormData((p) => ({ ...p, lng: e.target.value }))}
        className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 outline-none focus:ring-2 focus:ring-white/20"
        placeholder="-68.8458"
      />
    </label>

    <div className="md:col-span-2 flex items-center justify-between gap-3">
      <button
        type="button"
        onClick={onUseMyLocation}
        className="px-4 py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest"
      >
        Usar mi ubicación
      </button>
      <div className="text-[11px] text-white/45">
        Si ya tenés el pin, copiate Lat/Lng desde Google Maps y pegalo acá.
      </div>
    </div>

    <div className="md:col-span-2 rounded-2xl overflow-hidden border border-white/10 bg-white/5">
      {mapEmbedUrl(editFormData.lat, editFormData.lng) ? (
        <iframe
          title="Mapa"
          className="w-full h-[280px] md:h-[320px]"
          src={mapEmbedUrl(editFormData.lat, editFormData.lng)}
        />
      ) : (
        <div className="h-[220px] flex items-center justify-center text-sm text-white/50">
          Ingresá lat/lng para ver el mapa.
        </div>
      )}
    </div>
  </div>
</div>

            )}

            {wizardStep === 2 && (
              <div className="grid md:grid-cols-2 gap-6">
                <div className="rounded-3xl border border-white/10 bg-white/5 p-5">
                  <div className="text-[11px] font-black uppercase tracking-widest text-white/70">
                    Sales items (tickets)
                  </div>
                  <div className="mt-4 grid gap-3">
                    <input
                      value={eventItemDraft.name}
                      onChange={(e) =>
                        setEventItemDraft((s) => ({ ...s, name: e.target.value }))
                      }
                      className={`w-full px-4 py-3 rounded-2xl ${UI.input}`}
                      placeholder="General, VIP..."
                    />
                    <div className="grid grid-cols-2 gap-3">
                      <input
                        value={eventItemDraft.price}
                        onChange={(e) =>
                          setEventItemDraft((s) => ({ ...s, price: e.target.value }))
                        }
                        className={`w-full px-4 py-3 rounded-2xl ${UI.input}`}
                        placeholder="Precio (ARS)"
                      />
                      <input
                        value={eventItemDraft.stock_total}
                        onChange={(e) =>
                          setEventItemDraft((s) => ({ ...s, stock_total: e.target.value }))
                        }
                        className={`w-full px-4 py-3 rounded-2xl ${UI.input}`}
                        placeholder="Stock"
                      />
                    </div>

                    <button
                      onClick={createSaleItem}
                      disabled={tabBusy}
                      className={`w-full px-4 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest ${UI.button}`}
                    >
                      <Plus className="h-4 w-4" /> Agregar ticket
                    </button>

                    <div className="mt-2 space-y-2">
                      {eventItems?.length ? (
                        eventItems.map((it) => (
                          <div
                            key={it.id || `${it.name}-${it.price}`}
                            className="flex items-center justify-between rounded-2xl bg-white/5 border border-white/10 px-4 py-3"
                          >
                            <div className="min-w-0">
                              <div className="text-[12px] font-black truncate">{it.name}</div>
                              <div className="text-[11px] text-white/50">
                                ${Number(it.price || 0).toLocaleString()} · stock {Number(it.stock_total || 0).toLocaleString()}
                              </div>
                            </div>
                            <button
                              onClick={() => deleteSaleItem(it)}
                              className="p-2 rounded-xl hover:bg-white/10 border border-white/10"
                              title="Eliminar"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        ))
                      ) : (
                        <div className="text-[11px] text-white/45">Todavía no cargaste tickets.</div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="rounded-3xl border border-white/10 bg-white/5 p-5">
                  <div className="text-[11px] font-black uppercase tracking-widest text-white/70">
                    Vendedores
                  </div>
                  <div className="mt-4 grid gap-3">
                    <input
                      value={sellerDraft.name}
                      onChange={(e) =>
                        setSellerDraft((s) => ({ ...s, name: e.target.value }))
                      }
                      className={`w-full px-4 py-3 rounded-2xl ${UI.input}`}
                      placeholder="Nombre del vendedor"
                    />
                    <input
                      value={sellerDraft.code}
                      onChange={(e) =>
                        setSellerDraft((s) => ({ ...s, code: e.target.value }))
                      }
                      className={`w-full px-4 py-3 rounded-2xl ${UI.input}`}
                      placeholder="Código (opcional)"
                    />

                    <button
                      onClick={createSeller}
                      disabled={tabBusy}
                      className={`w-full px-4 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest ${UI.button}`}
                    >
                      <Plus className="h-4 w-4" /> Agregar vendedor
                    </button>

                    <div className="mt-2 space-y-2">
                      {sellers?.length ? (
                        sellers.map((s) => (
                          <div
                            key={s.id || s.code || s.name}
                            className="flex items-center justify-between rounded-2xl bg-white/5 border border-white/10 px-4 py-3"
                          >
                            <div className="min-w-0">
                              <div className="text-[12px] font-black truncate">{s.name}</div>
                              <div className="text-[11px] text-white/50">{s.code || "sin código"}</div>
                            </div>
                            <button
                              onClick={() => deleteSeller(s)}
                              className="p-2 rounded-xl hover:bg-white/10 border border-white/10"
                              title="Eliminar"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        ))
                      ) : (
                        <div className="text-[11px] text-white/45">Todavía no cargaste vendedores.</div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="md:col-span-2 text-[11px] text-white/45">
                  Tip: si querés, podés dejar esto vacío y cargarlo después desde Gestión.
                </div>
              </div>
            )}

            {wizardStep === 3 && (
              <div className="space-y-4">
                <div className="rounded-3xl border border-white/10 bg-white/5 p-5">
                  <div className="text-[11px] font-black uppercase tracking-widest text-white/70">
                    Confirmación
                  </div>
                  <div className="mt-4 grid md:grid-cols-2 gap-3 text-[12px] text-white/70">
                    <div><span className="text-white/40">Evento:</span> {editFormData.title}</div>
                    <div><span className="text-white/40">Slug:</span> {editFormData.slug}</div>
                    <div><span className="text-white/40">Fecha:</span> {editFormData.start_date} {editFormData.start_time}</div>
                    <div><span className="text-white/40">Cobro:</span> {editFormData.payout_alias} · {editFormData.cuit}</div>
                    <div><span className="text-white/40">Ubicación:</span> {editFormData.city} · {editFormData.venue}</div>
                    <div><span className="text-white/40">Tickets:</span> {eventItems?.length || 0}</div>
                    <div><span className="text-white/40">Vendedores:</span> {sellers?.length || 0}</div>
                  </div>
                </div>

                <div className="rounded-3xl border border-white/10 bg-white/5 p-5">
                  <label className="text-[11px] font-black uppercase tracking-widest text-white/60">
                    Descripción (opcional)
                  </label>
                  <textarea
                    value={editFormData.description || ""}
                    onChange={(e) =>
                      setEditFormData((s) => ({ ...s, description: e.target.value }))
                    }
                    className={`mt-2 w-full px-4 py-3 rounded-2xl ${UI.input}`}
                    rows={4}
                    placeholder="Breve descripción del evento..."
                  />
                </div>
              </div>
            )}

            {/* Wizard footer */}
            <div className="mt-8 flex flex-col md:flex-row gap-3">
              <button
                type="button"
                onClick={wizardStep === 0 ? onClose : onWizardBack}
                className="flex-1 px-6 py-4 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-white font-black uppercase tracking-widest text-[10px]"
              >
                {wizardStep === 0 ? "Cancelar" : "Atrás"}
              </button>

              {wizardStep < 3 ? (
                <button
                  type="button"
                  onClick={onWizardNext}
                  className="flex-1 px-6 py-4 rounded-2xl bg-indigo-600 hover:bg-indigo-500 text-white font-black uppercase tracking-widest text-[10px]"
                >
                  Continuar
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    // valida todo el flujo antes de guardar
                    const all = [0, 1, 2, 3, 4].map((s) => ({ s, e: getStepErrors(s) }));
                    const firstBad = all.find((x) => x.e.length);
                    if (firstBad) {
                      setWizardStep(firstBad.s);
                      setWizardTouched(true);
                      return;
                    }
                    saveEvent();
                  }}
                  className="flex-1 px-6 py-4 rounded-2xl bg-indigo-600 hover:bg-indigo-500 text-white font-black uppercase tracking-widest text-[10px]"
                >
                  Crear evento (demo)
                </button>
              )}
            </div>
          </div>
        ) : (
          <>
            <div className="flex gap-2 mb-8">
              {[
                { id: "info", label: "Info" },
                { id: "tickets", label: "Tickets" },
                { id: "sellers", label: "Sellers" },
              ].map((t) => (
                <button
                  key={t.id}
                  onClick={() => setActiveTab(t.id)}
                  className={`px-5 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all ${
                    activeTab === t.id ? "bg-indigo-600 text-white" : "bg-white/5 hover:bg-white/10"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {activeTab === "info" && (
              <>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <label className="text-sm">
                    <div className="text-white/60 mb-1">Nombre</div>
                    <input
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                      value={editFormData.title || ""}
                      onChange={(e) => setEditFormData({ ...editFormData, title: e.target.value })}
                    />
                  </label>

                  <label className="text-sm">
                    <div className="text-white/60 mb-1">Slug</div>
                    <input
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                      value={editFormData.slug || ""}
                      disabled={slugLocked}
                      onChange={(e) => {
                        if (slugLocked) return;
                        setEditFormData({ ...editFormData, slug: e.target.value });
                      }}
                    />
                  </label>

                  <label className="text-sm">
                    <div className="text-white/60 mb-1">Fecha</div>
                    <input
                      type="text"
                      placeholder="Ej: Sáb, 01 de Enero (o 2026-02-03)"
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                      value={editFormData.date_text || ""}
                      onChange={(e) => setEditFormData({ ...editFormData, date_text: e.target.value })}
                    />
                  </label>

                  <label className="text-sm">
                    <div className="text-white/60 mb-1">Ciudad</div>
                    <input
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                      value={editFormData.city || ""}
                      onChange={(e) => setEditFormData({ ...editFormData, city: e.target.value })}
                    />
                  </label>
                  <label className="text-sm">
                    <div className="text-white/60 mb-1">Venue</div>
                    <input
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                      value={editFormData.venue || ""}
                      onChange={(e) => setEditFormData({ ...editFormData, venue: e.target.value })}
                    />
                  </label>

                  <label className="text-sm md:col-span-2">
                    <div className="text-white/60 mb-1">Flyer URL</div>
                    <input
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                      value={editFormData.flyer_url || ""}
                      onChange={(e) => setEditFormData({ ...editFormData, flyer_url: e.target.value })}
                    />
                  </label>

                  <label className="text-sm md:col-span-2">
                    <div className="text-white/60 mb-1">Descripción</div>
                    <textarea
                      rows={3}
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                      value={editFormData.description || ""}
                      onChange={(e) => setEditFormData({ ...editFormData, description: e.target.value })}
                    />
                  </label>
                </div>

                {!editFormData.accept_terms && (
                  <div className="mt-4 flex items-start gap-3 rounded-2xl border border-white/10 bg-white/5 p-4">
                  <input
                    type="checkbox"
                    className="mt-1 h-5 w-5 accent-indigo-500"
                    checked={!!editFormData.accept_terms}
                    onChange={(e) =>
                      setEditFormData((prev) => ({
                        ...prev,
                        accept_terms: e.target.checked,
                      }))
                    }
                  />
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-white">Acepto Términos y Condiciones</div>
                    <div className="text-xs text-white/70">
                      Es requisito para publicar / guardar el evento{" "}
                      <a
                        href="#"
                        onClick={(e) => {
                          e.preventDefault();
                          alert("Aún no hay página pública de Términos. (Podemos agregar /terms cuando quieras)");
                        }}
                        className="underline text-white/80 hover:text-white"
                      >
                        Ver términos
                      </a>
                    </div>
                  </div>
                </div>
                )}
              </>
            )}

            {(activeTab === "tickets" || activeTab === "sellers") && (
              <div className="mt-3">
                {!eventSlug ? (
                  <div className="text-sm text-amber-200/90 bg-amber-500/10 border border-amber-500/20 rounded-xl p-3">
                    Primero guardá el evento (necesitamos un <b>slug</b>) y después cargamos {activeTab === "tickets" ? "tickets" : "vendedores"}.
                  </div>
                ) : (
                  <>
                    {tabError && (
                      <div className="text-sm text-red-200 bg-red-500/10 border border-red-500/20 rounded-xl p-3 mb-3">
                        {tabError}
                      </div>
                    )}

                    {tabBusy && <div className="text-sm text-white/60 mb-3">Cargando…</div>}

                    {activeTab === "tickets" && (
                      <div className="space-y-4">
                        <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                          <div className="text-sm text-white/70 mb-2">Agregar ticket (sale item)</div>
                          <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
                            <input
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm md:col-span-2"
                              placeholder="Nombre (ej: General)"
                              value={saleDraft.name}
                              onChange={(e) => setSaleDraft({ ...saleDraft, name: e.target.value })}
                            />
                            <input
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                              placeholder="Precio (ej: 12000)"
                              value={saleDraft.price}
                              onChange={(e) => setSaleDraft({ ...saleDraft, price: e.target.value })}
                            />
                            <input
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                              placeholder="Stock (opcional)"
                              value={saleDraft.stock_total}
                              onChange={(e) => setSaleDraft({ ...saleDraft, stock_total: e.target.value })}
                            />
                            <button
                              className="rounded-xl bg-indigo-500/80 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold disabled:opacity-50"
                              disabled={tabBusy || !saleDraft.name.trim() || !String(saleDraft.price).trim()}
                              onClick={createSaleItem}
                            >
                              + Agregar
                            </button>
                          </div>
                          <div className="mt-2 text-xs text-white/45">Nota: el backend guarda el precio en <i>centavos</i> automáticamente.</div>
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                          <div className="flex items-center justify-between mb-2">
                            <div className="text-sm text-white/70">Tickets actuales</div>
                            <button
                              className="text-xs text-white/70 hover:text-white underline"
                              onClick={loadSaleItems}
                              disabled={tabBusy}
                            >
                              refrescar
                            </button>
                          </div>

                          {!saleItems || saleItems.length === 0 ? (
                            <div className="text-sm text-white/50">Todavía no hay tickets.</div>
                          ) : (
                            <div className="space-y-2">
                              {saleItems.map((it) => (
                                <div
                                  key={it.id}
                                  className="flex items-center justify-between gap-3 rounded-xl bg-black/20 border border-white/10 px-3 py-2"
                                >
                                  <div className="min-w-0">
                                    <div className="text-sm font-semibold truncate">{it.name}</div>
                                    <div className="text-xs text-white/55">
                                      {it.currency} ${(it.price_cents || 0) / 100} • stock {it.stock_total ?? "—"}
                                    </div>
                                  </div>
                                  <button
                                    className="text-xs text-white/70 hover:text-white underline"
                                    onClick={() => deleteSaleItem(it.id)}
                                    disabled={tabBusy}
                                  >
                                    eliminar
                                  </button>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {activeTab === "sellers" && (
                      <div className="space-y-4">
                        <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                          <div className="text-sm text-white/70 mb-2">Agregar seller</div>
                          <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
                            <input
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                              placeholder="Código (ej: BAR1)"
                              value={sellerDraft.code}
                              onChange={(e) => setSellerDraft({ ...sellerDraft, code: e.target.value })}
                            />
                            <input
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm md:col-span-2"
                              placeholder="Nombre (ej: Barra principal)"
                              value={sellerDraft.name}
                              onChange={(e) => setSellerDraft({ ...sellerDraft, name: e.target.value })}
                            />
                            <button
                              className="rounded-xl bg-indigo-500/80 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold disabled:opacity-50"
                              disabled={tabBusy || !sellerDraft.code.trim() || !sellerDraft.name.trim()}
                              onClick={createSeller}
                            >
                              + Agregar
                            </button>
                          </div>
                          <div className="mt-3 flex items-start gap-3 rounded-xl bg-black/20 border border-white/10 px-3 py-2">
                            <input
                              type="checkbox"
                              className="mt-1 h-4 w-4 accent-indigo-500"
                              checked={!!sellerDraft.accept_terms}
                              onChange={(e) => setSellerDraft({ ...sellerDraft, accept_terms: e.target.checked })}
                            />
                            <div className="text-xs text-white/60">
                              Incluir <b>accept_terms</b> evita el 400 <i>terms_required</i> en algunos backends.
                            </div>
                          </div>
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                          <div className="flex items-center justify-between mb-2">
                            <div className="text-sm text-white/70">Sellers actuales</div>
                            <button
                              className="text-xs text-white/70 hover:text-white underline"
                              onClick={loadSellers}
                              disabled={tabBusy}
                            >
                              refrescar
                            </button>
                          </div>

                          {!sellers || sellers.length === 0 ? (
                            <div className="text-sm text-white/50">Todavía no hay sellers.</div>
                          ) : (
                            <div className="space-y-2">
                              {sellers.map((s) => (
                                <div key={s.id} className="flex items-center justify-between gap-3 rounded-xl bg-black/20 border border-white/10 px-3 py-2">
                                  <div className="min-w-0">
                                    <div className="text-sm font-semibold truncate">{s.code} • {s.name}</div>
                                    <div className="text-xs text-white/55">id: {s.id}</div>
                                  </div>
                                  <label className="flex items-center gap-2 text-xs text-white/70">
                                    <input
                                      type="checkbox"
                                      checked={!!s.active}
                                      onChange={(e) => toggleSeller(s.id, e.target.checked)}
                                      disabled={tabBusy}
                                    />
                                    activo
                                  </label>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            <div className="mt-8 flex flex-col md:flex-row gap-3">
              <button
                onClick={saveEvent}
                className="flex-1 px-6 py-4 rounded-2xl bg-indigo-600 hover:bg-indigo-500 text-white font-black uppercase tracking-widest text-[10px]"
              >
                Guardar (demo)
              </button>
              <button
                onClick={onClose}
                className="flex-1 px-6 py-4 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-white font-black uppercase tracking-widest text-[10px]"
              >
                Volver
              </button>
            </div>
          </>
        )}
        </div>
      </div>
    
  );
}


// -------------------------
// App
// -------------------------
export default function App() {
  const [view, setView] = useState("public");

  // Filtros rápidos (solo cartelera)
  const [filterCity, setFilterCity] = useState("all");
  const [filterType, setFilterType] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [me, setMe] = useState(null);
  const [googleClientId, setGoogleClientId] = useState("");
  const [loginRequired, setLoginRequired] = useState(false);
  const [pendingCheckout, setPendingCheckout] = useState(null);
  const [showTermsModal, setShowTermsModal] = useState(false);

  // Mis Tickets (Entradas + Barra)
  const [myAssets, setMyAssets] = useState([]);
  const [myAssetsLoading, setMyAssetsLoading] = useState(false);
  const [myAssetsError, setMyAssetsError] = useState(null);
  const [myFilters, setMyFilters] = useState({ kind: "all", status: "all", when: "all", q: "" });
  const [qrCache, setQrCache] = useState({});

  // Config público (Google Client ID)
  useEffect(() => {
    fetch("/api/public/config")
      .then((r) => r.json())
      .then((cfg) => setGoogleClientId(cfg?.google_client_id || ""))
      .catch(() => setGoogleClientId(""));
  }, []);

  const refreshPublicEvents = async () => {
    try {
      const r = await fetch("/api/public/events?tenant=default", { credentials: "include" });
      const data = await readJsonOrText(r);
      if (r.ok && Array.isArray(data) && data.length) {
        setEvents(
          data.map((e) => ({
            id: e.id || e.slug,
            ...e,
            flyer_url: e.flyer_url || e.hero_bg,
          }))
        );
      }
    } catch (e) {
      // si falla, mantenemos demo events
      console.warn("No se pudieron cargar eventos del backend (demo).");
    }
  };

  useEffect(() => {
    refreshPublicEvents();
  }, []);

  const openPublicEvent = async (slug) => {
    try {
      setLoading(true);
      const r = await fetch(`/api/public/events/${encodeURIComponent(slug)}?tenant=default`, {
        credentials: "include",
      });
      const data = await readJsonOrText(r);
      if (r.ok && data) {
        // Compat: el detalle puede traer items embebidos, pero la vista pública usa endpoint dedicado.
        let items = data.items || [];
        try {
          const rItems = await fetch(
            `/api/public/sale-items?tenant=default&event_slug=${encodeURIComponent(slug)}`,
            { credentials: "include" }
          );
          const dItems = await readJsonOrText(rItems);
          if (rItems.ok && dItems) {
            // dItems puede venir como {items: [...]} o como [...]
            items = Array.isArray(dItems) ? dItems : dItems.items || items;
          }
        } catch (e) {
          console.warn("No pude cargar sale-items públicos:", e);
        }

        setSelectedEvent({
          id: data.id || data.slug,
          ...data,
          items,
          flyer_url: data.flyer_url || data.hero_bg,
        });
        setSelectedTicket((items || [])[0] || null);
        setView("detail");
        return;
      }
      alert("No se pudo abrir el evento (detalle).");
    } catch (e) {
      console.error(e);
      alert("Error abriendo evento: " + (e?.message || e));
    } finally {
      setLoading(false);
    }
  };



  const [loading, setLoading] = useState(false);
  const [purchaseData, setPurchaseData] = useState(null);
  const [activeTab, setActiveTab] = useState("info");

  const [events, setEvents] = useState([
    {
      id: 1,
      slug: "techno-genesis-2026",
      title: "Techno Genesis: Core",
      category: "Música",
      date_text: "Sáb, 15 de Marzo",
      venue: "Underground Stadium",
      city: "Mendoza",
      flyer_url:
        "https://images.unsplash.com/photo-1574391884720-bbe3740e581a?q=80&w=1974&auto=format&fit=crop",
      active: true,
      stock_total: 1000,
      stock_sold: 840,
      revenue: 12600000,
      items: [
        { id: 101, name: "General", price: 15000, stock: 800, sold: 700 },
        { id: 102, name: "VIP", price: 35000, stock: 200, sold: 140 },
      ],
      sellers: [{ id: 1, name: "Staff Central", code: "TPRO", sales: 45 }],
    },
  ]);

  // -------------------------
  // Producer analytics (real backend)
  // -------------------------
  const [tenantId] = useState("default");
  const [producerEvents, setProducerEvents] = useState([]); // [{ event_slug, orders_count, total_cents, bar_cents, tickets_cents }]
  const [producerEventsLoading, setProducerEventsLoading] = useState(false);
  const [producerEventsError, setProducerEventsError] = useState(null);

  const [selectedProducerEventSlug, setSelectedProducerEventSlug] = useState("");
  const [producerDashboard, setProducerDashboard] = useState(null); // { kpis, topCustomers, topProducts, timeSeries }
  const [producerDashboardLoading, setProducerDashboardLoading] = useState(false);
  const [producerDashboardError, setProducerDashboardError] = useState(null);

  const [selectedEvent, setSelectedEvent] = useState(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editFormData, setEditFormData] = useState(null);

  const [checkoutForm, setCheckoutForm] = useState({
    fullName: "",
    dni: "",
    address: "",
    acceptTerms: false,
  });

  const [checkoutTouched, setCheckoutTouched] = useState({
    fullName: false,
    dni: false,
    address: false,
    acceptTerms: false,
  });

  const checkoutErrors = useMemo(() => {
    const errors = {};
    const name = (checkoutForm.fullName || "").trim();
    const address = (checkoutForm.address || "").trim();
    const dni = String(checkoutForm.dni || "").replace(/\D/g, "");

    if (!name) errors.fullName = "Ingresá tu nombre y apellido.";
    if (!dni) errors.dni = "Ingresá tu DNI.";
    else if (dni.length < 7) errors.dni = "El DNI debe tener al menos 7 números.";
    if (!address) errors.address = "Ingresá tu domicilio completo.";
    if (!checkoutForm.acceptTerms)
      errors.acceptTerms = "Aceptá Términos y Condiciones para continuar.";

    return errors;
  }, [checkoutForm]);

  const hasCheckoutErrors = Object.keys(checkoutErrors).length > 0;
  const checkoutError = (key) => (checkoutTouched[key] ? checkoutErrors[key] : "");
const [selectedTicket, setSelectedTicket] = useState(null);
  const [quantity, setQuantity] = useState(1);

  
  const loadMyAssets = async () => {
    setMyAssetsLoading(true);
    setMyAssetsError(null);
    try {
      const r = await fetch(`/api/orders/my-assets?tenant=default`, { credentials: "include" });
      const data = await readJsonOrText(r);
      if (!r.ok || !data?.ok) throw new Error(data?.detail || "No se pudieron cargar tus tickets");
      setMyAssets(Array.isArray(data.assets) ? data.assets : []);
    } catch (e) {
      setMyAssets([]);
      setMyAssetsError(e?.message || "No se pudieron cargar tus tickets");
    } finally {
      setMyAssetsLoading(false);
    }
  };

  const requestCancel = async ({ kind, id, order_id, reason }) => {
    const r = await fetch(`/api/orders/cancel-request?tenant=default`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ kind, id, order_id, reason }),
    });
    const data = await readJsonOrText(r);
    if (!r.ok || !data?.ok) throw new Error(data?.detail || "No se pudo solicitar arrepentimiento");
    return data;
  };

  const transferOrder = async ({ order_id, to_email }) => {
    const r = await fetch(`/api/orders/transfer-order?tenant=default`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ order_id, to_email }),
    });
    const data = await readJsonOrText(r);
    if (!r.ok || !data?.ok) throw new Error(data?.detail || "No se pudo transferir la compra");
    return data;
  };

const refreshMe = async () => {
    try {
      const r = await fetch("/api/auth/me", { credentials: "include" });
      if (!r.ok) {
        setMe(null);
        return null;
      }
      const data = await readJsonOrText(r);
      setMe(data.user || null);
      return data.user || null;
    } catch {
      setMe(null);
      return null;
    }
  };

  useEffect(() => {
    refreshMe();
  }, []);

  const logout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {}
    setMe(null);
    // Limpia estado producer (evita eventos pegados del user anterior)
    setProducerEvents([]);
    setSelectedProducerEventSlug("");
    setProducerDashboard(null);
    setProducerEventsError(null);
    setProducerDashboardError(null);
  };

  const openLoginModal = (opts = null) => {
    setPendingCheckout(opts);
    setLoginRequired(true);
  };

  const closeLoginModal = () => {
    setLoginRequired(false);
    setPendingCheckout(null);
  };

  
  useEffect(() => {
    // Cuando cambia el productor logueado, reseteamos y (si corresponde) recargamos.
    setProducerEvents([]);
    setSelectedProducerEventSlug("");
    setProducerDashboard(null);
    setProducerEventsError(null);
    setProducerDashboardError(null);
    if (view === "producer" && me) {
      loadProducerEvents();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.producer, view]);

// -------------------------
  // Producer analytics loaders
  // -------------------------
  const fetchJson = async (url, options = {}) => {
    const r = await fetch(url, { credentials: "include", ...options });
    if (!r.ok) {
      const text = await r.text().catch(() => "");
      throw new Error(`HTTP ${r.status} ${r.statusText}${text ? ` — ${text}` : ""}`);
    }
    return r.json();
  };

  const loadProducerEvents = async () => {
    setProducerEventsLoading(true);
    setProducerEventsError(null);
    try {
      const data = await fetchJson(`/api/producer/events?tenant_id=${encodeURIComponent(tenantId)}`);
      const list = Array.isArray(data?.events) ? data.events : Array.isArray(data) ? data : [];
      setProducerEvents(list);

      // Auto-select first event with sales if none selected yet
      if (!selectedProducerEventSlug && list.length > 0) {
        const firstSlug = list[0]?.event_slug || list[0]?.eventSlug || list[0]?.slug;
        if (firstSlug) setSelectedProducerEventSlug(firstSlug);
      }
    } catch (e) {
      setProducerEventsError(e?.message || "No se pudo cargar la lista de eventos.");
      setProducerEvents([]);
    } finally {
      setProducerEventsLoading(false);
    }
  };

  const loadProducerDashboard = async (eventSlug) => {
    if (!eventSlug) return;
    setProducerDashboardLoading(true);
    setProducerDashboardError(null);
    try {
      const data = await fetchJson(
        `/api/producer/dashboard?tenant_id=${encodeURIComponent(tenantId)}&event_slug=${encodeURIComponent(eventSlug)}`
      );
      setProducerDashboard(data);
    } catch (e) {
      setProducerDashboardError(e?.message || "No se pudo cargar el dashboard.");
      setProducerDashboard(null);
    } finally {
      setProducerDashboardLoading(false);
    }
  };

  const refreshProducerAnalytics = async () => {
    await loadProducerEvents();
    const slug = selectedProducerEventSlug || producerEvents?.[0]?.event_slug;
    if (slug) await loadProducerDashboard(slug);
  };

  useEffect(() => {
    if (view === "producer") {
      loadProducerEvents();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  useEffect(() => {
    if (view === "producer" && selectedProducerEventSlug) {
      loadProducerDashboard(selectedProducerEventSlug);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, selectedProducerEventSlug]);

  const handleCheckout = async (method) => {
  // Validación visual (sin alerts)
  setCheckoutTouched({
    fullName: true,
    dni: true,
    address: true,
    acceptTerms: true,
  });

  if (!selectedTicket || hasCheckoutErrors) {
    return;
  }

  // login obligatorio en checkout
    if (!me) {
      openLoginModal({ method });
      return;
    }

    setLoading(true);

    try {
      // 1) Crear orden (si es MP/Card, queda pending sin tickets)
      const res = await fetch("/api/orders/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          tenant_id: "default",
          event_slug: selectedEvent.slug,
          sale_item_id: selectedTicket.id,
          quantity,
          payment_method: method || "cash",
          buyer: {
            full_name: name,
            dni,
            address,
            email: me?.email || checkoutForm.email,
            phone: checkoutForm.phone,
          },
        }),
      });

      if (res.status === 401) {
        openLoginModal({ method });
        return;
      }

      const data = await readJsonOrText(res);
      if (!res.ok || !data?.ok) {
        throw new Error(data?.detail || "No se pudo crear la orden");
      }

      // 2) Si es Mercado Pago: crear preferencia y redirigir al checkout
      if ((method || "").toLowerCase() === "mp") {
        const prefRes = await fetch(`/api/payments/mp/create-preference?tenant=default`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ order_id: data.order_id }),
        });
        const pref = await readJsonOrText(prefRes);
        if (!prefRes.ok || !pref?.ok || !pref?.checkout_url) {
          throw new Error(pref?.detail || "No se pudo iniciar Mercado Pago");
        }
        // redirect
        window.location.href = pref.checkout_url;
        return;
      }

      // 3) Cash / Reserva (pago en puerta): éxito local (tickets emitidos)
      setPurchaseData({
        event: selectedEvent,
        ticket: selectedTicket,
        quantity,
        user: { ...checkoutForm },
        method,
        order_id: data.order_id,
        tickets: data.tickets || [],
        total_cents: data.total_cents,
        base_cents: data.base_cents,
        fee_cents: data.fee_cents,
      });

      setView("success");
    } catch (e) {
      console.error(e);
      alert("Error en checkout: " + (e?.message || e));
    } finally {
      setLoading(false);
    }
  };

  const openEditor = (ev = null, initialTab = "info") => {
    setIsEditing(true);
    setActiveTab(initialTab);
    if (ev) {
      const copy = JSON.parse(JSON.stringify(ev));
      copy._is_new = false;
      setEditFormData(copy);
    } else {
      setEditFormData({
        _is_new: true,
        id: Date.now(),
        title: "Nuevo Evento",
        slug: slugify("Nuevo Evento"),
        category: "Música",
        date_text: "Sáb, 01 de Enero",
        venue: "Venue",
        city: "Mendoza",
        flyer_url:
          "https://images.unsplash.com/photo-1574391884720-bbe3740e581a?q=80&w=1974&auto=format&fit=crop",
        active: true,
        accept_terms: false,
        stock_total: 0,
        stock_sold: 0,
        revenue: 0,
        items: [{ id: 1, name: "General", price: 0, stock: 0, sold: 0 }],
        sellers: [{ id: 1, name: "Staff", code: "CODE", sales: 0 }],
      });
    }
  };

  const saveEvent = async (finalize = true, closeOnSuccess = true) => {
    if (!editFormData) return;

    if (finalize && !editFormData.accept_terms) {
      alert("Para publicar un evento tenés que aceptar Términos y Condiciones.");
      return;
    }

    try {
      // login requerido para productor
      if (!me) {
        openLoginModal({});
        return;
      }

      const isUpdate = editFormData?._is_new === false;
      const url = isUpdate ? `/api/producer/events/${editFormData.slug}` : "/api/producer/events";
      const method = isUpdate ? "PUT" : "POST";

      const payload = {
        title: (editFormData.title ?? editFormData.name),
        slug: editFormData.slug,
        date_text: editFormData.date_text || editFormData.date,
        city: editFormData.city,
        venue: editFormData.venue,
        description: editFormData.description,
        flyer_url: editFormData.flyer_url,
        hero_bg: editFormData.hero_bg,
        address: editFormData.address,
        lat: editFormData.lat,
        lng: editFormData.lng,
        accept_terms: !!editFormData.accept_terms,
      };


      const r = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(payload),
      });

      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error((data && data.detail) || "No se pudo guardar el evento");

      await refreshPublicEvents();
      // Importante: el panel Producer mantiene su propio state.
      // Si no refrescamos acá, parece que "no se creó" hasta tocar ACTUALIZAR.
      try {
        await loadProducerEvents();
      } catch (e) {
        // no bloquea el flujo
      }

// Actualizamos el form con el slug/id real del backend (especialmente útil cuando el slug se normaliza)
const createdSlug = (data && (data.event_slug || data.slug)) ? (data.event_slug || data.slug) : payload.slug;
const createdId = (data && data.id) ? data.id : editFormData.id;

setEditFormData((prev) => {
  if (!prev) return prev;
  return {
    ...prev,
    _is_new: false,
    id: createdId,
    slug: createdSlug || prev.slug,
  };
});

if (closeOnSuccess) {
  setIsEditing(false);
  setEditFormData(null);
}
      return true;
    } catch (e) {
      console.error(e);
      alert("Error guardando evento: " + (e?.message || (typeof e === "string" ? e : JSON.stringify(e))));
      return false;
    }
  };

  // -------------------------
  // UI Components (inline / demo)
  // -------------------------
  const Header = () => {
    return (
      <header className="fixed top-0 left-0 right-0 z-50 bg-black/50 backdrop-blur-xl border-b border-white/5 overflow-x-hidden">
        <div className="max-w-7xl mx-auto w-full px-4 sm:px-6 py-4 sm:py-5">
          {/* TOP */}
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-14 h-14 sm:w-16 sm:h-16 rounded-3xl bg-gradient-to-br from-indigo-500 via-indigo-600 to-fuchsia-600 flex items-center justify-center shadow-[0_0_60px_rgba(99,102,241,0.55)] ring-1 ring-white/15 flex-shrink-0">
                <QrCode className="text-white" size={26} />
              </div>

              <div className="min-w-0">
                <div className="text-white font-black uppercase italic tracking-tight text-2xl sm:text-3xl leading-none truncate">
                  Ticket<span className="text-indigo-400">Pro</span>
                </div>
              </div>

              {/* Botón Ingresar al lado del logo (cuando no hay sesión) */}
              {!me && (
                <button
                  onClick={() => setLoginRequired(true)}
                  className="hidden sm:inline-flex items-center gap-2 ml-1 px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 text-white flex-shrink-0"
                >
                  <User size={16} /> Ingresar
                </button>
              )}
            </div>

            <div className="flex items-center gap-2 flex-shrink-0">
              {/* Mobile Ingresar */}
              {!me ? (
                <button
                  onClick={() => setLoginRequired(true)}
                  className="sm:hidden inline-flex items-center gap-2 px-4 py-2.5 rounded-2xl text-[9px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 text-white"
                >
                  <User size={16} /> Ingresar
                </button>
              ) : (
                <>
                  <div className="hidden md:flex flex-col items-end">
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                      Sesión
                    </div>
                    <div className="text-[11px] font-black text-white">{me.fullName || "User"}</div>
                  </div>
                  <button
                    onClick={logout}
                    className="px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 text-white"
                  >
                    Salir
                  </button>
                </>
              )}
            </div>
          </div>

          {/* TABS (abajo) */}
          <nav className="mt-4 flex items-center justify-center sm:justify-start gap-2 w-full">
            <button
              onClick={() => setView("public")}
              className={`px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest transition-all ${
                view === "public" ? "bg-indigo-600 text-white" : "bg-white/5 hover:bg-white/10"
              }`}
            >
              Cartelera
            </button>
            

            <button
              onClick={() => {
                if (!me) {
                  setView("public");
                  openLoginModal({ goto: "myTickets" });
                  return;
                }
                setView("myTickets");
                setTimeout(() => {
                  try { loadMyAssets(); } catch (e) {}
                }, 0);
              }}
              className={`px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest transition-all ${
                view === "myTickets" ? "bg-indigo-600 text-white" : "bg-white/5 hover:bg-white/10"
              }`}
            >
              Mis Tickets
            </button>
          </nav>
        </div>
      </header>
    );
  };

  const Footer = () => {
    return (
      <footer className="border-t border-white/5 bg-black/40 backdrop-blur-xl overflow-x-hidden">
        <div className="max-w-7xl mx-auto px-6 py-10">
          <div className="flex flex-col md:flex-row gap-10 md:items-start md:justify-between">
            <div className="min-w-0">
              <div className="text-white font-black uppercase italic tracking-tight text-xl">
                Ticket<span className="text-indigo-400">Pro</span>
              </div>
              <div className="text-[11px] text-white/50 mt-2 max-w-md">
                Plataforma de tickets con QR antifraude. Cartelera pública + panel Producer en un solo lugar.
              </div>
              <div className="mt-4">
                <button
                  onClick={() => {
                    if (!me) {
                      openLoginModal({ goto: "producer" });
                      return;
                    }
                    setView("producer");
                    setTimeout(() => {
                      try { loadProducerEvents(); } catch (e) {}
                    }, 0);
                  }}
                  className="px-5 py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
                >
                  Productor
                </button>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-8 text-[11px] font-black uppercase tracking-widest">
              <div className="space-y-3">
                <div className="text-neutral-500">Legal</div>
                <a className="block text-white/80 hover:text-white transition-colors" href="#terminos">
                  Términos
                </a>
                <a className="block text-white/80 hover:text-white transition-colors" href="#privacidad">
                  Privacidad
                </a>
                <a className="block text-white/80 hover:text-white transition-colors" href="#cookies">
                  Cookies
                </a>
              </div>

              <div className="space-y-3">
                <div className="text-neutral-500">Contacto</div>
                <a className="block text-white/80 hover:text-white transition-colors" href="mailto:soporte@ticketpro.app">
                  soporte@ticketpro.app
                </a>
                <a className="block text-white/80 hover:text-white transition-colors" href="#contacto">
                  Formulario
                </a>
              </div>

              <div className="space-y-3 col-span-2 sm:col-span-1">
                <div className="text-neutral-500">Redes</div>
                <div className="flex items-center gap-2">
                  <a
                    className="px-4 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 transition-all"
                    href="#instagram"
                  >
                    Instagram
                  </a>
                  <a
                    className="px-4 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 transition-all"
                    href="#tiktok"
                  >
                    TikTok
                  </a>
                  <a
                    className="px-4 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 transition-all"
                    href="#x"
                  >
                    X
                  </a>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-10 flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between text-[10px] font-black uppercase tracking-widest text-white/40">
            <div>© {new Date().getFullYear()} TicketPro</div>
            <div className="flex items-center gap-4">
              <span>Hecho para escalar</span>
              <span className="hidden sm:inline">·</span>
              <span>Sin vueltas, sin scroll lateral</span>
            </div>
          </div>
        </div>
      </footer>
    );
  };



  // -------------------------
  // Public filters (derived)
  // -------------------------
  const cities = useMemo(() => {
    const set = new Set();
    (events || []).forEach((ev) => {
      const c = (ev?.city || "").trim();
      if (c) set.add(c);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b, "es"));
  }, [events]);

  const types = useMemo(() => {
    const set = new Set();
    (events || []).forEach((ev) => {
      const t = (ev?.category || "").trim();
      if (t) set.add(t);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b, "es"));
  }, [events]);

  const filteredEvents = useMemo(() => {
    const q = (searchQuery || "").trim().toLowerCase();
    return (events || []).filter((ev) => {
      if (filterCity !== "all" && (ev?.city || "") !== filterCity) return false;
      if (filterType !== "all" && (ev?.category || "") !== filterType) return false;
      if (!q) return true;
      const haystack = `${ev?.title || ""} ${ev?.venue || ""} ${ev?.city || ""} ${ev?.category || ""}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [events, filterCity, filterType, searchQuery]);

  // -------------------------
  // VIEWS
  // -------------------------
  return (
    <div className={`min-h-screen ${UI.bg} text-white overflow-x-hidden`}>
      <Header />

      <main className="min-h-screen pt-36 sm:pt-40">
        {/* PUBLIC */}
        {view === "public" && (
          <div className="pt-0 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-8 mb-12">
              <div>
                <h1 className="text-5xl font-black uppercase italic tracking-tight">
                  Cartelera <span className="text-indigo-600">Viva</span>
                </h1>
                <p className="text-[10px] font-black uppercase tracking-widest text-neutral-500 mt-2">
                  Comprá tu ticket · QR antifraude · acceso rápido
                </p>
              </div>
            </div>

            {/* DESTACADOS / CAROUSEL */}
            <div className="mt-10">
              <div className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
                Destacados
              </div>
              <div className="text-2xl font-black uppercase mt-2">Eventos recomendados</div>
              <div className="mt-4">
                <FeaturedCarousel
                  events={filteredEvents}
                  formatMoneyFn={formatMoney}
                  onOpen={(ev) => {
                    setQuantity(1);
                    setCheckoutForm({ fullName: "", dni: "", address: "" });
                    openPublicEvent(ev.slug);
                  }}
                />
              </div>
            </div>



            {/* FILTROS RÁPIDOS */}
            <div className={`mt-6 ${UI.card} rounded-[2.5rem] border border-white/10 p-4 sm:p-5 overflow-x-hidden`}>
              <div className="flex flex-col lg:flex-row gap-3 lg:items-center">
                <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <label className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
                    Ciudad
                    <select
                      value={filterCity}
                      onChange={(e) => setFilterCity(e.target.value)}
                      className="mt-2 w-full rounded-2xl bg-white/5 border border-white/10 px-4 py-3 text-white text-[12px] font-black"
                    >
                      <option value="all">Todas</option>
                      {cities.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
                    Tipo
                    <select
                      value={filterType}
                      onChange={(e) => setFilterType(e.target.value)}
                      className="mt-2 w-full rounded-2xl bg-white/5 border border-white/10 px-4 py-3 text-white text-[12px] font-black"
                    >
                      <option value="all">Todos</option>
                      {types.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                <div className="flex-1">
                  <div className="text-[10px] font-black uppercase tracking-widest text-neutral-500">Búsqueda</div>
                  <div className="mt-2 flex items-center gap-3 rounded-2xl bg-white/5 border border-white/10 px-4 py-3">
                    <Search size={18} className="text-white/60" />
                    <input
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Buscar por evento, venue, ciudad…"
                      className="w-full bg-transparent outline-none text-white placeholder:text-white/30 font-black text-[12px]"
                    />
                    {(filterCity !== "all" || filterType !== "all" || (searchQuery || "").trim()) && (
                      <button
                        onClick={() => {
                          setFilterCity("all");
                          setFilterType("all");
                          setSearchQuery("");
                        }}
                        className="px-3 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-[9px] font-black uppercase tracking-widest"
                      >
                        Limpiar
                      </button>
                    )}
                  </div>
                </div>
              </div>

              <div className="mt-3 text-[10px] text-white/50 font-black uppercase tracking-widest">
                Mostrando {filteredEvents.length} de {events.length}
              </div>
            </div>

            {/* LISTADO MOBILE (compacto) */}
            <div className="md:hidden mt-8 space-y-4">
              {filteredEvents.map((ev) => (
                <button
                  key={ev.id}
                  onClick={() => {
                    setQuantity(1);
                    setCheckoutForm({ fullName: "", dni: "", address: "" });
                    openPublicEvent(ev.slug);
                  }}
                  className={`w-full text-left ${UI.card} rounded-3xl p-4 flex gap-4 items-center`}
                >
                  <img
                    src={flyerSrc(ev)}
                    alt={ev.title}
                    onError={(e) => {
                      e.currentTarget.onerror = null;
                      e.currentTarget.src = FALLBACK_FLYER;
                    }}
                    className="w-16 h-16 rounded-2xl object-cover shrink-0"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-400">
                      {ev.city}
                    </div>
                    <div className="text-base font-black uppercase italic truncate">{ev.title}</div>
                    <div className="text-[11px] text-neutral-300 mt-1 flex items-center gap-2">
                      <Calendar size={14} /> {ev.date_text}
                    </div>
                    <div className="text-[11px] text-neutral-300 mt-1 flex items-center gap-2">
                      <MapPin size={14} /> {ev.venue}
                    </div>
                    <div className="mt-2 text-sm font-black text-indigo-300 italic">
                      {priceLabelForEvent(ev, formatMoney)}
                    </div>
                  </div>
                </button>
              ))}
            </div>


<div className="hidden md:grid grid-cols-3 gap-8">
              {filteredEvents.map((ev) => (
                <button
                  key={ev.id}
                  onClick={() => {
                    setQuantity(1);
                    setCheckoutForm({ fullName: "", dni: "", address: "" });
                    openPublicEvent(ev.slug);
                  }}
                  className={`text-left overflow-hidden rounded-[2.5rem] ${UI.card} hover:border-indigo-600/40 transition-all`}
                >
                  <div className="relative h-56">
                    <img
                      src={flyerSrc(ev)}
                      alt={ev.title}
                      onError={(e) => {
                        e.currentTarget.onerror = null;
                        e.currentTarget.src = FALLBACK_FLYER;
                      }}
                      className="w-full h-full object-cover opacity-90"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />
                    <div className="absolute bottom-0 left-0 p-6">
                      <div className="text-[9px] font-black uppercase tracking-widest text-neutral-300">
                        {ev.category} · {ev.city}
                      </div>
                      <div className="text-2xl font-black uppercase italic mt-1">{ev.title}</div>
                      <div className="text-[11px] text-neutral-300 mt-2 flex items-center gap-2">
                        <Calendar size={14} /> {ev.date_text}
                      </div>
                      <div className="text-[11px] text-neutral-300 mt-1 flex items-center gap-2">
                        <MapPin size={14} /> {ev.venue}
                      </div>
                    </div>
                  </div>

                  <div className="p-6 flex items-center justify-between gap-4">
                    <div>
                      <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                        Desde
                      </div>
                      <div className="text-xl font-black text-indigo-400 italic">
                        {priceLabelForEvent(ev, formatMoney)}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                        Stock
                      </div>
                      <div className="text-[11px] font-black">
                        {(ev.stock_total || 0) - (ev.stock_sold || 0)} / {ev.stock_total || 0}
                      </div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* DETAIL */}
        {view === "detail" && (
          selectedEvent ? (
          <div className="pt-0 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
            <button
              onClick={() => setView("public")}
              className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all mb-8"
            >
              <ChevronLeft size={16} /> Volver
            </button>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-10">
              <div className={`overflow-hidden rounded-[2.5rem] ${UI.card} lg:col-span-2`}>
                <div className="relative h-72">
                  <img
                    src={selectedEvent.flyer_url || FALLBACK_FLYER}
                    alt={selectedEvent.title}
                    className="w-full h-full object-cover opacity-90"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-transparent" />
                  <div className="absolute bottom-0 left-0 p-8">
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-300">
                      {selectedEvent.category} · {selectedEvent.city}
                    </div>
                    <div className="text-4xl font-black uppercase italic mt-1">
                      {selectedEvent.title}
                    </div>
                    <div className="text-[11px] text-neutral-300 mt-3 flex items-center gap-2">
                      <Calendar size={14} /> {selectedEvent.date_text}
                    </div>
                    <div className="text-[11px] text-neutral-300 mt-1 flex items-center gap-2">
                      <MapPin size={14} /> {selectedEvent.venue}
                    </div>
                    {buildUberLink(selectedEvent) && (
                      <a
                        href={buildUberLink(selectedEvent)}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-2 mt-3 px-4 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest"
                      >
                        <MapPin size={14} /> Cotizar en Uber
                      </a>
                    )}
                  </div>
                </div>

                <div className="p-8">
                  {(selectedEvent.description || selectedEvent.address) && (
                    <div className="mb-8">
                      {selectedEvent.description && (
                        <div className="text-[12px] text-neutral-300 leading-relaxed">
                          {selectedEvent.description}
                        </div>
                      )}
                      {selectedEvent.address && (
                        <div className="text-[11px] text-neutral-500 mt-3 flex items-center gap-2">
                          <MapPin size={14} /> {selectedEvent.address}
                        </div>
                      )}
                    </div>
                  )}
                  <div className="flex items-center gap-3 mb-6">
                    <div className="p-3 rounded-2xl bg-indigo-600/20 border border-indigo-600/30">
                      <Ticket className="text-indigo-300" size={18} />
                    </div>
                    <div>
                      <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                        Elegí tu ticket
                      </div>
                      <div className="text-xl font-black uppercase italic">Tipos disponibles</div>
                    </div>
                  </div>

                  <div className="space-y-3">
                    {(selectedEvent.items || []).map((it) => (
                      <button
                        key={it.id}
                        onClick={() => setSelectedTicket(it)}
                        className={`w-full p-5 rounded-3xl flex items-center justify-between gap-4 transition-all border ${
                          selectedTicket?.id === it.id
                            ? "bg-indigo-600/10 border-indigo-600/30"
                            : "bg-white/5 border-white/10 hover:bg-white/10"
                        }`}
                      >
                        <div className="text-left">
                          <div className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
                            Ticket
                          </div>
                          <div className="text-lg font-black uppercase">{it.name}</div>
                          <div className="text-[11px] text-neutral-400 mt-1">
                            Stock: {(it.stock || 0) - (it.sold || 0)} / {it.stock || 0}
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                            Precio
                          </div>
                          <div className="text-xl font-black text-indigo-400 italic">
                            {formatMoney(it.price)}
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className={`p-8 rounded-[2.5rem] ${UI.card}`}>
                <div className="flex items-center gap-3 mb-6">
                  <div className="p-3 rounded-2xl bg-indigo-600/20 border border-indigo-600/30">
                    <CreditCard className="text-indigo-300" size={18} />
                  </div>
                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                      Checkout
                    </div>
                    <div className="text-xl font-black uppercase italic">Datos del titular</div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">
                      Nombre y Apellido
                    </div>
                    <input
                      value={checkoutForm.fullName}
                      onChange={(e) => setCheckoutForm({ ...checkoutForm, fullName: e.target.value })}
                      placeholder="Nombre y Apellido"
                      autoComplete="name"
                      onBlur={() => setCheckoutTouched({ ...checkoutTouched, fullName: true })}
                      className={`w-full px-4 py-3 rounded-2xl bg-white/5 border text-[12px] font-bold ${checkoutError("fullName") ? "border-red-500/70" : "border-white/10"}`}
                    />
                    {checkoutError("fullName") && (
                      <div className="mt-1 text-[10px] font-bold text-red-400">
                        {checkoutError("fullName")}
                      </div>
                    )}
                  </div>

                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">
                      DNI
                    </div>
                    <input
                      value={checkoutForm.dni}
                      onChange={(e) => {
                        const v = String(e.target.value || "")
                          .replace(/\D/g, "")
                          .slice(0, 8);
                        setCheckoutForm({ ...checkoutForm, dni: v });
                      }}
                      onBlur={() => setCheckoutTouched({ ...checkoutTouched, dni: true })}
                      placeholder="DNI (mín. 7 números)"
                      inputMode="numeric"
                      minLength={7}
                      maxLength={8}
                      autoComplete="off"
                      className={`w-full px-4 py-3 rounded-2xl bg-white/5 border text-[12px] font-bold ${checkoutError("dni") ? "border-red-500/70" : "border-white/10"}`}
                    />
                    {checkoutError("dni") && (
                      <div className="mt-1 text-[10px] font-bold text-red-400">
                        {checkoutError("dni")}
                      </div>
                    )}
                  </div>

                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">
                      Domicilio completo
                    </div>
                    <input
                      value={checkoutForm.address}
                      onChange={(e) => setCheckoutForm({ ...checkoutForm, address: e.target.value })}
                      placeholder="Calle, número, ciudad"
                      autoComplete="street-address"
                      onBlur={() => setCheckoutTouched({ ...checkoutTouched, address: true })}
                      className={`w-full px-4 py-3 rounded-2xl bg-white/5 border text-[12px] font-bold ${checkoutError("address") ? "border-red-500/70" : "border-white/10"}`}
                    />
                    {checkoutError("address") && (
                      <div className="mt-1 text-[10px] font-bold text-red-400">
                        {checkoutError("address")}
                      </div>
                    )}
                  </div>

                  <div className="flex items-center justify-between gap-4 pt-2">
                    <div>
                      <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                        Cantidad
                      </div>
                      <div className="flex items-center gap-2 mt-2">
                        <button
                          onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                          disabled={quantity <= 1}
                          className="w-10 h-10 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 flex items-center justify-center text-white disabled:opacity-40 disabled:cursor-not-allowed"
                          aria-label="Restar"
                        >
                          <span className="text-lg font-black leading-none">−</span>
                        </button>
                        <div className="w-10 text-center text-lg font-black">{quantity}</div>
                        <button
                          onClick={() => setQuantity((q) => q + 1)}
                          className="w-10 h-10 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 flex items-center justify-center text-white"
                          aria-label="Sumar"
                        >
                          <span className="text-lg font-black leading-none">+</span>
                        </button>
                      </div>
                    </div>

<div className="text-right">
  <div className="text-[11px] text-neutral-400 space-y-1">
    <div className="flex items-center justify-between gap-6">
      <span className="font-bold">Subtotal</span>
      <span className="font-black">{formatMoney((selectedTicket?.price || 0) * quantity)}</span>
    </div>
    <div className="flex items-center justify-between gap-6">
      <span className="font-bold">Service charge (15%)</span>
      <span className="font-black">
        {formatMoney(((selectedTicket?.price || 0) * quantity) * 0.15)}
      </span>
    </div>
  </div>

  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mt-3">
    Total a pagar
  </div>
  <div className="text-3xl font-black text-indigo-400 italic mt-1">
    {(() => {
      const sub = (selectedTicket?.price || 0) * quantity;
      const fee = sub * 0.15;
      return formatMoney(sub + fee);
    })()}
  </div>
</div>
                  </div>

                  <div className="mt-6 p-4 rounded-2xl bg-white/5 border border-white/10">
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={checkoutForm.acceptTerms}
                        onChange={(e) => {
                          setCheckoutTouched({ ...checkoutTouched, acceptTerms: true });
                          setCheckoutForm({ ...checkoutForm, acceptTerms: e.target.checked });
                        }}
                      />
                      <div className="text-[11px] text-neutral-300 leading-relaxed">
                        Acepto los <span className="text-white font-bold">Términos y Condiciones</span> y la política de privacidad.
                      </div>
                    </label>
                  </div>
                  {checkoutError("acceptTerms") && (
                    <div className="mt-2 text-[10px] font-bold text-red-400">
                      {checkoutError("acceptTerms")}
                    </div>
                  )}

<div className="grid grid-cols-1 gap-3 mt-6">
  <button
    onClick={() => handleCheckout("mp")}
    disabled={
      loading ||
      !selectedTicket ||
      !checkoutForm.acceptTerms ||
      !checkoutForm.fullName.trim() ||
      !checkoutForm.address.trim() ||
      String(checkoutForm.dni || "").length < 7
    }
    className={`w-full py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white transition-all flex items-center justify-center gap-2 ${UI.button} disabled:opacity-40 disabled:cursor-not-allowed`}
  >
    {loading ? <Loader2 className="animate-spin" size={16} /> : <Wallet size={16} />}
    Pagar con Mercado Pago
  </button>

  <button
    onClick={() => handleCheckout("card")}
    disabled={
      loading ||
      !selectedTicket ||
      !checkoutForm.acceptTerms ||
      !checkoutForm.fullName.trim() ||
      !checkoutForm.address.trim() ||
      String(checkoutForm.dni || "").length < 7
    }
    className="w-full py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
  >
    <CreditCard size={16} /> Pagar con tarjeta
  </button>

  <button
    disabled
    className="w-full py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest bg-white/5 border border-white/10 flex items-center justify-center gap-2 opacity-40 cursor-not-allowed"
    title="Próximamente"
  >
    <ShoppingCart size={16} /> Reservar (próximamente)
  </button>
</div>

                  <div className="mt-6 p-4 rounded-2xl bg-white/5 border border-white/10 text-[11px] text-neutral-400 leading-relaxed">
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">
                      Info
                    </div>
                    El QR se genera al confirmar pago. Demo UI.
                  </div>
                </div>
              </div>
            </div>
          </div>
          ) : (
          <div className="pt-0 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
            <button
              onClick={() => setView("public")}
              className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all mb-8"
            >
              <ChevronLeft size={16} /> Volver
            </button>

            <div className={`rounded-[2.5rem] ${UI.card} p-10 text-center`}>
              <div className="inline-flex items-center gap-3 justify-center text-neutral-300">
                <Loader2 className="animate-spin" size={18} />
                <span className="text-[11px] font-black uppercase tracking-widest">
                  Cargando evento…
                </span>
              </div>
              <div className="text-[12px] text-neutral-400 mt-4">
                Si esto tarda demasiado, volvé a la cartelera y reintentá.
              </div>
            </div>
          </div>
          )
        )}
{/* PRODUCER (demo) */}
        {view === "producer" && (
          <div className="pt-0 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-8 mb-12">
              <div>
                <h1 className="text-5xl font-black uppercase italic tracking-tight">
                  Panel de <span className="text-indigo-600">Control</span>
                </h1>
                <p className="text-[10px] font-black uppercase tracking-widest text-neutral-500 mt-2">
                  Métricas en tiempo real y gestión operativa
                </p>
              </div>

              <div className="w-full md:w-auto flex flex-col sm:flex-row items-stretch sm:items-end gap-3">
                <div className="flex-1 sm:min-w-[320px]">
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">
                    Evento (con ventas)
                  </div>
                  <div className="flex items-center gap-2">
                    <select
                      value={selectedProducerEventSlug}
                      onChange={(e) => setSelectedProducerEventSlug(e.target.value)}
                      className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 text-[11px] font-black uppercase tracking-widest text-white focus:outline-none focus:ring-2 focus:ring-indigo-600"
                      disabled={producerEventsLoading}
                    >
                      {producerEventsLoading && <option value="">Cargando…</option>}
                      {!producerEventsLoading && producerEvents.length === 0 && (
                        <option value="">Sin ventas recientes</option>
                      )}
                      {!producerEventsLoading &&
                        producerEvents.map((ev) => {
                          const slug = ev.event_slug || ev.eventSlug || ev.slug;
                          const ordersCount = ev.orders_count ?? ev.orders ?? ev.ordersCount;
                          const totalCents = ev.total_cents ?? ev.total ?? ev.totalCents;
                          const label = `${slug}${ordersCount != null ? ` · ${ordersCount} órdenes` : ""}${
                            totalCents != null ? ` · $${Math.round((totalCents / 100) || 0).toLocaleString()}` : ""
                          }`;
                          return (
                            <option key={slug} value={slug}>
                              {label}
                            </option>
                          );
                        })}
                    </select>

                    <button
                      onClick={() => refreshProducerAnalytics()}
                      disabled={producerEventsLoading || producerDashboardLoading}
                      className={`px-4 py-3 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white transition-all flex items-center justify-center gap-2 ${UI.button}`}
                      title="Refrescar"
                    >
                      {producerEventsLoading || producerDashboardLoading ? (
                        <Loader2 size={16} className="animate-spin" />
                      ) : (
                        <RefreshCw size={16} />
                      )}
                    </button>
                  </div>
                  {producerEventsError && (
                    <div className="mt-2 text-[10px] font-bold text-rose-400">{producerEventsError}</div>
                  )}
                </div>

                <button
                  onClick={() => openEditor()}
                  className={`px-8 py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white transition-all ${UI.button}`}
                >
                  <Plus size={16} /> Crear Evento
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-16">
              {[
                {
                  label: "Recaudación Total",
                  val: `$${(events.reduce((acc, ev) => acc + (ev.revenue || 0), 0) / 1000).toLocaleString()}k`,
                  icon: DollarSign,
                },
                {
                  label: "Eventos Activos",
                  val: `${events.filter((e) => e.active).length}`,
                  icon: CheckCircle2,
                },
                {
                  label: "Tickets Vendidos",
                  val: `${events.reduce((acc, ev) => acc + (ev.stock_sold || 0), 0).toLocaleString()}`,
                  icon: Ticket,
                },
                {
                  label: "Sellers",
                  val: `${events.reduce((acc, ev) => acc + (ev.sellers?.length || 0), 0)}`,
                  icon: Users,
                },
              ].map((k, idx) => (
                <div key={idx} className={`p-6 rounded-[2.5rem] ${UI.card}`}>
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                      {k.label}
                    </div>
                    <div className="p-2 rounded-2xl bg-indigo-600/20 border border-indigo-600/30">
                      <k.icon size={18} className="text-indigo-300" />
                    </div>
                  </div>
                  <div className="text-3xl font-black uppercase italic tracking-tight">{k.val}</div>
                </div>
              ))}
            </div>

            {/* DASHBOARD CRUZADO (real) */}
            <div className={`p-8 rounded-[2.5rem] ${UI.card} mb-16`}>
              <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6 mb-8">
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                    Entradas + Barra
                  </div>
                  <h2 className="text-2xl font-black uppercase italic tracking-tight">
                    Dashboard Cruzado <span className="text-indigo-600">Real</span>
                  </h2>
                  <p className="text-[11px] text-neutral-400 mt-2 max-w-2xl">
                    Este módulo consume el backend:{" "}
                    <span className="text-white/80 font-bold">/api/producer/events</span> y{" "}
                    <span className="text-white/80 font-bold">/api/producer/dashboard</span>.
                    Elegís un evento arriba y acá ves la info combinada.
                  </p>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    onClick={() => selectedProducerEventSlug && loadProducerDashboard(selectedProducerEventSlug)}
                    disabled={!selectedProducerEventSlug || producerDashboardLoading}
                    className={`px-6 py-3 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white transition-all flex items-center gap-2 ${UI.button}`}
                  >
                    {producerDashboardLoading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
                    Actualizar
                  </button>
                </div>
              </div>

              {producerDashboardError && (
                <div className="mb-6 p-4 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-[11px] font-bold">
                  {producerDashboardError}
                </div>
              )}

              {!producerDashboard && producerDashboardLoading && (
                <div className="p-10 rounded-3xl bg-white/5 border border-white/10 flex items-center justify-center gap-3">
                  <Loader2 className="animate-spin" size={18} />
                  <div className="text-[11px] font-black uppercase tracking-widest text-neutral-400">
                    Cargando dashboard…
                  </div>
                </div>
              )}

              {producerDashboard && (
                <>
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-10">
                    {[
                      { label: "Revenue Total", val: `$${(producerDashboard.kpis?.total || 0).toLocaleString()}`, icon: CreditCard },
                      { label: "Ventas Barra", val: `$${(producerDashboard.kpis?.bar || 0).toLocaleString()}`, icon: ShoppingCart },
                      { label: "Tickets Emitidos", val: `${(producerDashboard.kpis?.tickets || 0).toLocaleString()}`, icon: Ticket },
                      { label: "Ticket Promedio", val: `$${(producerDashboard.kpis?.avg || 0).toLocaleString()}`, icon: DollarSign },
                    ].map((k, i) => (
                      <div key={i} className="p-6 rounded-3xl bg-white/5 border border-white/10">
                        <div className="flex items-center justify-between">
                          <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">{k.label}</div>
                          <div className="p-2 rounded-2xl bg-indigo-600/20 border border-indigo-600/30">
                            <k.icon size={18} className="text-indigo-300" />
                          </div>
                        </div>
                        <div className="mt-4 text-2xl font-black tracking-tight">{k.val}</div>
                        <div className="mt-2 text-[11px] text-neutral-500">
                          Evento: <span className="text-white/70 font-bold">{selectedProducerEventSlug}</span>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div className="lg:col-span-2 p-6 rounded-3xl bg-white/5 border border-white/10">
                      <div className="flex items-center justify-between mb-4">
                        <div>
                          <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Serie temporal</div>
                          <div className="text-xl font-black uppercase italic">Hora vs Tickets / Barra</div>
                        </div>
                      </div>

                      <div className="space-y-2">
                        {(producerDashboard.timeSeries || []).length === 0 && (
                          <div className="text-[11px] text-neutral-500">Sin datos horarios todavía.</div>
                        )}
                        {(producerDashboard.timeSeries || []).slice(-24).map((r, idx) => (
                          <div key={idx} className="flex items-center gap-4">
                            <div className="w-14 text-[11px] font-black text-neutral-400">{r.hour}</div>
                            <div className="flex-1 h-2 rounded-full bg-white/5 overflow-hidden">
                              <div
                                className="h-full bg-indigo-600/80"
                                style={{
                                  width: `${Math.min(
                                    100,
                                    Math.round(((r.tickets || 0) / Math.max(1, producerDashboard.kpis?.tickets || 1)) * 100)
                                  )}%`,
                                }}
                              />
                            </div>
                            <div className="w-24 text-right text-[11px] font-bold text-neutral-300">
                              {r.tickets || 0} tks
                            </div>
                            <div className="w-28 text-right text-[11px] font-bold text-indigo-300">
                              ${((r.bar || 0)).toLocaleString()}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="p-6 rounded-3xl bg-white/5 border border-white/10">
                      <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Top items (MVP)</div>
                      <div className="text-xl font-black uppercase italic mb-4">Productos / Tipos</div>

                      <div className="space-y-3">
                        {(producerDashboard.topProducts || []).length === 0 && (
                          <div className="text-[11px] text-neutral-500">Sin items para este evento.</div>
                        )}
                        {(producerDashboard.topProducts || []).slice(0, 8).map((p, idx) => (
                          <div key={idx} className="flex items-center justify-between gap-4 p-3 rounded-2xl bg-white/5 border border-white/10">
                            <div className="min-w-0">
                              <div className="text-[11px] font-black truncate">{p.name}</div>
                              <div className="text-[10px] text-neutral-500">
                                {p.category} · {p.sales} ventas
                              </div>
                            </div>
                            <div className="text-[11px] font-black text-indigo-300">
                              ${Number(p.revenue || 0).toLocaleString()}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="mt-10 p-6 rounded-3xl bg-indigo-600/10 border border-indigo-600/20">
                    <div className="text-[10px] font-black uppercase tracking-widest text-indigo-200">
                      Nota técnica
                    </div>
                    <div className="text-[12px] text-indigo-100/80 mt-2 leading-relaxed">
                      Hoy tu <span className="font-bold">items_json</span> es un objeto plano (no array). Por eso el MVP agrupa por{" "}
                      <span className="font-bold">ticket_type_id</span> / <span className="font-bold">sale_item_id</span>.
                      Cuando conectemos nombres con <span className="font-bold">ticket_types</span> y <span className="font-bold">sale_items</span>,
                      este bloque pasa a “Top Productos” con nombres humanos.
                    </div>
                  </div>
                </>
              )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
	            {/* Lista de eventos (reales, filtrados por productor en backend) */}
              <div className={`p-8 rounded-[2.5rem] ${UI.card} lg:col-span-2`}>
                <div className="flex items-start justify-between gap-6 mb-8">
                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                      Eventos
                    </div>
                    <div className="text-2xl font-black uppercase italic">Gestión</div>
	                    <div className="text-[11px] text-neutral-400 mt-2">
	                      Solo se muestran tus eventos (asociados a tu cuenta de productor).
	                    </div>
                  </div>
                  <button
                    onClick={() => openEditor()}
                    className={`px-6 py-3 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white transition-all ${UI.button}`}
                  >
                    <Plus size={16} /> Nuevo
                  </button>
                </div>

	                <div className="space-y-4">
	                  {(producerEvents || []).map((ev) => (
                    <div
	                      key={ev.id || ev.slug}
                      className="p-6 rounded-3xl bg-white/5 border border-white/10 flex flex-col md:flex-row gap-6 items-start md:items-center justify-between"
                    >
                      <div className="flex items-center gap-4">
                        <img
                          src={flyerSrc(ev)}
                          alt={ev.title}
                          className="w-20 h-20 object-cover rounded-2xl border border-white/10"
                        />
                        <div>
                          <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                            {ev.slug}
                          </div>
                          <div className="text-xl font-black uppercase">{ev.title}</div>
                          <div className="text-[11px] text-neutral-400 mt-1 flex items-center gap-2">
                            <Calendar size={14} /> {ev.date_text}
                            <span className="text-neutral-600">·</span>
                            <MapPin size={14} /> {ev.venue}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 w-full md:w-auto">
                        <button
                          onClick={() => openEditor(ev)}
                          className="flex-1 md:flex-none px-5 py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
                        >
                          <Edit3 size={16} /> Editar
                        </button>
                        <button
                          onClick={() => setSelectedEvent(ev)}
                          className={`flex-1 md:flex-none px-5 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all ${UI.button}`}
                        >
                          <Info size={16} /> Ver
                        </button>
                      </div>
                    </div>
	                  ))}
	                  {(producerEvents || []).length === 0 && (
	                    <div className="p-6 rounded-3xl bg-white/5 border border-white/10 text-sm text-white/70">
	                      No tenés eventos propios todavía. Creá uno con <b>Nuevo</b>.
	                    </div>
	                  )}
                </div>
              </div>

              {/* Operación (demo) */}
              <div className={`p-8 rounded-[2.5rem] ${UI.card}`}>
                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                  Operación
                </div>
                <div className="text-2xl font-black uppercase italic mt-1 mb-6">Quick Actions</div>

                <div className="space-y-3">
                  <button className="w-full py-4 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all flex items-center justify-center gap-2">
                    <Mail size={16} /> Enviar campaña (demo)
                  </button>
                  <button className="w-full py-4 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all flex items-center justify-center gap-2">
                    <ShieldCheck size={16} /> Antifraude (demo)
                  </button>
                  <button className="w-full py-4 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all flex items-center justify-center gap-2">
                    <Instagram size={16} /> Social (demo)
                  </button>
                  <button className="w-full py-4 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all flex items-center justify-center gap-2">
                    <Twitter size={16} /> Publicar (demo)
                  </button>
                </div>

                <div className="mt-8 p-5 rounded-3xl bg-white/5 border border-white/10 text-[11px] text-neutral-400 leading-relaxed">
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">
                    Próximo paso
                  </div>
                  Conectar este panel a datos reales + permisos por productor.
                </div>
              </div>
            </div>
          </div>
        )}

        {/* SUCCESS */}
        

        {/* MIS TICKETS (cliente) */}
        {view === "myTickets" && (
          <div className="pt-0 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 mb-10">
              <div>
                <h1 className="text-5xl font-black uppercase italic tracking-tight">
                  Mis <span className="text-indigo-600">Tickets</span>
                </h1>
                <p className="text-[11px] text-white/60 mt-2 max-w-2xl leading-relaxed">
                  Acá ves tus compras de <span className="text-white font-black">Entradas</span> y <span className="text-white font-black">Barra</span>.
                  Los QR se muestran listos para validar. Para <span className="text-white font-black">arrepentimiento</span> se genera una solicitud y el productor se contactará.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => loadMyAssets()}
                  className="px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 text-white"
                >
                  Actualizar
                </button>
              </div>
            </div>

            {/* Filtros */}
            <div className="p-5 rounded-3xl bg-white/5 border border-white/10 mb-10">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Tipo</div>
                  <select
                    value={myFilters.kind}
                    onChange={(e) => setMyFilters((s) => ({ ...s, kind: e.target.value }))}
                    className="w-full bg-black/40 border border-white/10 rounded-2xl px-4 py-3 text-[11px] text-white outline-none"
                  >
                    <option value="all">Todos</option>
                    <option value="entradas">Entradas</option>
                    <option value="barra">Barra</option>
                  </select>
                </div>

                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Estado</div>
                  <select
                    value={myFilters.status}
                    onChange={(e) => setMyFilters((s) => ({ ...s, status: e.target.value }))}
                    className="w-full bg-black/40 border border-white/10 rounded-2xl px-4 py-3 text-[11px] text-white outline-none"
                  >
                    <option value="all">Todos</option>
                    <option value="valid">Por usar</option>
                    <option value="used">Usados</option>
                    <option value="cancel_requested">Arrepentimiento solicitado</option>
                    <option value="cancelled">Cancelados</option>
                  </select>
                </div>

                <div className="md:col-span-2">
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Búsqueda</div>
                  <div className="flex items-center gap-2 bg-black/40 border border-white/10 rounded-2xl px-4 py-3">
                    <Search size={16} className="text-white/50" />
                    <input
                      value={myFilters.q}
                      onChange={(e) => setMyFilters((s) => ({ ...s, q: e.target.value }))}
                      placeholder="Buscar por evento, venue, ciudad…"
                      className="w-full bg-transparent outline-none text-[11px] text-white placeholder:text-white/30"
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* Content */}
            {myAssetsLoading ? (
              <div className="text-white/60 text-[11px]">Cargando…</div>
            ) : myAssetsError ? (
              <div className="p-5 rounded-3xl bg-red-500/10 border border-red-500/20 text-[11px] text-red-200">
                {myAssetsError}
              </div>
            ) : (
              (() => {
                const q = (myFilters.q || "").trim().toLowerCase();

                const filtered = (Array.isArray(myAssets) ? myAssets : [])
                  .filter((a) => (myFilters.kind === "all" ? true : (String(a.kind || "") === myFilters.kind)))
                  .filter((a) => {
                    if (myFilters.status === "all") return true;
                    const st = String(a.status || "").toLowerCase();
                    return st === myFilters.status;
                  })
                  .filter((a) => {
                    if (!q) return true;
                    const hay = `${a.title || ""} ${a.venue || ""} ${a.city || ""} ${a.event_slug || ""}`.toLowerCase();
                    return hay.includes(q);
                  });

                if (!filtered.length) {
                  return (
                    <div className="p-6 rounded-3xl bg-white/5 border border-white/10 text-[11px] text-white/60">
                      No hay tickets para mostrar con esos filtros.
                    </div>
                  );
                }

                return (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {filtered.map((a) => {
                      const kind = String(a.kind || "entradas");
                      const st = String(a.status || "valid").toLowerCase();
                      const isUsed = st === "used";
                      const isCancelReq = st === "cancel_requested";
                      const isCancelled = st === "cancelled";
                      const badgeKind = kind === "barra" ? "Barra" : "Entradas";

                      const badgeStatus = isCancelled ? "Cancelado" : isCancelReq ? "Arrepentimiento" : isUsed ? "Usado" : "Por usar";
                      const qrPayload = a.qr_payload || "";

                      return (
                        <div key={`${kind}-${a.id}`} className="rounded-3xl bg-white/5 border border-white/10 overflow-hidden">
                          <div className="flex gap-5 p-5">
                            {/* flyer */}
                            <div className="w-28 h-28 rounded-3xl overflow-hidden bg-white/10 flex-shrink-0">
                              {a.flyer_url ? (
                                <img src={a.flyer_url} alt="" className="w-full h-full object-cover" />
                              ) : (
                                <div className="w-full h-full bg-gradient-to-br from-indigo-600/40 to-fuchsia-600/30" />
                              )}
                            </div>

                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <div className="px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-widest bg-white/10 border border-white/10">
                                  {badgeKind}
                                </div>
                                <div className={`px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-widest border ${
                                  isCancelled ? "bg-red-500/10 border-red-500/20 text-red-200" :
                                  isCancelReq ? "bg-amber-500/10 border-amber-500/20 text-amber-200" :
                                  isUsed ? "bg-white/10 border-white/10 text-white/70" :
                                  "bg-emerald-500/10 border-emerald-500/20 text-emerald-200"
                                }`}>
                                  {badgeStatus}
                                </div>
                              </div>

                              <div className="mt-3 text-xl font-black leading-tight truncate">
                                {a.title || (kind === "barra" ? "Compra de Barra" : "Entrada")}
                              </div>

                              <div className="mt-2 text-[11px] text-white/60">
                                {(a.date_text || "Fecha a confirmar")} · {(a.venue || "Venue")} · {(a.city || "Ciudad")}
                              </div>

                              <div className="mt-2 text-[10px] text-white/40 font-black uppercase tracking-widest">
                                Orden #{a.order_id}
                              </div>
                            </div>
                          </div>

                          <div className="px-5 pb-5">
                            <div className="flex flex-col md:flex-row gap-5 items-start md:items-center justify-between">
                              {/* QR */}
                              <div className="flex items-center gap-4">
                                <div className="w-40 h-40 rounded-3xl bg-white p-2 flex items-center justify-center">
                                  {qrPayload ? (
                                    <img
                                      src={qrImgUrl(qrPayload, 220)}
                                      alt="QR"
                                      className="w-full h-full object-contain"
                                    />
                                  ) : (
                                    <div className="text-[10px] text-black/60 font-black uppercase tracking-widest">
                                      Sin QR
                                    </div>
                                  )}
                                </div>

                                <div className="space-y-2">
                                  <button
                                    onClick={() => downloadQrPng(qrPayload, `ticketpro_${badgeKind.toLowerCase()}_${a.id}.png`, 520)}
                                    disabled={!qrPayload}
                                    className="px-4 py-2 rounded-2xl text-[9px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 text-white disabled:opacity-40"
                                  >
                                    Descargar QR
                                  </button>

                                  <button
                                    onClick={async () => {
                                      try {
                                        const to = prompt("Transferir compra a este email:", "");
                                        if (!to) return;
                                        await transferOrder({ order_id: a.order_id, to_email: to });
                                        alert("Transferencia solicitada. El nuevo titular verá la compra en Mis Tickets.");
                                        await loadMyAssets();
                                      } catch (e) {
                                        alert(e?.message || "No se pudo transferir.");
                                      }
                                    }}
                                    className="px-4 py-2 rounded-2xl text-[9px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 text-white"
                                  >
                                    Transferir compra
                                  </button>

                                  <button
                                    onClick={async () => {
                                      try {
                                        const ok = confirm("Arrepentimiento: se genera una solicitud y el productor se contactará. ¿Continuar?");
                                        if (!ok) return;
                                        const reason = prompt("Motivo (opcional):", "");
                                        await requestCancel({ kind, id: a.id, order_id: a.order_id, reason: reason || "" });
                                        alert("Listo. Se notificó al productor y se contactará para el proceso.");
                                        await loadMyAssets();
                                      } catch (e) {
                                        alert(e?.message || "No se pudo solicitar arrepentimiento.");
                                      }
                                    }}
                                    className="px-4 py-2 rounded-2xl text-[9px] font-black uppercase tracking-widest bg-amber-500/10 hover:bg-amber-500/15 transition-all border border-amber-500/20 text-amber-200"
                                  >
                                    Arrepentimiento
                                  </button>
                                </div>
                              </div>

                              {/* detalle técnico */}
                              <div className="w-full md:w-auto">
                                <div className="p-4 rounded-3xl bg-black/30 border border-white/10 text-[11px] text-white/60 leading-relaxed">
                                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">
                                    Detalle
                                  </div>
                                  <div>• ID: <span className="text-white/80 font-black">{a.id}</span></div>
                                  <div>• Tipo: <span className="text-white/80 font-black">{badgeKind}</span></div>
                                  <div>• Estado: <span className="text-white/80 font-black">{badgeStatus}</span></div>
                                  {a.used_at ? <div>• Usado: <span className="text-white/80 font-black">{String(a.used_at)}</span></div> : null}
                                  {a.created_at ? <div>• Creado: <span className="text-white/80 font-black">{String(a.created_at)}</span></div> : null}
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })()
            )}
          </div>
        )}

{view === "success" && purchaseData && (
          <div className="pt-0 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
            <div className="max-w-3xl mx-auto">
              <div className={`p-10 rounded-[2.5rem] ${UI.card} text-center`}>
                <div className="w-16 h-16 rounded-3xl bg-indigo-600/20 border border-indigo-600/30 flex items-center justify-center mx-auto mb-6">
                  <CheckCircle2 className="text-indigo-300" size={24} />
                </div>
                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                  Compra confirmada (demo)
                </div>
                <div className="text-3xl font-black uppercase italic mt-2 mb-4">
                  ¡Listo! Tu QR está listo
                </div>
                <div className="text-[12px] text-neutral-400 leading-relaxed mb-8">
                  Este es un flujo demo. Luego se conecta a issued_tickets + antifraud + PDF.
                </div>

                <div className="p-6 rounded-3xl bg-white/5 border border-white/10 flex flex-col md:flex-row items-center gap-6 mb-8">
                  <div className="w-24 h-24 rounded-3xl bg-white/5 border border-white/10 flex items-center justify-center">
                    <QrCode size={42} className="text-indigo-300" />
                  </div>

                  <div className="flex-1 space-y-4 text-center md:text-left">
                    <div>
                      <div className="text-[9px] font-black text-neutral-500 uppercase tracking-widest">
                        Titular de Entrada
                      </div>
                      <div className="text-xl font-black uppercase">{purchaseData?.user.fullName}</div>
                    </div>

                    <div>
                      <div className="text-[9px] font-black text-neutral-500 uppercase tracking-widest">
                        Ticket x{purchaseData?.quantity}
                      </div>
                      <div className="text-xl font-black text-indigo-400 italic uppercase leading-none">
                        {purchaseData?.event.title}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Tickets emitidos (1 QR por entrada) */}
                <div className="mb-8">
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-3">
                    Tus QRs ({purchaseData?.tickets?.length || 0})
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {(purchaseData?.tickets || []).map((t, idx) => (
                      <div key={t.ticket_id || idx} className="p-5 rounded-3xl bg-white/5 border border-white/10 flex items-center gap-4">
                        <div className="w-14 h-14 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center">
                          <QrCode className="text-indigo-300" size={22} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-[10px] font-black uppercase tracking-widest text-neutral-400">
                            Ticket #{idx + 1}
                          </div>
                          <div className="text-[12px] font-mono text-white truncate">
                            {t.ticket_id}
                          </div>
                          <div className="text-[10px] text-neutral-500 truncate">
                            {t.qr_payload}
                          </div>
                        </div>
                        <button
                          onClick={() => navigator.clipboard?.writeText(t.qr_payload || t.ticket_id || "")}
                          className="px-3 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest"
                        >
                          Copiar
                        </button>
                      </div>
                    ))}
                  </div>

                  {!purchaseData?.tickets?.length && (
                    <div className="text-[11px] text-neutral-500 mt-3">
                      (Demo) Aún no hay tickets emitidos.
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <button
                    onClick={() => {
                      const tickets = (purchaseData?.tickets || []).map((t, i) => ({
                        ...t,
                        label: `Ticket #${i + 1}`,
                        // Para imprimir algo lindo en el PDF
                        title: purchaseData?.event?.title || purchaseData?.event_title || "",
                        venue: purchaseData?.event?.venue || purchaseData?.event_venue || "",
                        city: purchaseData?.event?.city || purchaseData?.event_city || "",
                        date_text: purchaseData?.event?.date_text || purchaseData?.event_date_start || "",
                        qr_payload: t.qr_payload || t.ticket_id || t.ticketId || t.id,
                      }));

                      openPrintableTicketsPdf({
                        title: purchaseData?.event?.title ? `Tickets — ${purchaseData.event.title}` : "Mis Tickets",
                        holder: purchaseData?.user?.fullName || checkoutForm.fullName || "",
                        tickets,
                        config: { cols: 2, qrSize: 320 },
                      });
                    }}
                    className="flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 p-5 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all"
                  >
                    <Download size={16} /> Descargar PDF
                  </button>
                  <button className="flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 p-5 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all">
                    <Share2 size={16} /> Compartir
                  </button>
                </div>

                <button
                  onClick={() => {
                    setView("public");
                    setSelectedEvent(null);
                  }}
                  className="w-full text-[10px] font-black text-indigo-400 uppercase tracking-[0.2em] hover:text-white transition-colors mt-8"
                >
                  Volver a la cartelera
                </button>
              </div>
            </div>
          </div>
        )}
      </main>

      <Footer />

      {isEditing && (
        <EditorModal
          editFormData={editFormData}
          setEditFormData={setEditFormData}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          setIsEditing={setIsEditing}
          saveEvent={saveEvent}
        />
      )}

<GoogleLoginModal
        open={loginRequired}
        onClose={closeLoginModal}
        googleClientId={googleClientId}
        onLoggedIn={async (u) => {
          setMe(u);
          await refreshMe();
          setLoginRequired(false);

          const method = pendingCheckout?.method;
          const goto = pendingCheckout?.goto;
          setPendingCheckout(null);

          if (goto === "myTickets") {
            setView("myTickets");
            setTimeout(() => {
              try { loadMyAssets(); } catch (e) {}
            }, 0);
            return;
          }

          if (method) setTimeout(() => handleCheckout(method), 0);
        }}
      />

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
        html, body { width: 100%; overflow-x: hidden; }
        body { font-family: 'Inter', sans-serif; background: #050508; }
        #root { width: 100%; overflow-x: hidden; }
        .no-scrollbar::-webkit-scrollbar { display: none; }
        .no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-thumb { background: #4f46e5; border-radius: 10px; }
        input[type=number]::-webkit-inner-spin-button,
        input[type=number]::-webkit-outer-spin-button {
          -webkit-appearance: none;
          margin: 0;
        }
      `}</style>

    {/* Terms & Conditions Modal */}
    {showTermsModal && (
      <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center px-4">
        <div className="bg-gray-900 rounded-xl max-w-lg w-full max-h-[80vh] flex flex-col">
          <div className="p-4 border-b border-gray-700 text-lg font-semibold">
            Términos y Condiciones
          </div>

          <div className="p-4 overflow-y-auto text-sm text-gray-300 space-y-3">
            <p>Al crear y publicar un evento en Ticketera, el productor declara que cuenta con los derechos necesarios.</p>
            <p>Ticketera actúa como intermediario tecnológico.</p>
            <p>El productor es responsable de la información cargada.</p>
            <p>El alias de cobro será usado para liquidaciones.</p>
          </div>

          <div className="p-4 border-t border-gray-700 flex justify-end gap-3">
            <button
              onClick={() => setShowTermsModal(false)}
              className="px-4 py-2 text-gray-400"
            >
              Cancelar
            </button>

            <button
              onClick={() => {
                setEditFormData({
                  ...editFormData,
                  accept_terms: true,
                });
                setShowTermsModal(false);
              }}
              className="bg-violet-600 px-4 py-2 rounded-lg text-white"
            >
              Acepto
            </button>
          </div>
        </div>
      </div>
    )}
    </div>
);
}