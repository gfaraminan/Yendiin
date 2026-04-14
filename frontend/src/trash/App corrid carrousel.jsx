import React, { useEffect, useState } from "react";
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

// --- Pricing & Flyer helpers (responsive public UI) ---
const getMinPositivePrice = (ev) => {
  const items = Array.isArray(ev?.items) ? ev.items : [];
  const prices = items
    .map((it) => Number(it?.price ?? 0))
    .filter((p) => Number.isFinite(p) && p > 0);
  if (!prices.length) return null;
  return Math.min(...prices);
};

const getPriceLabel = (ev) => {
  const min = getMinPositivePrice(ev);
  return min == null ? "Consultar" : `Desde ${formatMoney(min)}`;
};

const FALLBACK_FLYER_SVG =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(`
  <svg xmlns='http://www.w3.org/2000/svg' width='1200' height='800'>
    <defs>
      <linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>
        <stop offset='0' stop-color='#0b0b10'/>
        <stop offset='0.55' stop-color='#111827'/>
        <stop offset='1' stop-color='#4f46e5'/>
      </linearGradient>
      <radialGradient id='r' cx='75%' cy='30%' r='55%'>
        <stop offset='0' stop-color='rgba(255,255,255,0.18)'/>
        <stop offset='1' stop-color='rgba(255,255,255,0)'/>
      </radialGradient>
    </defs>
    <rect width='100%' height='100%' fill='url(#g)'/>
    <rect width='100%' height='100%' fill='url(#r)'/>
    <text x='70' y='170' fill='rgba(255,255,255,0.9)' font-size='56' font-family='Arial' font-weight='800'>TICKETERA</text>
    <text x='70' y='240' fill='rgba(255,255,255,0.95)' font-size='72' font-family='Arial' font-weight='900' font-style='italic'>TicketPro</text>
    <text x='70' y='320' fill='rgba(255,255,255,0.55)' font-size='28' font-family='Arial' font-weight='700' letter-spacing='4'>EVENTO · IMAGEN NO DISPONIBLE</text>
  </svg>
`);

const getFlyerSrc = (ev) => {
  const src = ev?.flyer_url || ev?.hero_bg || ev?.image_url || "";
  return src || FALLBACK_FLYER_SVG;
};

// --- Mobile Featured Carousel: 1 card + "peek" + dots ---
const FeaturedCarouselMobile = ({ items = [], onOpen }) => {
  const scrollerRef = React.useRef(null);
  const [active, setActive] = React.useState(0);

  // 1 card full + peek (reduce the subtraction to show more of next card)
  const CARD_W = "calc(100vw - 3.75rem)";
  const GAP = 14;

  React.useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;

    const onScroll = () => {
      const first = el.firstElementChild;
      const cardPx = first ? first.getBoundingClientRect().width : 1;
      const idx = Math.round(el.scrollLeft / (cardPx + GAP));
      setActive(Math.max(0, Math.min(idx, items.length - 1)));
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => el.removeEventListener("scroll", onScroll);
  }, [items.length]);

  const jumpTo = (i) => {
    const el = scrollerRef.current;
    if (!el) return;
    const first = el.firstElementChild;
    const cardPx = first ? first.getBoundingClientRect().width : 0;
    el.scrollTo({ left: i * (cardPx + GAP), behavior: "smooth" });
  };

  return (
    <div className="w-full">
      <div
        ref={scrollerRef}
        className="no-scrollbar flex w-full gap-[14px] overflow-x-auto overflow-y-hidden px-4 pb-3"
        style={{ scrollSnapType: "x mandatory", WebkitOverflowScrolling: "touch" }}
      >
        {items.map((ev) => (
          <button
            key={ev.id}
            onClick={() => onOpen?.(ev)}
            className="shrink-0 text-left"
            style={{ width: CARD_W, scrollSnapAlign: "start" }}
          >
            <div className="overflow-hidden rounded-[2rem] border border-white/10 bg-white/5">
              <div className="relative h-40">
                <img
                  src={getFlyerSrc(ev)}
                  alt={ev.title}
                  className="w-full h-full object-cover opacity-90"
                  onError={(e) => {
                    e.currentTarget.src = FALLBACK_FLYER_SVG;
                  }}
                />
                <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/25 to-transparent" />
                <div className="absolute bottom-0 left-0 p-4">
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-300">
                    {ev.category} · {ev.city}
                  </div>
                  <div className="text-xl font-black uppercase italic mt-1 leading-tight">
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
                    {getPriceLabel(ev)}
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
            </div>
          </button>
        ))}
      </div>

      <div className="flex items-center justify-center gap-2">
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
                if (!r.ok || !data?.ok) throw new Error(data?.detail || "Login falló");
                onLoggedIn({
                  fullName: data.user?.name || data.user?.meaningful_name || "User",
                  email: data.user?.email || "",
                  picture: data.user?.picture || "",
                  sub: data.user?.sub,
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
            onClick={() => onLoggedIn({ fullName: "Demo User", email: "demo@ticketera.local" })}
            className={`w-full py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white ${UI.buttonGhost}`}
          >
            <Smartphone size={16} /> Continuar como Demo
          </button>

          <button
            onClick={onClose}
            className="w-full py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
          >
            Cancelar
          </button>
        </div>

        <div className="mt-6 text-[10px] text-neutral-500 leading-relaxed">
          Nota: En demo no hay pago real. El login sirve para separar usuarios y probar multi-QR.
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
  const eventSlug = editFormData?.slug || "";

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

  const [tabBusy, setTabBusy] = useState(false);
  const [tabError, setTabError] = useState("");

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
      setSellers(data?.items || data || []);
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

      await fetchJson(`/api/producer/sale-items/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      setSaleDraft({ kind: "ticket", name: "", price: 10, currency: "ARS", stock_total: "", sort_order: 1 });
      await loadSaleItems();
    } catch (e) {
      const msg = String(e?.message || e || "");
      if (msg.includes("duplicate key") || msg.includes("ux_sale_items")) {
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
      setTabError(String(e?.message || e));
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
      <div className={`w-full max-w-4xl p-8 rounded-[2.5rem] ${UI.card} text-white`}>
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

        <div className="flex gap-2 mb-8">
          {[
            { id: "info", label: "Info" },
            { id: "tickets", label: "Tickets" },
            { id: "sellers", label: "Sellers" },
          ].map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`px-3 md:px-5 py-2.5 md:py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all ${
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
        <div className="text-sm font-semibold text-white">
          Acepto Términos y Condiciones
        </div>
        <div className="text-xs text-white/70">
          Es requisito para publicar / guardar el evento{" "}
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault()
              alert("Aún no hay página pública de Términos. (Podemos agregar /terms cuando quieras)")
            }}
            className="underline text-white/80 hover:text-white"
          >
            Ver términos
          </a>
        </div>
      </div>
    </div>
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

                  {tabBusy && (
                    <div className="text-sm text-white/60 mb-3">
                      Cargando…
                    </div>
                  )}

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
                        <div className="mt-2 text-xs text-white/45">
                          Nota: el backend guarda el precio en <i>centavos</i> automáticamente.
                        </div>
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

                        {(!saleItems || saleItems.length === 0) ? (
                          <div className="text-sm text-white/50">Todavía no hay tickets.</div>
                        ) : (
                          <div className="space-y-2">
                            {saleItems.map((it) => (
                              <div key={it.id} className="flex items-center justify-between gap-3 rounded-xl bg-black/20 border border-white/10 px-3 py-2">
                                <div className="min-w-0">
                                  <div className="text-sm font-semibold truncate">{it.name}</div>
                                  <div className="text-xs text-white/50">
                                    {it.currency || "ARS"} {priceLabel(it)} · stock {it.stock_total ?? "∞"}
                                  </div>
                                </div>
                                <label className="flex items-center gap-2 text-xs text-white/70">
                                  <input
                                    type="checkbox"
                                    checked={!!it.active}
                                    onChange={(e) => toggleSaleItem(it.id, e.target.checked)}
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

                  {activeTab === "sellers" && (
                    <div className="space-y-4">
                      <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                        <div className="text-sm text-white/70 mb-2">Agregar vendedor</div>
                        <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
                          <input
                            className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                            placeholder="Código (ej: GERMAN)"
                            value={sellerDraft.code}
                            onChange={(e) => setSellerDraft({ ...sellerDraft, code: e.target.value })}
                          />
                          <input
                            className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm md:col-span-3"
                            placeholder="Nombre (ej: Germán)"
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
                      </div>

                      <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                        <div className="flex items-center justify-between mb-2">
                          <div className="text-sm text-white/70">Vendedores actuales</div>
                          <button
                            className="text-xs text-white/70 hover:text-white underline"
                            onClick={loadSellers}
                            disabled={tabBusy}
                          >
                            refrescar
                          </button>
                        </div>

                        {(!sellers || sellers.length === 0) ? (
                          <div className="text-sm text-white/50">Todavía no hay vendedores.</div>
                        ) : (
                          <div className="space-y-2">
                            {sellers.map((s) => (
                              <div key={s.id} className="flex items-center justify-between gap-3 rounded-xl bg-black/20 border border-white/10 px-3 py-2">
                                <div className="min-w-0">
                                  <div className="text-sm font-semibold truncate">{s.name}</div>
                                  <div className="text-xs text-white/50">code: {s.code}</div>
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
      </div>
    </div>
  );
};


// -------------------------
// App
// -------------------------
export default function App() {
  const [view, setView] = useState("public");
  const [me, setMe] = useState(null);
  const [googleClientId, setGoogleClientId] = useState("");
  const [loginRequired, setLoginRequired] = useState(false);
  const [pendingCheckout, setPendingCheckout] = useState(null);

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
        setSelectedEvent({
          id: data.id || data.slug,
          ...data,
          flyer_url: data.flyer_url || data.hero_bg,
        });
        setSelectedTicket((data.items || [])[0] || null);
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
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [quantity, setQuantity] = useState(1);

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
  };

  const openLoginModal = (opts = null) => {
    setPendingCheckout(opts);
    setLoginRequired(true);
  };

  const closeLoginModal = () => {
    setLoginRequired(false);
    setPendingCheckout(null);
  };

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
    if (!selectedTicket || !checkoutForm.fullName || !checkoutForm.dni || !checkoutForm.address) {
      alert("Por favor completa Nombre, DNI y Dirección.");
      return;
    }
    if (!checkoutForm.acceptTerms) {
      alert("Tenés que aceptar Términos y Condiciones para continuar.");
      return;
    }

    // login obligatorio en checkout
    if (!me) {
      openLoginModal({ method });
      return;
    }

    setLoading(true);

    try {
      const res = await fetch("/api/orders/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          tenant_id: "default",
          event_slug: selectedEvent.slug,
          sale_item_id: selectedTicket.id,
          quantity,
          payment_method: method || "DEMO",
        }),
      });

      if (res.status === 401) {
        openLoginModal({ method });
        setLoading(false);
        return;
      }

      const data = await res.json();
      if (!res.ok || !data?.ok) {
        throw new Error(data?.detail || "No se pudo crear la orden");
      }

      setPurchaseData({
        event: selectedEvent,
        ticket: selectedTicket,
        quantity,
        user: { ...checkoutForm },
        method,
        order_id: data.order_id,
        tickets: data.tickets || [],
        total_cents: data.total_cents,
      });

      setView("success");
    } catch (e) {
      console.error(e);
      alert("Error en checkout: " + (e?.message || e));
    } finally {
      setLoading(false);
    }
  };

  const openEditor = (ev = null) => {
    setIsEditing(true);
    setActiveTab("info");
    if (ev) {
      const copy = JSON.parse(JSON.stringify(ev));
      copy._is_new = false;
      setEditFormData(copy);
    } else {
      setEditFormData({
        _is_new: true,
        id: Date.now(),
        slug: "nuevo-evento",
        title: "Nuevo Evento",
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

  const saveEvent = async () => {
    if (!editFormData) return;

    if (!editFormData.accept_terms) {
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
      if (!r.ok || !data?.ok) throw new Error(data?.detail || "No se pudo guardar el evento");

      await refreshPublicEvents();

      setIsEditing(false);
      setEditFormData(null);
    } catch (e) {
      console.error(e);
      alert("Error guardando evento: " + (e?.message || (typeof e === "string" ? e : JSON.stringify(e))));
    }
  };

  // -------------------------
  // UI Components (inline / demo)
  // -------------------------
  const Header = () => {
    return (
      <header className="fixed top-0 left-0 right-0 z-50 bg-black/50 backdrop-blur-xl border-b border-white/5">
        <div className="max-w-7xl mx-auto px-4 md:px-6 py-3 md:py-5 flex items-center justify-between gap-4 md:gap-6">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 md:w-10 md:h-10 rounded-2xl bg-indigo-600 flex items-center justify-center shadow-[0_0_30px_rgba(79,70,229,0.4)]">
              <QrCode className="text-white" size={22} />
            </div>
            <div>
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                Ticketera
              </div>
              <div className="text-white font-black uppercase italic tracking-tight text-lg md:text-base">
                Ticket<span className="text-indigo-500">Pro</span>
              </div>
            </div>
          </div>

          <nav className="flex items-center gap-2">
            <button
              onClick={() => setView("public")}
              className={`px-3 md:px-5 py-2.5 md:py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all ${
                view === "public" ? "bg-indigo-600 text-white" : "bg-white/5 hover:bg-white/10"
              }`}
            >
              Cartelera
            </button>
            <button
              onClick={() => setView("producer")}
              className={`px-3 md:px-5 py-2.5 md:py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all ${
                view === "producer" ? "bg-indigo-600 text-white" : "bg-white/5 hover:bg-white/10"
              }`}
            >
              Producer
            </button>
          </nav>

          <div className="flex items-center gap-2">
            {!me ? (
              <button
                onClick={() => setLoginRequired(true)}
                className="px-5 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 text-white"
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
                  className="px-5 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 text-white"
                >
                  Salir
                </button>
              </>
            )}
          </div>
        </div>
      </header>
    );
  };

  // -------------------------
  // VIEWS
  // -------------------------
  return (
    <div className={`min-h-screen ${UI.bg} text-white`}>
      <Header />

      <main className="min-h-screen">
        {/* PUBLIC */}
        {view === "public" && (
          <div className="pt-24 md:pt-32 pb-16 md:pb-20 px-4 md:px-6 max-w-7xl mx-auto animate-in fade-in text-white overflow-x-hidden">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 md:gap-8 mb-8 md:mb-12">
              <div className="w-full">
                <h1 className="text-4xl md:text-5xl font-black uppercase italic tracking-tight leading-[0.95]">
                  Cartelera <span className="text-indigo-600">Viva</span>
                </h1>
                <p className="text-[10px] font-black uppercase tracking-widest text-neutral-500 mt-2">
                  Comprá tu ticket · QR antifraude · acceso rápido
                </p>
              </div>

              <button
                onClick={() => setView("producer")}
                className={`w-full md:w-auto px-8 py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white transition-all ${UI.button}`}
              >
                <ShieldCheck size={16} /> Ir a Producer
              </button>
            </div>

            {/* MOBILE: Destacados (1 card + peek + dots) */}
            <div className="md:hidden mb-10">
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">
                Destacados
              </div>
              <div className="text-lg font-black uppercase mb-4">Eventos recomendados</div>

              <FeaturedCarouselMobile
                items={(events || []).slice(0, 8)}
                onOpen={(ev) => {
                  setQuantity(1);
                  setCheckoutForm({ fullName: "", dni: "", address: "" });
                  openPublicEvent(ev.slug);
                }}
              />
            </div>

            {/* MOBILE: Listado compacto (sin banners gigantes) */}
            <div className="md:hidden space-y-3">
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                Todos los eventos
              </div>

              {(events || []).map((ev) => (
                <button
                  key={ev.id}
                  onClick={() => {
                    setQuantity(1);
                    setCheckoutForm({ fullName: "", dni: "", address: "" });
                    openPublicEvent(ev.slug);
                  }}
                  className="w-full text-left rounded-2xl border border-white/10 bg-white/5 hover:bg-white/10 transition-all overflow-hidden"
                >
                  <div className="flex gap-4 p-4">
                    <div className="w-20 h-20 rounded-2xl overflow-hidden border border-white/10 shrink-0">
                      <img
                        src={getFlyerSrc(ev)}
                        alt={ev.title}
                        className="w-full h-full object-cover opacity-90"
                        onError={(e) => {
                          e.currentTarget.src = FALLBACK_FLYER_SVG;
                        }}
                      />
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="text-[9px] font-black uppercase tracking-widest text-neutral-400 truncate">
                        {ev.category} · {ev.city}
                      </div>
                      <div className="text-base font-black uppercase italic leading-tight mt-1 truncate">
                        {ev.title}
                      </div>

                      <div className="mt-2 flex items-center gap-2 text-[11px] text-neutral-300">
                        <Calendar size={14} /> <span className="truncate">{ev.date_text}</span>
                      </div>

                      <div className="mt-1 flex items-center gap-2 text-[11px] text-neutral-400">
                        <MapPin size={14} /> <span className="truncate">{ev.venue || "Venue"}</span>
                      </div>

                      <div className="mt-2 flex items-center justify-between">
                        <div className="text-sm font-black text-indigo-300 italic">
                          {getPriceLabel(ev)}
                        </div>
                        <div className="text-[10px] font-black text-white/80">
                          {(ev.stock_total || 0) - (ev.stock_sold || 0)}/{ev.stock_total || 0}
                        </div>
                      </div>
                    </div>
                  </div>
                </button>
              ))}
            </div>

            {/* DESKTOP/TABLET: grilla original */}
            <div className="hidden md:grid grid-cols-1 md:grid-cols-3 gap-8">
              {events.map((ev) => (
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
                      src={getFlyerSrc(ev)}
                      alt={ev.title}
                      className="w-full h-full object-cover opacity-90"
                      onError={(e) => {
                        e.currentTarget.src = FALLBACK_FLYER_SVG;
                      }}
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
                      <div className="text-lg font-black text-indigo-400 italic">
                        {getPriceLabel(ev)}
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
        {view === "detail" && selectedEvent && (
          <div className="pt-32 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
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
                    src={selectedEvent.flyer_url}
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
                      className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 text-[12px] font-bold"
                    />
                  </div>

                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">
                      DNI
                    </div>
                    <input
                      value={checkoutForm.dni}
                      onChange={(e) => setCheckoutForm({ ...checkoutForm, dni: e.target.value })}
                      className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 text-[12px] font-bold"
                    />
                  </div>

                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">
                      Dirección
                    </div>
                    <input
                      value={checkoutForm.address}
                      onChange={(e) => setCheckoutForm({ ...checkoutForm, address: e.target.value })}
                      className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 text-[12px] font-bold"
                    />
                  </div>

                  <div className="flex items-center justify-between gap-4 pt-2">
                    <div>
                      <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                        Cantidad
                      </div>
                      <div className="flex items-center gap-2 mt-2">
                        <button
                          onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                          className="w-10 h-10 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 flex items-center justify-center"
                        >
                          <Minus size={16} />
                        </button>
                        <div className="w-10 text-center text-lg font-black">{quantity}</div>
                        <button
                          onClick={() => setQuantity((q) => q + 1)}
                          className="w-10 h-10 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 flex items-center justify-center"
                        >
                          <Plus size={16} />
                        </button>
                      </div>
                    </div>

                    <div className="text-right">
                      <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                        Total
                      </div>
                      <div className="text-2xl font-black text-indigo-400 italic mt-1">
                        {formatMoney((selectedTicket?.price || 0) * quantity)}
                      </div>
                    </div>
                  </div>

                  <div className="mt-6 p-4 rounded-2xl bg-white/5 border border-white/10">
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={checkoutForm.acceptTerms}
                        onChange={(e) => setCheckoutForm({ ...checkoutForm, acceptTerms: e.target.checked })}
                      />
                      <div className="text-[11px] text-neutral-300 leading-relaxed">
                        Acepto los <span className="text-white font-bold">Términos y Condiciones</span> y la política de privacidad.
                      </div>
                    </label>
                  </div>

                  <div className="grid grid-cols-1 gap-3 mt-6">
                    <button
                      onClick={() => handleCheckout("card")}
                      disabled={loading}
                      className={`w-full py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white transition-all flex items-center justify-center gap-2 ${UI.button}`}
                    >
                      {loading ? <Loader2 className="animate-spin" size={16} /> : <Wallet size={16} />}
                      Pagar con tarjeta
                    </button>

                    <button
                      onClick={() => handleCheckout("mp")}
                      disabled={loading}
                      className="w-full py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 flex items-center justify-center gap-2"
                    >
                      <Wallet size={16} /> Pagar con Mercado Pago
                    </button>

                    <button
                      onClick={() => handleCheckout("cash")}
                      disabled={loading}
                      className="w-full py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 flex items-center justify-center gap-2"
                    >
                      <ShoppingCart size={16} /> Reservar (pago en puerta)
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
        )}

        {/* PRODUCER (demo) */}
        {view === "producer" && (
          <div className="pt-32 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
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
              {/* Lista de eventos (demo) */}
              <div className={`p-8 rounded-[2.5rem] ${UI.card} lg:col-span-2`}>
                <div className="flex items-start justify-between gap-6 mb-8">
                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                      Eventos
                    </div>
                    <div className="text-2xl font-black uppercase italic">Gestión</div>
                    <div className="text-[11px] text-neutral-400 mt-2">
                      UI demo de eventos (state local). El dropdown de arriba ya consume eventos reales con ventas.
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
                  {events.map((ev) => (
                    <div
                      key={ev.id}
                      className="p-6 rounded-3xl bg-white/5 border border-white/10 flex flex-col md:flex-row gap-6 items-start md:items-center justify-between"
                    >
                      <div className="flex items-center gap-4">
                        <img
                          src={ev.flyer_url}
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
        {view === "success" && purchaseData && (
          <div className="pt-32 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
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
                  <button className="flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 p-5 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all">
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
<style>{`
  .no-scrollbar::-webkit-scrollbar { display: none; }
  .no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
`}</style>


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
        onLoggedIn={(u) => {
          setMe(u);
          setLoginRequired(false);
          const method = pendingCheckout?.method;
          setPendingCheckout(null);
          if (method) setTimeout(() => handleCheckout(method), 0);
        }}
      />

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
        body { font-family: 'Inter', sans-serif; background: #050508; overflow-x: hidden; }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-thumb { background: #4f46e5; border-radius: 10px; }
        input[type=number]::-webkit-inner-spin-button, input[type=number]::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
      `}</style>
    </div>
  );
}