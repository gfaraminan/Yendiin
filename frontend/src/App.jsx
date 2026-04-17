
// Wizard Draft & Steps Helpers
const EVENT_DRAFT_KEY = "ticketera.newEventDraft.v1";
const saveDraft = (data)=>{try{localStorage.setItem(EVENT_DRAFT_KEY,JSON.stringify({...data,_savedAt:Date.now()}));}catch(e){}}
const loadDraft = ()=>{try{const r=localStorage.getItem(EVENT_DRAFT_KEY);return r?JSON.parse(r):null;}catch{return null}}
const clearDraft = ()=>{localStorage.removeItem(EVENT_DRAFT_KEY)};

import React, { useEffect, useMemo, useRef, useState } from "react";

import {
  Loader2,
  MapPin,
  Ticket,
  Search,
  ChevronLeft,
  CreditCard,
  CheckCircle2,
  Calendar,
  User,
  Share2,
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
  LinkIcon,
  RefreshCw,
} from "lucide-react";
import { FALLBACK_FLYER, UI } from "./app/constants";
import FeaturedCarousel from "./components/FeaturedCarousel";
import AppFooter from "./components/AppFooter";
import SoldOutRibbon from "./components/SoldOutRibbon";
import PublicHomeView from "./views/PublicHomeView";
import EventDetailView from "./views/EventDetailView";
import PurchaseSuccessView from "./views/PurchaseSuccessView";
import MyTicketsView from "./views/MyTicketsView";
import { makeBrandPageTitle, resolveBrandConfig } from "./config/brand";
import { resolveFeatureFlags } from "./config/features";
import { resolveLegalConfig } from "./config/legal";
import { defaultRuntimeConfig, resolvePublicTenant } from "./config/runtime";
import {
  downloadQrPng,
  downloadTicketsPdf,
  flyerSrc,
  normalizeAssetUrl,
  priceLabelForEvent,
  qrImgUrl,
  readJsonOrText,
  sendTicketsByEmail,
  slugify,
} from "./app/helpers";
import { eventSalesProgress, formatEventDateText, isEventSoldOut } from "./app/eventSales";
import { fetchPublicRuntimeConfig, resolveCheckoutSuccessState, resolveRuntimeConfigState } from "./app/runtimeBootstrap";
import { parseAppLocation } from "./app/navigation";
import { buildEventGoogleMapsLink, buildUberLink, formatMoneyAr, normalizeErrorDetail } from "./app/formatters";
import { buildCheckoutBlockReason, buildOrderPayload, resolveCheckoutServicePct, validateCheckoutForm } from "./app/checkout";
import { createMpPreference } from "./app/payments";
import { getOwnerSummary, getProducerDashboard, listProducerEvents } from "./app/producerApi";
import { buildStaffPosPayload, buildValidateQrPayload, normalizeStaffPosResult } from "./app/staff";
import { resolveFlaggedViews } from "./app/flagViews";

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
};




// -------------------------
// Helpers (demo / placeholders)
// -------------------------
const linkifyPlainText = (value) => {
  const text = String(value || "");
  const urlRegex = /(https?:\/\/[^\s]+|(?:www\.)?maps\.app\.goo\.gl\/[^\s]+)/gi;
  const isUrl = /^(https?:\/\/\S+|(?:www\.)?maps\.app\.goo\.gl\/\S+)$/i;
  const parts = text.split(urlRegex);

  return parts.map((part, idx) => {
    if (!part) return <React.Fragment key={`desc-empty-${idx}`} />;

    if (isUrl.test(part)) {
      const href = /^https?:\/\//i.test(part) ? part : `https://${part.replace(/^\/*/, "")}`;
      return (
        <a
          key={`desc-link-${idx}`}
          href={href}
          target="_blank"
          rel="noreferrer"
          className="underline decoration-indigo-400/70 text-indigo-300 hover:text-indigo-200 break-all"
        >
          {part}
        </a>
      );
    }

    return <React.Fragment key={`desc-text-${idx}`}>{part}</React.Fragment>;
  });
};

const SafeMailIcon = ({ size = 16 }) => <span style={{ fontSize: size }}>✉</span>;
const SafeSocialIcon = ({ size = 16 }) => <span style={{ fontSize: size }}>🐦</span>;

const GoogleLoginModal = ({ open, onClose, onLoggedIn, googleClientId, featureFlags }) => {
  const [ready, setReady] = useState(false);
  const googleButtonRef = useRef(null);

  // Method: "google" | "email"
  const allowGoogleLogin = Boolean(featureFlags?.googleLogin);
  const allowMagicLinkLogin = Boolean(featureFlags?.magicLinkLogin);
  const [loginMethod, setLoginMethod] = useState(allowGoogleLogin ? "google" : "email");

  // Email magic link state
  const [email, setEmail] = useState("");
  const [emailSending, setEmailSending] = useState(false);
  const [emailSent, setEmailSent] = useState(false);
  const [emailError, setEmailError] = useState("");

  // Helper: parse JSON or fallback to text
  const readJsonOrText = async (r) => {
    const ct = (r.headers.get("content-type") || "").toLowerCase();
    if (ct.includes("application/json")) return await r.json();
    const t = await r.text();
    try { return JSON.parse(t); } catch { return { detail: t }; }
  };

  useEffect(() => {
    if (!open) return;

    // Reset UI every time it opens
    setEmailSent(false);
    setEmailError("");
    setEmailSending(false);
    // Cargar Google Identity script sólo si vamos a mostrar Google (y tenemos client_id)
    const ensureScript = () =>
      new Promise((resolve, reject) => {
        if (window.google?.accounts?.id) return resolve(true);
        const id = "google-identity";
        if (document.getElementById(id)) {
          // esperar a que cargue
          const check = () => {
            if (window.google?.accounts?.id) resolve(true);
            else setTimeout(check, 50);
          };
          check();
          return;
        }
        const s = document.createElement("script");
        s.id = id;
        s.src = "https://accounts.google.com/gsi/client";
        s.async = true;
        s.defer = true;
        s.onload = () => resolve(true);
        s.onerror = () => reject(new Error("No se pudo cargar Google"));
        document.head.appendChild(s);
      });

    (async () => {
      try {
        // Si no hay client_id, igual dejamos el modal usable por Email
        if (allowGoogleLogin && googleClientId) {
          await ensureScript();
        }
        setReady(true);

        // Inicializa Google Identity si hay client_id
        if (allowGoogleLogin && googleClientId && window.google?.accounts?.id) {
          window.google.accounts.id.initialize({
            client_id: googleClientId,
            use_fedcm_for_prompt: false,
            use_fedcm_for_button: false,
            button_auto_select: false,
            itp_support: true,
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
        }
      } catch (e) {
        console.error(e);
        setReady(false);
      }
    })();
  }, [open, googleClientId, allowGoogleLogin]);

  useEffect(() => {
    if (!open || !allowGoogleLogin || loginMethod !== "google") return;
    if (!googleClientId || !ready || !window.google?.accounts?.id || !googleButtonRef.current) return;

    try {
      googleButtonRef.current.innerHTML = "";
      window.google.accounts.id.renderButton(googleButtonRef.current, {
        type: "standard",
        theme: "filled_black",
        size: "large",
        text: "continue_with",
        shape: "pill",
        logo_alignment: "left",
        width: 360,
      });
    } catch (e) {
      console.error(e);
    }
  }, [open, loginMethod, googleClientId, ready, allowGoogleLogin]);

  useEffect(() => {
    if (!allowGoogleLogin && allowMagicLinkLogin) setLoginMethod("email");
    if (allowGoogleLogin && !allowMagicLinkLogin) setLoginMethod("google");
  }, [allowGoogleLogin, allowMagicLinkLogin]);

  const sendMagicLink = async () => {
    const em = String(email || "").trim().toLowerCase();
    if (!em || !em.includes("@")) {
      setEmailError("Ingresá un email válido.");
      return;
    }
    setEmailError("");
    setEmailSent(false);
    setEmailSending(true);
    try {
      const r = await fetch("/api/auth/email/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email: em }),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error((data && data.detail) || "No se pudo enviar el link");

      setEmailSent(true);
    } catch (e) {
      console.error(e);
      setEmailError(e?.message ? String(e.message) : "No se pudo enviar el link. Probá de nuevo en un minuto.");
    } finally {
      setEmailSending(false);
    }
  };

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
          {allowGoogleLogin && loginMethod === "google" && (
            <>
              <div className="flex items-center justify-center">
                <div className="rounded-full overflow-hidden leading-none" ref={googleButtonRef} />
              </div>

              {!googleClientId && (
                <div className="text-[11px] text-neutral-400 text-center">
                  Falta configurar <span className="text-white/90 font-bold">GOOGLE_CLIENT_ID</span> en el backend.
                </div>
              )}

              {googleClientId && !ready && (
                <div className="text-[11px] text-neutral-400 text-center">
                  Cargando Google…
                </div>
              )}

              {allowMagicLinkLogin && (
                <button
                  onClick={() => setLoginMethod("email")}
                  className="w-full min-h-[44px] rounded-full bg-white/10 hover:bg-white/15 border border-white/10 transition-all flex items-center justify-center px-5"
                >
                  <span className="text-[13px] sm:text-[14px] font-black uppercase tracking-wide leading-none text-white/90">Continuar con Mail</span>
                </button>
              )}
            </>
          )}

          {allowMagicLinkLogin && loginMethod === "email" && (
            <>
              <div className="space-y-2">
                <div className="text-[10px] font-black uppercase tracking-widest text-neutral-400">
                  Magic link
                </div>

                <div className="flex gap-2">
                  <div className="flex-1">
                    <input
                      value={email}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        setEmailError("");
                        setEmailSent(false);
                      }}
                      placeholder="tu@email.com"
                      className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm"
                      autoComplete="email"
                      inputMode="email"
                    />
                  </div>

                  <button
                    onClick={sendMagicLink}
                    disabled={emailSending}
                    className={`px-4 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest border transition-all flex items-center gap-2 ${
                      emailSending
                        ? "bg-white/5 border-white/10 opacity-70"
                        : "bg-indigo-600 hover:bg-indigo-500 border-white/10"
                    }`}
                  >
                    {emailSending ? <Loader2 className="animate-spin" size={16} /> : <SafeMailIcon size={16} />}
                    Enviar
                  </button>
                </div>

                {!!emailError && (
                  <div className="text-[11px] text-red-300">{emailError}</div>
                )}

                {emailSent && (
                  <div className="text-[11px] text-emerald-300">
                    Listo ✅ Te mandamos un link. Abrilo desde tu correo para iniciar sesión.
                  </div>
                )}

                <div className="text-[11px] text-neutral-400">
                  El link vence en pocos minutos. Si no llega, revisá spam/promociones.
                </div>
              </div>

              {allowGoogleLogin && (
                <button
                  onClick={() => setLoginMethod("google")}
                  className="w-full py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
                >
                  Volver a Google
                </button>
              )}
            </>
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
// (demo)
// -------------------------
const EditorModal = ({
  editFormData,
  setEditFormData,
  activeTab,
  setActiveTab,
  setIsEditing,
  saveEvent,
  onFlyerPicked,
  currentView,
  onOpenStaffAccess,
  legalConfig,
}) => {
  if (!editFormData) return null;

  const slugLocked = !editFormData?._is_new;

  const onClose = () => {
    setIsEditing(false);
    setEditFormData(null);
  };
  // --- Tickets (sale-items) & Sellers helpers ---
  const tenantId = editFormData?.tenant_id || defaultRuntimeConfig.publicTenant;
  // Para evento nuevo, el slug NO se considera válido hasta que el backend lo persista.
  const eventSlug = editFormData?._is_new ? "" : (editFormData?.slug || editFormData?.event_slug || editFormData?.eventSlug || "");

  const sellerCodeOf = (s) => String(s?.code || s?.pin || "").trim();

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
  const [editingSaleItemId, setEditingSaleItemId] = useState(null);
  const [saleEditDraft, setSaleEditDraft] = useState({
    price: "",
    stock_total: "",
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
  const [courtesyIssueResult, setCourtesyIssueResult] = useState(null);
  const [posIssueResult, setPosIssueResult] = useState(null);
  const [posDraft, setPosDraft] = useState({
    sale_item_id: "",
    quantity: "1",
    payment_method: "cash",
    seller_code: "",
    buyer_name: "",
    buyer_email: "",
    buyer_phone: "",
    buyer_dni: "",
    note: "",
  });

  // -------------------------
  // Wizard (solo para evento nuevo)
  // -------------------------
  const isNewEvent = !!editFormData?._is_new;

  const [wizardStep, setWizardStep] = useState(0); // 0..4
  const [wizardTouched, setWizardTouched] = useState(false);
  const [flyerPreview, setFlyerPreview] = useState("");
  const [mpOauthBusy, setMpOauthBusy] = useState(false);

  
  const [flyerFilePending, setFlyerFilePending] = useState(null);
// Resetea wizard cuando cambia el evento
  useEffect(() => {
    if (isNewEvent) {
      setWizardStep(0);
      setWizardTouched(false);
      setFlyerPreview(editFormData?.flyer_url || "");
      // Asegura default de términos visible desde el paso 1
      if (typeof editFormData?.accept_terms === "undefined") {
        setEditFormData((p) => ({ ...p, accept_terms: true }));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editFormData?.id, editFormData?._is_new]);

  const clamp = (n, a, b) => Math.max(a, Math.min(b, n));

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
    "Flyer con preview + descripción + ubicación",
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
    const settlementMode = String(editFormData?.settlement_mode || "manual_transfer").trim();

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
      if (settlementMode !== "mp_split" && !payout) e.push("Falta el alias de cobro (CBU/alias/MercadoPago).");
      if (!cuit) e.push("Falta el CUIT.");

      // Venue/ubicación/flyer forman parte del alta (para evitar pasos mezclados)
      if (!city) e.push("Falta la ciudad.");
      if (!venue) e.push("Falta el venue/lugar.");
      if (!address) e.push("Falta la dirección.");

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


  const uploadFlyerForEvent = async (slug, file) => {
    const fd = new FormData();
    fd.append("file", file);

    const r = await fetch(
      `/api/producer/events/${encodeURIComponent(slug)}/flyer?tenant_id=${encodeURIComponent(tenantId)}`,
      { method: "POST", body: fd, credentials: "include" }
    );
    const data = await readJsonOrText(r);
    if (!r.ok) throw new Error(normalizeErrorDetail(data, r, "No se pudo subir el flyer"));
    return data?.url;
  };

  const onPickFlyerFile = async (file) => {
    if (!file) return;

    // Preview inmediata (local)
    const localUrl = URL.createObjectURL(file);
    setFlyerPreview(localUrl);

    // Guardamos el file por si todavía no existe el evento (alta)
    setFlyerFilePending(file);

    try {
      if (typeof onFlyerPicked === "function") onFlyerPicked(file);
    } catch (_) {}

    // Si el evento ya existe, subimos ya y guardamos URL persistente
    const slug = editFormData?.slug;
    const isUpdate = editFormData?._is_new === false;
    if (slug && isUpdate) {
      try {
        const url = await uploadFlyerForEvent(slug, file);
        setEditFormData((p) => ({ ...p, flyer_url: url }));
        if (typeof setFlyerFilePending === "function") setFlyerFilePending(null);
        setFlyerPreview(url);
      } catch (e) {
        console.error(e);
        alert("No se pudo subir el flyer: " + (e?.message || e));
      }
    }
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

  const connectMpOauth = async () => {
    try {
      setMpOauthBusy(true);
      const tenantIdForOauth = editFormData?.tenant_id || defaultRuntimeConfig.publicTenant;
      const r = await fetch(`/api/payments/mp/oauth/start?tenant=${encodeURIComponent(tenantIdForOauth)}`, {
        credentials: "include",
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error((data && data.detail) || "No se pudo iniciar OAuth de Mercado Pago");

      const authUrl = String(data?.auth_url || "").trim();
      if (!authUrl) throw new Error("No se recibió auth_url de Mercado Pago");

      const popup = window.open(authUrl, "mp_oauth", "width=560,height=760");
      if (!popup) throw new Error("No se pudo abrir la ventana de autorización. Revisá el bloqueador de popups.");

      await new Promise((resolve, reject) => {
        let done = false;
        let closeGraceTimeoutId = 0;
        const cleanup = () => {
          if (done) return;
          done = true;
          window.clearTimeout(timeoutId);
          window.clearTimeout(closeGraceTimeoutId);
          window.clearInterval(popupWatcher);
          window.removeEventListener("message", onMessage);
        };

        const timeoutId = window.setTimeout(() => {
          cleanup();
          reject(new Error("Tiempo de espera agotado para la autorización de Mercado Pago"));
        }, 120000);

        const onMessage = (ev) => {
          const msg = ev?.data || {};
          if (!msg || msg.type !== "mp_oauth_success") return;
          const userId = String(msg.user_id || "").trim();
          cleanup();
          if (!userId) {
            reject(new Error("Mercado Pago respondió sin user_id"));
            return;
          }
          setEditFormData((prev) => (prev ? { ...prev, mp_collector_id: userId } : prev));
          resolve(true);
        };

        const popupWatcher = window.setInterval(() => {
          if (!popup.closed || done) return;
          window.clearTimeout(closeGraceTimeoutId);
          // Evita falso negativo: MP puede cerrar popup justo después de postMessage.
          closeGraceTimeoutId = window.setTimeout(() => {
            if (done) return;
            cleanup();
            reject(new Error("La ventana de autorización se cerró antes de completar el proceso"));
          }, 700);
        }, 500);

        window.addEventListener("message", onMessage);
      });

      alert("Cuenta de Mercado Pago conectada. Se cargó el Collector ID automáticamente.");
    } catch (e) {
      const rawMsg = String(e?.message || e || "").trim();
      const msg = rawMsg.includes("mp_oauth_client_id_not_configured")
        ? "OAuth de Mercado Pago no está configurado todavía en este ambiente. Podés seguir en modo manual y transferir al productor."
        : rawMsg.includes("mp_oauth_client_secret_not_configured")
        ? "Falta configurar credenciales OAuth de Mercado Pago en este ambiente. Podés seguir en modo manual."
        : rawMsg.includes("mp_oauth_redirect_uri_not_configured")
        ? "Falta configurar la URL de retorno OAuth de Mercado Pago en este ambiente. Podés seguir en modo manual."
        : `No se pudo conectar Mercado Pago: ${rawMsg || "error desconocido"}`;
      alert(msg);
    } finally {
      setMpOauthBusy(false);
    }
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
      const saleItemsUrl = currentView === "supportAI" ? `/api/support/ai/admin/sale-items?${qs.toString()}` : `/api/producer/sale-items?${qs.toString()}`;
      const data = await fetchJson(saleItemsUrl);
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
      const rawList =
        Array.isArray(data) ? data :
        Array.isArray(data?.sellers) ? data.sellers :
        Array.isArray(data?.items) ? data.items :
        Array.isArray(data?.rows) ? data.rows :
        [];
      const list = rawList.map((s) => ({
        ...s,
        code: String(s?.code || s?.pin || "").trim(),
      }));
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

  useEffect(() => {
    if (!saleItems?.length) return;
    setPosDraft((prev) => {
      if (String(prev.sale_item_id || "").trim()) return prev;
      const firstId = saleItems[0]?.id != null ? String(saleItems[0].id) : "";
      return { ...prev, sale_item_id: firstId };
    });
  }, [saleItems]);

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

      const createUrl = currentView === "supportAI" ? `/api/support/ai/admin/sale-items/create?${qsCreate.toString()}` : `/api/producer/sale-items/create?${qsCreate.toString()}`;
      await fetchJson(createUrl, {
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

  const startEditSaleItem = (item) => {
    if (!item?.id) return;
    setEditingSaleItemId(Number(item.id));
    setSaleEditDraft({
      price: String((Number(getPriceCents(item)) || 0) / 100),
      stock_total: item?.stock_total == null ? "" : String(item.stock_total),
    });
  };

  const cancelEditSaleItem = () => {
    setEditingSaleItemId(null);
    setSaleEditDraft({ price: "", stock_total: "" });
  };

  const saveSaleItemEdit = async (item) => {
    if (!item?.id || !eventSlug) return;
    const price = Number(saleEditDraft.price);
    if (!Number.isFinite(price) || price < 0) {
      setTabError("El precio debe ser un número válido.");
      return;
    }
    const stockRaw = String(saleEditDraft.stock_total ?? "").trim();
    const stockTotal = stockRaw === "" ? null : Number(stockRaw);
    if (stockRaw !== "" && (!Number.isFinite(stockTotal) || stockTotal < 0)) {
      setTabError("El stock debe ser un número válido.");
      return;
    }

    setTabBusy(true);
    setTabError("");
    try {
      const payload = {
        tenant_id: tenantId,
        event_slug: eventSlug,
        kind: item.kind || "ticket",
        name: String(item.name || "").trim(),
        price: Math.round(price * 100) / 100,
        price_cents: Math.round(price * 100),
        currency: item.currency || "ARS",
        stock_total: stockTotal,
        sort_order: Number.isFinite(Number(item.display_order)) ? Number(item.display_order) : 0,
        active: item.active !== false,
      };
      const qs = new URLSearchParams({ tenant_id: tenantId, event_slug: eventSlug });
      const updateUrl = currentView === "supportAI"
        ? `/api/support/ai/admin/sale-items/${Number(item.id)}?${qs.toString()}`
        : `/api/producer/sale-items/${Number(item.id)}?${qs.toString()}`;
      await fetchJson(updateUrl, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      await loadSaleItems();
      cancelEditSaleItem();
    } catch (e) {
      setTabError(String(e?.message || e));
    } finally {
      setTabBusy(false);
    }
  };

  const toggleSaleItem = async (id, active) => {
    setTabBusy(true);
    setTabError("");
    try {
      const toggleUrl = currentView === "supportAI" ? `/api/support/ai/admin/sale-items/toggle` : `/api/producer/sale-items/toggle`;
      await fetchJson(toggleUrl, {
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

  const deleteSaleItem = async (itemOrId) => {
    if (!eventSlug) return;
    const id = Number(
      typeof itemOrId === "object" && itemOrId !== null
        ? itemOrId.id
        : itemOrId
    );
    if (!Number.isFinite(id) || id <= 0) {
      setTabError("No pudimos identificar el ticket a eliminar.");
      return;
    }

    if (!window.confirm("¿Eliminar este ticket? Esta acción no se puede deshacer.")) {
      return;
    }

    setTabBusy(true);
    setTabError("");
    try {
      const qs = new URLSearchParams({
        tenant_id: tenantId,
        event_slug: eventSlug,
      });
      const deleteUrl = currentView === "supportAI"
        ? `/api/support/ai/admin/sale-items/${id}?${qs.toString()}`
        : `/api/producer/sale-items/${id}?${qs.toString()}`;
      await fetchJson(deleteUrl, {
        method: "DELETE",
      });
      await loadSaleItems();
      setEventItems((prev) => (prev || []).filter((it) => Number(it?.id) !== id));
    } catch (e) {
      setTabError(String(e?.message || e));
    } finally {
      setTabBusy(false);
    }
  };

  const issueCourtesyForSaleItem = async (item) => {
    if (!eventSlug || !item?.id) return;

    const qtyRaw = window.prompt(`¿Cuántas cortesías querés emitir para "${item.name || "Ticket"}"?`, "1");
    if (qtyRaw == null) return;
    const quantity = parseInt(String(qtyRaw || "").trim(), 10);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      setTabError("Ingresá una cantidad válida de cortesías.");
      return;
    }

    setTabBusy(true);
    setTabError("");
    setCourtesyIssueResult(null);
    try {
      const qs = new URLSearchParams({ tenant_id: tenantId });
      const res = await fetchJson(`/api/producer/events/${encodeURIComponent(eventSlug)}/courtesy-issue?${qs.toString()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId,
          sale_item_id: Number(item.id),
          quantity,
          buyer_name: "Cortesía",
        }),
      });

      await loadSaleItems();
      const issued = Number(res?.quantity || quantity);
      setCourtesyIssueResult({
        quantity: issued,
        order_id: String(res?.order_id || ""),
        tickets: Array.isArray(res?.tickets) ? res.tickets : [],
      });
    } catch (e) {
      setTabError(String(e?.message || e));
    } finally {
      setTabBusy(false);
    }
  };

  const issuePosSale = async () => {
    if (!eventSlug) return;
    const saleItemId = parseInt(String(posDraft.sale_item_id || "").trim(), 10);
    const quantity = parseInt(String(posDraft.quantity || "").trim(), 10);
    if (!Number.isFinite(saleItemId) || saleItemId <= 0) {
      setTabError("Seleccioná un ticket para registrar la venta en taquilla.");
      return;
    }
    if (!Number.isFinite(quantity) || quantity <= 0) {
      setTabError("Ingresá una cantidad válida.");
      return;
    }

    setTabBusy(true);
    setTabError("");
    setPosIssueResult(null);
    try {
      const qs = new URLSearchParams({ tenant_id: tenantId });
      const res = await fetchJson(`/api/producer/events/${encodeURIComponent(eventSlug)}/pos-sale?${qs.toString()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId,
          sale_item_id: saleItemId,
          quantity,
          payment_method: String(posDraft.payment_method || "cash").trim().toLowerCase(),
          seller_code: String(posDraft.seller_code || "").trim() || null,
          buyer_name: String(posDraft.buyer_name || "").trim() || null,
          buyer_email: String(posDraft.buyer_email || "").trim() || null,
          buyer_phone: String(posDraft.buyer_phone || "").trim() || null,
          buyer_dni: String(posDraft.buyer_dni || "").trim() || null,
          note: String(posDraft.note || "").trim() || null,
        }),
      });

      await loadSaleItems();
      setPosIssueResult({
        order_id: String(res?.order_id || ""),
        quantity: Number(res?.quantity || quantity),
        payment_method: String(res?.payment_method || posDraft.payment_method || "cash"),
        total_cents: Number(res?.total_cents || 0),
        buyer_email: String(posDraft.buyer_email || "").trim(),
        tickets: Array.isArray(res?.tickets) ? res.tickets : [],
      });
      setPosDraft((prev) => ({
        ...prev,
        quantity: "1",
        buyer_name: "",
        buyer_email: "",
        buyer_phone: "",
        buyer_dni: "",
        note: "",
      }));
    } catch (e) {
      setTabError(String(e?.message || e));
    } finally {
      setTabBusy(false);
    }
  };

  const orderPdfUrl = (orderId) =>
    `${window.location.origin}/api/tickets/orders/${encodeURIComponent(String(orderId || "").trim())}/pdf`;

  const shareOrderPdfByWhatsapp = (orderId) => {
    if (!featureFlags.whatsappShare) return;
    const oid = String(orderId || "").trim();
    if (!oid) return;
    const text = `🎟️ ${brandConfig.shortName}\nOrden: ${oid}\nPDF: ${orderPdfUrl(oid)}`;
    window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener,noreferrer");
  };

  const sendOrderPdfByEmail = async (orderId, defaultEmail = "") => {
    const oid = String(orderId || "").trim();
    if (!oid) return;
    const isStaffMode = Boolean(staffAccess?.active);
    const activeEventSlug = String(isStaffMode ? (staffAccess?.slug || "") : (eventSlug || "")).trim();
    if (!activeEventSlug) {
      alert("No se encontró el evento para enviar el PDF.");
      return;
    }
    const email = window.prompt("¿A qué email enviamos el PDF?", String(defaultEmail || "").trim());
    if (!email) return;
    try {
      const qs = new URLSearchParams({ tenant_id: isStaffMode ? defaultRuntimeConfig.publicTenant : tenantId });
      const payload = { to_email: String(email).trim() };
      const headers = { "Content-Type": "application/json" };
      const staffToken = String(staffAccess?.token || "").trim();
      if (isStaffMode && staffToken) headers["x-staff-token"] = staffToken;
      const res = await fetchJson(
        `/api/producer/events/${encodeURIComponent(activeEventSlug)}/orders/${encodeURIComponent(oid)}/send-pdf?${qs.toString()}`,
        {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
        }
      );
      alert(`PDF enviado a ${res?.sent_to || email}`);
    } catch (e) {
      alert(`No se pudo enviar el PDF: ${String(e?.message || e)}`);
    }
  };

  const deleteSeller = async (sellerOrId) => {
    if (!eventSlug) return;
    const seller =
      typeof sellerOrId === "object" && sellerOrId !== null ? sellerOrId : null;
    const id = Number(seller?.id ?? sellerOrId);
    if (!Number.isFinite(id) || id <= 0) {
      setTabError("No pudimos identificar el vendedor a eliminar.");
      return;
    }

    const label = seller?.name || sellerCodeOf(seller) || `#${id}`;
    if (!window.confirm(`¿Eliminar vendedor ${label}?`)) {
      return;
    }

    setTabBusy(true);
    setTabError("");
    try {
      const qs = new URLSearchParams({
        tenant_id: tenantId,
        event_slug: eventSlug,
      });
      await fetchJson(`/api/producer/sellers/${id}?${qs.toString()}`, {
        method: "DELETE",
      });
      await loadSellers();
    } catch (e) {
      setTabError(String(e?.message || e));
    } finally {
      setTabBusy(false);
    }
  };

  const createSeller = async () => {
    if (!eventSlug) {
      setTabError("Guardá el evento primero o verificá que tenga slug válido.");
      return;
    }
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
              Editor
            </div>
            <div className="text-3xl font-black uppercase italic">
              {editFormData?.title || "Nuevo Evento"}
            </div>
            <div className="text-[11px] text-neutral-400 mt-2">
              Completá los datos para crear o actualizar tu evento.
            </div>
          </div>
          <button onClick={onClose} className="p-2 rounded-2xl hover:bg-white/5 transition-all">
            <X />
          </button>
        </div>


        {isNewEvent ? (
          <div>
            <div className="mb-6 text-[11px] text-neutral-400">Completá los datos del evento para continuar.</div>

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
                    Modo de liquidación
                  </label>
                  <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => setEditFormData((s) => ({ ...s, settlement_mode: "manual_transfer" }))}
                      className={`px-3 py-3 rounded-2xl border text-left ${String(editFormData.settlement_mode || "manual_transfer") === "manual_transfer"
                        ? "border-violet-400/80 bg-violet-500/20"
                        : "border-white/15 bg-white/5 hover:bg-white/10"
                        }`}
                    >
                      <div className="text-[11px] font-black uppercase tracking-widest text-white/80">Manual</div>
                      <div className="text-[11px] text-white/60">Cobra la cuenta administradora y luego se transfiere al productor.</div>
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditFormData((s) => ({ ...s, settlement_mode: "mp_split" }))}
                      className={`px-3 py-3 rounded-2xl border text-left ${String(editFormData.settlement_mode || "manual_transfer") === "mp_split"
                        ? "border-violet-400/80 bg-violet-500/20"
                        : "border-white/15 bg-white/5 hover:bg-white/10"
                        }`}
                    >
                      <div className="text-[11px] font-black uppercase tracking-widest text-white/80">Split Mercado Pago</div>
                      <div className="text-[11px] text-white/60">El evento cobra directo en la cuenta OAuth conectada del productor.</div>
                    </button>
                  </div>
                </div>

                {String(editFormData.settlement_mode || "manual_transfer") === "mp_split" && (
                  <div>
                    <label className="text-[11px] font-black uppercase tracking-widest text-neutral-500">
                      Collector ID Mercado Pago
                    </label>
                    <input
                      value={editFormData.mp_collector_id || ""}
                      onChange={(e) =>
                        setEditFormData((s) => ({
                          ...s,
                          mp_collector_id: e.target.value,
                        }))
                      }
                      className={`mt-2 w-full px-4 py-3 rounded-2xl ${UI.input}`}
                      placeholder="Ej: 123456789"
                    />
                    <div className="mt-2 flex items-center gap-2">
                      <button
                        type="button"
                        onClick={connectMpOauth}
                        disabled={mpOauthBusy}
                        className="px-3 py-2 rounded-xl bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-400/30 text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
                      >
                        {mpOauthBusy ? "Conectando..." : "Conectar Mercado Pago (OAuth)"}
                      </button>
                      <span className="text-[10px] text-white/50">Si no autorizás MP OAuth, la venta entra a tu cuenta admin y luego transferís al productor.</span>
                    </div>
                  </div>
                )}

                <div>
                  <label className="text-[11px] font-black uppercase tracking-widest text-neutral-500">
                    Número de contacto
                  </label>
                  <input
                    value={editFormData.contact_phone || ""}
                    onChange={(e) =>
                      setEditFormData((s) => ({ ...s, contact_phone: e.target.value }))
                    }
                    className={`mt-2 w-full px-4 py-3 rounded-2xl ${UI.input}`}
                    placeholder="Celular del organizador"
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

                <div className="md:col-span-2 rounded-2xl border border-white/10 bg-white/5 p-4">
                  <label className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      checked={(editFormData.visibility || "public") === "unlisted"}
                      onChange={(e) =>
                        setEditFormData((prev) => ({
                          ...prev,
                          visibility: e.target.checked ? "unlisted" : "public",
                        }))
                      }
                      className="mt-1"
                    />
                    <div className="min-w-0">
                      <div className="text-[12px] font-black">Evento privado (solo por link)</div>
                      <div className="text-[11px] text-neutral-400">
                        Si está activo, no aparecerá en la cartelera. Solo se accede con el link.
                      </div>
                    </div>
                  </label>
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
                        Acepto {" "}
                        <a
                          href={legalConfig.producerTermsUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="underline"
                          onClick={(e) => e.stopPropagation()}
                        >
                          Términos y Condiciones del Productor
                        </a>
                      </div>
                      <div className="text-[11px] text-neutral-400">
                        Declaro que poseo facultades suficientes para obligar a la entidad/sociedad cuyos datos he registrado. 
                        <a
                          href="#"
                          onClick={(ev) => {
                            ev.preventDefault();
                            setShowTermsModal(true);
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
                </div>
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="text-sm font-semibold mb-2">Preview</div>
      <div className="aspect-[16/9] w-full rounded-2xl overflow-hidden bg-black/30 border border-white/10 flex items-center justify-center">
        {(normalizeAssetUrl(flyerPreview, { allowBlob: true }) || normalizeAssetUrl(editFormData.flyer_url)) ? (
          <img
            src={normalizeAssetUrl(flyerPreview, { allowBlob: true }) || normalizeAssetUrl(editFormData.flyer_url) || FALLBACK_FLYER}
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

    <div className="md:col-span-2 rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="text-xs font-black uppercase tracking-widest text-white/60">Descripción del evento</div>
      <textarea
        value={editFormData.description || ""}
        onChange={(e) => setEditFormData((p) => ({ ...p, description: e.target.value }))}
        className="mt-2 w-full px-4 py-3 rounded-2xl resize-y bg-white/5 border border-white/10 outline-none focus:ring-2 focus:ring-white/20"
        rows={8}
        placeholder="Contá todo lo que quieras: artistas, horarios, condiciones, +18, etc."
      />
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
                              <div className="text-[11px] text-white/50">{sellerCodeOf(s) || "sin código"}</div>
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
                    <div><span className="text-white/40">Cobro:</span> {editFormData.payout_alias || "-"} · {editFormData.cuit || "-"} · {editFormData.settlement_mode === "mp_split" ? "Split MP" : "Manual"}</div>
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
                  Crear evento
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

                  <div className="text-sm">
                    <div className="text-white/60 mb-1">Fecha y horario</div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <input
                        type="date"
                        className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                        value={editFormData.start_date || ""}
                        onChange={(e) => setEditFormData({ ...editFormData, start_date: e.target.value })}
                      />
                      <input
                        type="time"
                        className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                        value={editFormData.start_time || ""}
                        onChange={(e) => setEditFormData({ ...editFormData, start_time: e.target.value })}
                      />
                    </div>
                    <div className="mt-2 text-[11px] text-white/50">
                      Fecha visible actual: {editFormData.date_text || "(sin definir)"}
                    </div>
                  </div>

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

                  <label className="text-sm">
                    <div className="text-white/60 mb-1">Alias para el cobro</div>
                    <input
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                      value={editFormData.payout_alias || ""}
                      onChange={(e) => setEditFormData((prev) => ({ ...prev, payout_alias: e.target.value }))}
                      placeholder="alias / CBU / Mercado Pago"
                    />
                  </label>

                  <div className="text-sm">
                    <div className="text-white/60 mb-1">Modo de liquidación</div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <button
                        type="button"
                        onClick={() => setEditFormData((prev) => ({ ...prev, settlement_mode: "manual_transfer" }))}
                        className={`px-3 py-3 rounded-xl border text-left ${String(editFormData.settlement_mode || "manual_transfer") === "manual_transfer"
                          ? "border-violet-400/80 bg-violet-500/20"
                          : "border-white/15 bg-white/5 hover:bg-white/10"
                          }`}
                      >
                        <div className="text-[11px] font-black uppercase tracking-widest text-white/80">Manual</div>
                        <div className="text-[11px] text-white/60">Cobra la cuenta administradora y luego se transfiere al productor.</div>
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditFormData((prev) => ({ ...prev, settlement_mode: "mp_split" }))}
                        className={`px-3 py-3 rounded-xl border text-left ${String(editFormData.settlement_mode || "manual_transfer") === "mp_split"
                          ? "border-violet-400/80 bg-violet-500/20"
                          : "border-white/15 bg-white/5 hover:bg-white/10"
                          }`}
                      >
                        <div className="text-[11px] font-black uppercase tracking-widest text-white/80">Split Mercado Pago</div>
                        <div className="text-[11px] text-white/60">El evento cobra directo en la cuenta OAuth conectada del productor.</div>
                      </button>
                    </div>
                  </div>

                  {String(editFormData.settlement_mode || "manual_transfer") === "mp_split" && (
                    <div className="text-sm md:col-span-2 rounded-2xl border border-white/10 bg-white/5 p-4">
                      <div className="text-white/60 mb-1">Collector ID Mercado Pago</div>
                      <input
                        className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                        value={editFormData.mp_collector_id || ""}
                        onChange={(e) => setEditFormData((prev) => ({ ...prev, mp_collector_id: e.target.value }))}
                        placeholder="Ej: 123456789"
                      />
                      <div className="mt-2 flex items-center gap-2">
                        <button
                          type="button"
                          onClick={connectMpOauth}
                          disabled={mpOauthBusy}
                          className="px-3 py-2 rounded-xl bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-400/30 text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
                        >
                          {mpOauthBusy ? "Conectando..." : "Conectar Mercado Pago (OAuth)"}
                        </button>
                        <span className="text-[10px] text-white/50">Si no autorizás MP OAuth, la venta entra a tu cuenta admin y luego transferís al productor.</span>
                      </div>
                    </div>
                  )}

                  <label className="text-sm">
                    <div className="text-white/60 mb-1">CUIT</div>
                    <input
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                      value={editFormData.cuit || ""}
                      onChange={(e) => setEditFormData((prev) => ({ ...prev, cuit: e.target.value }))}
                      placeholder="20-XXXXXXXX-X"
                    />
                  </label>

                  <label className="text-sm">
                    <div className="text-white/60 mb-1">Número de contacto</div>
                    <input
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2"
                      value={editFormData.contact_phone || ""}
                      onChange={(e) => setEditFormData((prev) => ({ ...prev, contact_phone: e.target.value }))}
                      placeholder="Celular del organizador"
                    />
                  </label>

                  <div className="text-sm md:col-span-2 rounded-2xl border border-white/10 bg-white/5 p-4">
                    <label className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        className="mt-1 h-5 w-5 accent-indigo-500"
                        checked={(editFormData.visibility || "public") === "unlisted"}
                        onChange={(e) =>
                          setEditFormData((prev) => ({
                            ...prev,
                            visibility: e.target.checked ? "unlisted" : "public",
                          }))
                        }
                      />
                      <div>
                        <div className="text-white font-semibold">Evento privado (solo por link)</div>
                        <div className="text-xs text-white/70">
                          Si está activo, no aparecerá en la cartelera. Solo se accede con el link.
                        </div>
                      </div>
                    </label>
                  </div>

                  <div className="text-sm md:col-span-2 rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="text-white/60 mb-2">Flyer del evento</div>
                    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                      <input
                        type="file"
                        accept="image/*"
                        className="w-full text-sm md:max-w-sm"
                        onChange={(e) => onPickFlyerFile(e.target.files?.[0])}
                      />
                      {normalizeAssetUrl(editFormData.flyer_url) && (
                        <a
                          href={normalizeAssetUrl(editFormData.flyer_url)}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs underline text-white/70 hover:text-white"
                        >
                          Ver flyer actual
                        </a>
                      )}
                    </div>
                  </div>

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
                    <div className="text-sm font-semibold text-white">
                      Acepto{" "}
                      <a
                        href={legalConfig.producerTermsUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Términos y Condiciones del Productor
                      </a>
                    </div>
                    <div className="text-xs text-white/70">
                      Declaro que poseo facultades suficientes para obligar a la entidad/sociedad cuyos datos he registrado. 
                      <a
                        href="#"
                        onClick={(e) => {
                          e.preventDefault();
                          setShowTermsModal(true);
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
                        {!editFormData.accept_terms && (
                          <div className="rounded-2xl border border-amber-400/35 bg-amber-500/10 p-3">
                            <label className="flex items-start gap-3">
                              <input
                                type="checkbox"
                                className="mt-1 h-4 w-4 accent-indigo-500"
                                checked={!!editFormData.accept_terms}
                                onChange={(e) =>
                                  setEditFormData((prev) => ({
                                    ...prev,
                                    accept_terms: e.target.checked,
                                  }))
                                }
                              />
                              <div className="min-w-0">
                                <div className="text-sm font-semibold text-amber-100">
                                  Para guardar cambios necesitás aceptar{" "}
                                  <a
                                    href={legalConfig.producerTermsUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="underline"
                                    onClick={(ev) => ev.stopPropagation()}
                                  >
                                    Términos y Condiciones del Productor
                                  </a>
                                </div>
                                <button
                                  type="button"
                                  className="text-xs text-amber-100/90 underline hover:text-white mt-1"
                                  onClick={() => setShowTermsModal(true)}
                                >
                                  Ver términos
                                </button>
                              </div>
                            </label>
                          </div>
                        )}

                        <div id="pos-taquilla-box" className="rounded-2xl border border-indigo-400/30 bg-indigo-500/10 p-3">
                          <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                            <div className="text-sm font-semibold text-indigo-100">Venta en taquilla (POS)</div>
                            {!!eventSlug && (
                              <button
                                type="button"
                                onClick={() => onOpenStaffAccess?.({ slug: eventSlug, title: editFormData?.title || eventSlug })}
                                className="px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-[10px] text-black font-black uppercase tracking-widest"
                              >
                                <span className="inline-flex items-center gap-1"><LinkIcon size={12} /> Acceso Staff</span>
                              </button>
                            )}
                          </div>
                          <div className="text-[11px] text-indigo-100/80 mb-3">
                            Acceso rápido: desde el panel productor, botón <b>POS Taquilla</b>.
                          </div>
                          <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
                            <select
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                              value={posDraft.sale_item_id}
                              onChange={(e) => setPosDraft((prev) => ({ ...prev, sale_item_id: e.target.value }))}
                            >
                              <option value="">Seleccioná ticket…</option>
                              {(saleItems || []).map((it) => (
                                <option key={it.id} value={it.id}>
                                  {it.name} · ${(Number(it.price_cents || 0) / 100).toLocaleString()}
                                </option>
                              ))}
                            </select>
                            <input
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                              placeholder="Cantidad"
                              value={posDraft.quantity}
                              onChange={(e) => setPosDraft((prev) => ({ ...prev, quantity: e.target.value }))}
                            />
                            <select
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                              value={posDraft.payment_method}
                              onChange={(e) => setPosDraft((prev) => ({ ...prev, payment_method: e.target.value }))}
                            >
                              <option value="cash">Efectivo</option>
                              <option value="card">Tarjeta</option>
                              <option value="transfer">Transferencia</option>
                              <option value="debit">Débito</option>
                              <option value="credit">Crédito</option>
                              <option value="mp_point">MP Point</option>
                              <option value="other">Otro</option>
                            </select>
                            <input
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                              placeholder="Seller code (opcional)"
                              value={posDraft.seller_code}
                              onChange={(e) => setPosDraft((prev) => ({ ...prev, seller_code: e.target.value }))}
                            />
                            <input
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm md:col-span-2"
                              placeholder="Comprador (opcional)"
                              value={posDraft.buyer_name}
                              onChange={(e) => setPosDraft((prev) => ({ ...prev, buyer_name: e.target.value }))}
                            />
                            <input
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                              placeholder="Email (opcional)"
                              value={posDraft.buyer_email}
                              onChange={(e) => setPosDraft((prev) => ({ ...prev, buyer_email: e.target.value }))}
                            />
                            <input
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                              placeholder="Celular (opcional)"
                              value={posDraft.buyer_phone}
                              onChange={(e) => setPosDraft((prev) => ({ ...prev, buyer_phone: e.target.value }))}
                            />
                            <input
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                              placeholder="DNI (opcional)"
                              value={posDraft.buyer_dni}
                              onChange={(e) => setPosDraft((prev) => ({ ...prev, buyer_dni: e.target.value }))}
                            />
                            <input
                              className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm md:col-span-3"
                              placeholder="Nota interna (opcional)"
                              value={posDraft.note}
                              onChange={(e) => setPosDraft((prev) => ({ ...prev, note: e.target.value }))}
                            />
                            <button
                              className="rounded-xl bg-indigo-500/80 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold disabled:opacity-50"
                              disabled={tabBusy || !String(posDraft.sale_item_id || "").trim()}
                              onClick={issuePosSale}
                            >
                              Registrar venta POS
                            </button>
                          </div>
                          {posIssueResult && (
                            <div className="mt-3 rounded-xl border border-emerald-400/30 bg-emerald-500/10 p-3 text-xs text-emerald-100">
                              <div className="font-semibold">Venta registrada</div>
                              <div>Orden: <span className="font-mono">{posIssueResult.order_id || "-"}</span></div>
                              <div>Entradas: {posIssueResult.quantity} · Pago: {posIssueResult.payment_method}</div>
                              <div>Total: ${(Number(posIssueResult.total_cents || 0) / 100).toLocaleString()}</div>
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <a
                                  href={orderPdfUrl(posIssueResult.order_id)}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="rounded-lg border border-white/20 bg-white/5 px-2 py-1 text-[11px] text-white/85 hover:bg-white/10"
                                >
                                  ver PDF
                                </a>
                                <button
                                  type="button"
                                  className="rounded-lg border border-white/20 bg-white/5 px-2 py-1 text-[11px] text-white/85 hover:bg-white/10"
                                  onClick={() => sendOrderPdfByEmail(posIssueResult.order_id, posIssueResult.buyer_email)}
                                >
                                  <span className="inline-flex items-center gap-1"><Mail size={12} /> enviar PDF por mail</span>
                                </button>
                                <button
                                  type="button"
                                  className="rounded-lg border border-white/20 bg-white/5 px-2 py-1 text-[11px] text-white/85 hover:bg-white/10"
                                  onClick={() => shareOrderPdfByWhatsapp(posIssueResult.order_id)}
                                >
                                  compartir PDF por whatsapp
                                </button>
                              </div>
                              {!!posIssueResult.tickets?.length && (
                                <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                                  {posIssueResult.tickets.map((t, idx) => {
                                    const payload = t?.qr_payload || t?.qr_token || t?.ticket_id || "";
                                    return (
                                      <div key={t?.ticket_id || idx} className="rounded-xl border border-white/10 bg-black/20 p-3 flex items-center gap-3">
                                        <img
                                          src={qrImgUrl(payload, 150)}
                                          alt={`QR pos ${idx + 1}`}
                                          className="h-20 w-20 rounded-lg border border-white/10 bg-white"
                                        />
                                        <div className="min-w-0 flex-1">
                                          <div className="text-xs text-white/80">{t?.ticket_type || "Entrada"}</div>
                                          <div className="text-[11px] text-white/60 truncate">ID: {t?.ticket_id}</div>
                                          <div className="mt-2 flex flex-wrap items-center gap-2">
                                            <button
                                              type="button"
                                              className="text-[11px] text-emerald-300 hover:text-emerald-200 underline"
                                              onClick={() => navigator.clipboard?.writeText(String(payload || ""))}
                                            >
                                              copiar QR payload
                                            </button>
                                          </div>
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                          )}
                        </div>

                        {courtesyIssueResult && (
                          <div className="rounded-2xl border border-emerald-400/30 bg-emerald-500/10 p-3">
                            <div className="text-sm font-semibold text-emerald-200">
                              Cortesías emitidas: {courtesyIssueResult.quantity}
                            </div>
                            <div className="text-xs text-emerald-100/90 mt-1">
                              Orden: <span className="font-mono">{courtesyIssueResult.order_id || "-"}</span>
                            </div>
                            <div className="mt-2 flex flex-wrap items-center gap-2">
                              <a
                                href={orderPdfUrl(courtesyIssueResult.order_id)}
                                target="_blank"
                                rel="noreferrer"
                                className="rounded-lg border border-white/20 bg-white/5 px-2 py-1 text-[11px] text-white/85 hover:bg-white/10"
                              >
                                ver PDF
                              </a>
                              <button
                                type="button"
                                className="rounded-lg border border-white/20 bg-white/5 px-2 py-1 text-[11px] text-white/85 hover:bg-white/10"
                                onClick={() => sendOrderPdfByEmail(courtesyIssueResult.order_id)}
                              >
                                <span className="inline-flex items-center gap-1"><Mail size={12} /> enviar PDF por mail</span>
                              </button>
                              <button
                                type="button"
                                className="rounded-lg border border-white/20 bg-white/5 px-2 py-1 text-[11px] text-white/85 hover:bg-white/10"
                                onClick={() => shareOrderPdfByWhatsapp(courtesyIssueResult.order_id)}
                              >
                                compartir PDF por whatsapp
                              </button>
                            </div>
                            {!courtesyIssueResult.tickets?.length ? (
                              <div className="text-xs text-emerald-100/80 mt-2">
                                Se emitieron correctamente. Podés verlas también en <b>Listado de tickets</b> del evento.
                              </div>
                            ) : (
                              <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                                {courtesyIssueResult.tickets.map((t, idx) => {
                                  const payload = t?.qr_payload || t?.qr_token || t?.ticket_id || "";
                                  return (
                                    <div key={t?.ticket_id || idx} className="rounded-xl border border-white/10 bg-black/20 p-3 flex items-center gap-3">
                                      <img
                                        src={qrImgUrl(payload, 150)}
                                        alt={`QR cortesía ${idx + 1}`}
                                        className="h-20 w-20 rounded-lg border border-white/10 bg-white"
                                      />
                                      <div className="min-w-0 flex-1">
                                        <div className="text-xs text-white/80">{t?.ticket_type || "Cortesía"}</div>
                                        <div className="text-[11px] text-white/60 truncate">ID: {t?.ticket_id}</div>
                                        <div className="mt-2 flex flex-wrap items-center gap-2">
                                          <button
                                            type="button"
                                            className="text-[11px] text-emerald-300 hover:text-emerald-200 underline"
                                            onClick={() => navigator.clipboard?.writeText(String(payload || ""))}
                                          >
                                            copiar QR payload
                                          </button>
                                        </div>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        )}

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
                          <div className="mt-2 text-xs text-white/45">El precio se guarda automáticamente al confirmar.</div>
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
                                  <div className="min-w-0 flex-1">
                                    <div className="text-sm font-semibold truncate">{it.name}</div>
                                    {editingSaleItemId === Number(it.id) ? (
                                      <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
                                        <input
                                          className="rounded-lg bg-black/30 border border-white/15 px-2 py-1.5 text-xs"
                                          placeholder="Precio"
                                          value={saleEditDraft.price}
                                          onChange={(e) => setSaleEditDraft((prev) => ({ ...prev, price: e.target.value }))}
                                        />
                                        <input
                                          className="rounded-lg bg-black/30 border border-white/15 px-2 py-1.5 text-xs"
                                          placeholder="Stock"
                                          value={saleEditDraft.stock_total}
                                          onChange={(e) => setSaleEditDraft((prev) => ({ ...prev, stock_total: e.target.value }))}
                                        />
                                      </div>
                                    ) : (
                                      <div className="text-xs text-white/55">
                                        {it.currency} ${priceLabel(it)} • stock {it.stock_total ?? "—"}
                                      </div>
                                    )}
                                  </div>
                                  <div className="flex items-center gap-3">
                                    <button
                                      className="rounded-lg border border-emerald-300/40 bg-emerald-400/20 px-3 py-1.5 text-xs font-semibold text-emerald-100 shadow-[0_0_0_1px_rgba(16,185,129,0.15)] transition hover:bg-emerald-400/30 hover:text-white disabled:opacity-60"
                                      onClick={() => issueCourtesyForSaleItem(it)}
                                      disabled={tabBusy}
                                    >
                                      ✨ emitir cortesía
                                    </button>
                                    {editingSaleItemId === Number(it.id) ? (
                                      <>
                                        <button
                                          className="text-xs text-indigo-300 hover:text-indigo-200 underline disabled:opacity-60"
                                          onClick={() => saveSaleItemEdit(it)}
                                          disabled={tabBusy}
                                        >
                                          guardar
                                        </button>
                                        <button
                                          className="text-xs text-white/70 hover:text-white underline disabled:opacity-60"
                                          onClick={cancelEditSaleItem}
                                          disabled={tabBusy}
                                        >
                                          cancelar
                                        </button>
                                      </>
                                    ) : (
                                      <button
                                        className="text-xs text-indigo-300 hover:text-indigo-200 underline disabled:opacity-60"
                                        onClick={() => startEditSaleItem(it)}
                                        disabled={tabBusy}
                                      >
                                        editar
                                      </button>
                                    )}
                                    <button
                                      className="text-xs text-white/70 hover:text-white underline"
                                      onClick={() => deleteSaleItem(it.id)}
                                      disabled={tabBusy}
                                    >
                                      eliminar
                                    </button>
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {activeTab === "sellers" && (
                      <div className="space-y-4">
                        {!editFormData.accept_terms && (
                          <div className="rounded-2xl border border-amber-400/35 bg-amber-500/10 p-3">
                            <label className="flex items-start gap-3">
                              <input
                                type="checkbox"
                                className="mt-1 h-4 w-4 accent-indigo-500"
                                checked={!!editFormData.accept_terms}
                                onChange={(e) =>
                                  setEditFormData((prev) => ({
                                    ...prev,
                                    accept_terms: e.target.checked,
                                  }))
                                }
                              />
                              <div className="min-w-0">
                                <div className="text-sm font-semibold text-amber-100">
                                  Para guardar cambios necesitás aceptar{" "}
                                  <a
                                    href={legalConfig.producerTermsUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="underline"
                                    onClick={(ev) => ev.stopPropagation()}
                                  >
                                    Términos y Condiciones del Productor
                                  </a>
                                </div>
                                <button
                                  type="button"
                                  className="text-xs text-amber-100/90 underline hover:text-white mt-1"
                                  onClick={() => setShowTermsModal(true)}
                                >
                                  Ver términos
                                </button>
                              </div>
                            </label>
                          </div>
                        )}

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
                              Confirmá que el vendedor acepta los términos para continuar.
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
                                    <div className="text-sm font-semibold truncate">{sellerCodeOf(s)} • {s.name}</div>
                                    <div className="text-xs text-white/55">id: {s.id}</div>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <button
                                      className="text-xs text-white/70 hover:text-white underline"
                                      onClick={async () => {
                                        const code = sellerCodeOf(s);
                                        if (!code) {
                                          setTabError("Este seller no tiene código válido para compartir.");
                                          return;
                                        }
                                        const base = `${window.location.origin}/evento/${encodeURIComponent(eventSlug)}`;
                                        const url = `${base}?seller_code=${encodeURIComponent(code)}`;
                                        try {
                                          await navigator.clipboard.writeText(url);
                                          setTabError(`Link copiado: ${url}`);
                                        } catch {
                                          setTabError(`Copiá este link: ${url}`);
                                        }
                                      }}
                                    >
                                      copiar link
                                    </button>
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
                Guardar
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
  const [runtimeConfig, setRuntimeConfig] = useState(defaultRuntimeConfig);
  const brandConfig = useMemo(() => resolveBrandConfig(runtimeConfig), [runtimeConfig]);
  const featureFlags = useMemo(() => resolveFeatureFlags(runtimeConfig), [runtimeConfig]);
  const isAltCheckoutUxEnabled = Boolean(featureFlags.altCheckoutUx);
  const flaggedViews = useMemo(
    () => resolveFlaggedViews({
      altProducerUi: Boolean(featureFlags.altProducerUi),
      altStaffUi: Boolean(featureFlags.altStaffUi),
    }),
    [featureFlags.altProducerUi, featureFlags.altStaffUi]
  );
  const { producerHomeView, staffValidatorView, staffPosView } = flaggedViews;
  const isProducerView = flaggedViews.isProducerView(view);
  const isStaffValidatorView = flaggedViews.isStaffValidatorView(view);
  const isStaffPosView = flaggedViews.isStaffPosView(view);
  const legalConfig = useMemo(() => resolveLegalConfig(runtimeConfig), [runtimeConfig]);
  const [loginRequired, setLoginRequired] = useState(false);
  const [pendingCheckout, setPendingCheckout] = useState(null);
  const [showTermsModal, setShowTermsModal] = useState(false);

  // Mis Tickets (Entradas + Barra)
  const [myAssets, setMyAssets] = useState([]);
  const [myAssetsLoading, setMyAssetsLoading] = useState(false);
  const [myAssetsError, setMyAssetsError] = useState(null);
  const [myFilters, setMyFilters] = useState({ kind: "all", status: "all", when: "all", q: "" });
  const [qrCache, setQrCache] = useState({});

  // Soporte IA (interno/staff)
  const [supportAiInput, setSupportAiInput] = useState("");
  const [supportAiLoading, setSupportAiLoading] = useState(false);
  const [supportAiError, setSupportAiError] = useState(null);
  const [supportAiHistory, setSupportAiHistory] = useState([]);
  const [supportAiStatus, setSupportAiStatus] = useState(null);
  const [adminDashboard, setAdminDashboard] = useState(null);
  const [adminEvents, setAdminEvents] = useState([]);
  const [adminOpsLoading, setAdminOpsLoading] = useState(false);
  const [adminOpsError, setAdminOpsError] = useState(null);
  const [newEventForm, setNewEventForm] = useState({ title: "", owner_tenant: "", city: "", date_text: "", venue: "" });
  const [transferForm, setTransferForm] = useState({ event_slug: "", new_owner_tenant: "" });
  const [adminEventFilter, setAdminEventFilter] = useState("");
  const [adminReportSearch, setAdminReportSearch] = useState("");
  const [adminReportSettlementFilter, setAdminReportSettlementFilter] = useState("all");
  const [adminReportStatusFilter, setAdminReportStatusFilter] = useState("all");
  const [adminReportProducerFilter, setAdminReportProducerFilter] = useState("all");
  const [adminReportSortBy, setAdminReportSortBy] = useState("title_asc");
  const [adminOwnerEmailForEditor, setAdminOwnerEmailForEditor] = useState("");
  const [adminEventActionLoading, setAdminEventActionLoading] = useState(false);
  const [adminDeleteRequests, setAdminDeleteRequests] = useState([]);
  const [adminBarSalesModal, setAdminBarSalesModal] = useState({ open: false, eventSlug: "", rows: [], loading: false, error: "", totalCents: 0 });
  const [adminBarSalesSearch, setAdminBarSalesSearch] = useState("");
  const [validatorEvent, setValidatorEvent] = useState(null);
  const [staffAccess, setStaffAccess] = useState({ active: false, slug: "", mode: "", token: "", title: "" });
  const [staffSaleItems, setStaffSaleItems] = useState([]);
  const [staffPosDraft, setStaffPosDraft] = useState({
    sale_item_id: "",
    quantity: "1",
    payment_method: "cash",
    seller_code: "",
    buyer_name: "",
    buyer_email: "",
    buyer_phone: "",
    buyer_dni: "",
    note: "",
  });
  const [staffPosBusy, setStaffPosBusy] = useState(false);
  const [staffPosError, setStaffPosError] = useState("");
  const [staffPosResult, setStaffPosResult] = useState(null);
  const [validatorInput, setValidatorInput] = useState("");
  const [validatorLoading, setValidatorLoading] = useState(false);
  const [validatorResult, setValidatorResult] = useState(null);
  const [scannerActive, setScannerActive] = useState(false);
  const [scannerError, setScannerError] = useState("");
  const validatorInputRef = useRef(null);
  const scannerVideoRef = useRef(null);
  const scannerStreamRef = useRef(null);
  const scannerRafRef = useRef(null);
  const scannerBusyRef = useRef(false);

  const formatMoney = formatMoneyAr;

  const publicTenant = useMemo(() => resolvePublicTenant(runtimeConfig), [runtimeConfig]);

  useEffect(() => {
    document.title = makeBrandPageTitle("Inicio", runtimeConfig);
  }, [runtimeConfig]);

  // Config público (Google Client ID + tenant público opcional)
  useEffect(() => {
    fetchPublicRuntimeConfig()
      .then((cfg) => {
        setRuntimeConfig((prev) => {
          const next = resolveRuntimeConfigState(cfg, prev);
          setGoogleClientId(next.googleClientId);
          return next.runtimeConfig;
        });
      })
      .catch(() => {
        setGoogleClientId("");
      });
  }, []);

  const refreshPublicEvents = async () => {
    try {
      const r = await fetch(`/api/public/events?tenant=${encodeURIComponent(publicTenant)}`, { credentials: "include" });
      const data = await readJsonOrText(r);
      if (r.ok && Array.isArray(data) && data.length) {
        setEvents(
          data.map((e) => ({
            id: e.id || e.slug,
            ...e,
            visibility: e.visibility || "public",
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
  }, [publicTenant]);

  useEffect(() => {
    try {
      const nextPurchase = resolveCheckoutSuccessState({
        hash: window.location.hash,
        previousPurchaseData: purchaseData,
        selectedEvent,
        selectedTicket,
        quantity,
        checkoutForm,
      });
      if (!nextPurchase) return;
      setPurchaseData(nextPurchase);
      setView("success");
    } catch (e) {
      console.warn("No se pudo procesar checkout/success", e);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);


  const openPublicEvent = async (slug) => {
    const localFallbackEvent = (events || []).find((ev) => String(ev?.slug || "") === String(slug || ""));
    const openWithLocalFallback = () => {
      if (!localFallbackEvent) return false;
      const sellerFromUrl =
        new URLSearchParams(window.location.search).get("seller") ||
        new URLSearchParams(window.location.search).get("seller_code") ||
        "";
      const localItems = Array.isArray(localFallbackEvent?.items) ? localFallbackEvent.items : [];
      setSelectedSellerCode(String(sellerFromUrl || "").trim());
      setSelectedEvent({
        id: localFallbackEvent.id || localFallbackEvent.slug,
        ...localFallbackEvent,
        items: localItems,
        flyer_url: localFallbackEvent.flyer_url || localFallbackEvent.hero_bg,
      });
      setSelectedTicket(localItems[0] || null);
      const detailPath = `/evento/${encodeURIComponent(slug)}`;
      const detailUrl = `${detailPath}${window.location.search || ""}`;
      const currentUrl = `${window.location.pathname}${window.location.search || ""}`;
      if (currentUrl !== detailUrl) {
        window.history.pushState({ ticketpro_view: "detail", slug }, "", detailUrl);
      } else {
        window.history.replaceState({ ticketpro_view: "detail", slug }, "", detailUrl);
      }
      window.scrollTo({ top: 0, behavior: "auto" });
      setView("detail");
      return true;
    };

    try {
      setLoading(true);
      const r = await fetch(`/api/public/events/${encodeURIComponent(slug)}?tenant=${encodeURIComponent(publicTenant)}`, {
        credentials: "include",
      });
      const data = await readJsonOrText(r);
      if (r.ok && data) {
        // Compat: el detalle puede traer items embebidos, pero la vista pública usa endpoint dedicado.
        let items = data.items || [];
        try {
          const rItems = await fetch(
            `/api/public/sale-items?tenant=${encodeURIComponent(publicTenant)}&event_slug=${encodeURIComponent(slug)}`,
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

        const sellerFromUrl = new URLSearchParams(window.location.search).get("seller") || new URLSearchParams(window.location.search).get("seller_code") || "";
        setSelectedSellerCode(String(sellerFromUrl || "").trim());
        setSelectedEvent({
          id: data.id || data.slug,
          ...data,
          items,
          flyer_url: data.flyer_url || data.hero_bg,
        });
        setSelectedTicket((items || [])[0] || null);
        const detailPath = `/evento/${encodeURIComponent(slug)}`;
        const detailUrl = `${detailPath}${window.location.search || ""}`;
        const currentUrl = `${window.location.pathname}${window.location.search || ""}`;
        if (currentUrl !== detailUrl) {
          window.history.pushState({ ticketpro_view: "detail", slug }, "", detailUrl);
        } else {
          window.history.replaceState({ ticketpro_view: "detail", slug }, "", detailUrl);
        }
        window.scrollTo({ top: 0, behavior: "auto" });
        setView("detail");
        return;
      }
      if (openWithLocalFallback()) return;
      alert("No se pudo abrir el evento (detalle).");
    } catch (e) {
      console.error(e);
      if (openWithLocalFallback()) return;
      alert("Error abriendo evento: " + (e?.message || e));
    } finally {
      setLoading(false);
    }
  };



  const [loading, setLoading] = useState(false);
  const [purchaseData, setPurchaseData] = useState(null);
  const [successProcessing, setSuccessProcessing] = useState(false);
  const [successTries, setSuccessTries] = useState(0);
  const [successMessage, setSuccessMessage] = useState(null);
  const [activeTab, setActiveTab] = useState("info");
  const [mpOauthBusy, setMpOauthBusy] = useState(false);

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
      visibility: "public",
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
  const tenantId = publicTenant;
  const [producerEvents, setProducerEvents] = useState([]); // [{ event_slug, orders_count, total_cents, bar_cents, tickets_cents }]
  const [producerEventsLoading, setProducerEventsLoading] = useState(false);
  const [producerEventsError, setProducerEventsError] = useState(null);

  const [selectedProducerEventSlug, setSelectedProducerEventSlug] = useState("");
  const [producerDashboard, setProducerDashboard] = useState(null); // { kpis, topCustomers, topProducts, timeSeries }
  const [producerDashboardLoading, setProducerDashboardLoading] = useState(false);
  const [producerDashboardError, setProducerDashboardError] = useState(null);
  const [soldTicketsModal, setSoldTicketsModal] = useState({
    open: false,
    event: null,
    rows: [],
    loading: false,
    error: "",
  });
  const [soldTicketsSearch, setSoldTicketsSearch] = useState("");
  const [adminCancelingTicketId, setAdminCancelingTicketId] = useState("");
  const [barOrdersModal, setBarOrdersModal] = useState({
    open: false,
    event: null,
    rows: [],
    loading: false,
    error: "",
    totalCents: 0,
  });
  const [barOrdersSearch, setBarOrdersSearch] = useState("");
  const [sellerSalesModal, setSellerSalesModal] = useState({
    open: false,
    event: null,
    rows: [],
    loading: false,
    error: "",
    totalTickets: 0,
  });
  const [sellerSalesSearch, setSellerSalesSearch] = useState("");
  const [staffLinksModal, setStaffLinksModal] = useState({
    open: false,
    event: null,
    loading: false,
    error: "",
    hours_valid: 12,
    validateLink: "",
    posLink: "",
  });
  const [ownerBarSummaryBySlug, setOwnerBarSummaryBySlug] = useState({});
  const [marketingSection, setMarketingSection] = useState("audience");
  const [audienceFilters, setAudienceFilters] = useState({ event_slug: "", date_from: "", date_to: "", sale_item_id: "", q: "" });
  const [audienceRows, setAudienceRows] = useState([]);
  const [audienceTotal, setAudienceTotal] = useState(0);
  const [audienceLoading, setAudienceLoading] = useState(false);
  const [audienceError, setAudienceError] = useState("");
  const [campaignsRows, setCampaignsRows] = useState([]);
  const [campaignsLoading, setCampaignsLoading] = useState(false);
  const [campaignsError, setCampaignsError] = useState("");
  const [campaignDraft, setCampaignDraft] = useState({ name: "", subject: "", body_html: "", body_text: "" });
  const [campaignSaving, setCampaignSaving] = useState(false);
  const [selectedCampaign, setSelectedCampaign] = useState(null);
  const [campaignDeliveries, setCampaignDeliveries] = useState([]);
  const [campaignDeliveriesLoading, setCampaignDeliveriesLoading] = useState(false);

  const [selectedEvent, setSelectedEvent] = useState(null);
  const [selectedSellerCode, setSelectedSellerCode] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [editFormData, setEditFormData] = useState(null);
  // File pendiente para subir flyer (se guarda en un ref para que sobreviva al wizard)
  const flyerPendingRef = useRef(null);

  const [checkoutForm, setCheckoutForm] = useState({
    fullName: "",
    dni: "",
    phone: "",
    address: "",
    province: "",
    postalCode: "",
    birthDate: "",
    acceptTerms: false,
  });

  const [checkoutTouched, setCheckoutTouched] = useState({
    fullName: false,
    dni: false,
    phone: false,
    address: false,
    province: false,
    postalCode: false,
    birthDate: false,
    acceptTerms: false,
  });

  const checkoutErrors = useMemo(() => validateCheckoutForm(checkoutForm), [checkoutForm]);

  const hasCheckoutErrors = Object.keys(checkoutErrors).length > 0;
  const checkoutError = (key) => (checkoutTouched[key] ? checkoutErrors[key] : "");

const [selectedTicket, setSelectedTicket] = useState(null);
  const [quantity, setQuantity] = useState(1);

  useEffect(() => {
    if (!selectedTicket && (selectedEvent?.items || []).length > 0) {
      setSelectedTicket(selectedEvent.items[0]);
    }
  }, [selectedEvent, selectedTicket]);

  const checkoutBlockReason = buildCheckoutBlockReason({ selectedTicket, selectedEvent, hasCheckoutErrors });

  const checkoutServicePct = resolveCheckoutServicePct(selectedEvent);
  const checkoutServicePctLabel = `${(checkoutServicePct * 100).toFixed(2)}%`;

  
  const loadMyAssets = async () => {
    setMyAssetsLoading(true);
    setMyAssetsError(null);
    try {
      const r = await fetch(`/api/orders/my-assets?tenant=${encodeURIComponent(publicTenant)}`, { credentials: "include" });
      const data = await readJsonOrText(r);
      if (!r.ok || !data?.ok) throw new Error(data?.detail || "No se pudieron cargar tus tickets");
      setMyAssets(Array.isArray(data.assets) ? data.assets : []);
    } catch (e) {
      setMyAssets([]);
      const raw = String(e?.message || "");
      const safeMsg = raw.includes("<html") || raw.includes("<!DOCTYPE")
        ? "No se pudieron cargar tus tickets. Probá actualizar en unos segundos."
        : (raw || "No se pudieron cargar tus tickets");
      setMyAssetsError(safeMsg);
    } finally {
      setMyAssetsLoading(false);
    }
  };

  const requestCancel = async ({ kind, id, order_id, reason }) => {
    const r = await fetch(`/api/orders/cancel-request?tenant=${encodeURIComponent(publicTenant)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ kind, id, order_id, reason }),
    });
    const data = await readJsonOrText(r);
    if (!r.ok || !data?.ok) throw new Error(data?.detail || "No se pudo solicitar arrepentimiento");
    return data;
  };

  const transferOrder = async ({ order_id, ticket_id, to_email }) => {
    const r = await fetch(`/api/orders/transfer-order?tenant=${encodeURIComponent(publicTenant)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ order_id, ticket_id, to_email }),
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
    (async () => {
      // 1) estado inicial
      await refreshMe();

      // 2) si venimos de un magic-link (backend redirige a /?login=1)
      try {
        const url = new URL(window.location.href);
        if (url.searchParams.get("login") === "1") {
          await refreshMe(); // refuerza sesión recién creada
          url.searchParams.delete("login");
          window.history.replaceState({}, "", url.pathname + (url.search ? url.search : "") + url.hash);
        }
      } catch {}
    })();
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
    setOwnerBarSummaryBySlug({});
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
    setOwnerBarSummaryBySlug({});
    setProducerEventsError(null);
    setProducerDashboardError(null);
    if (isProducerView && me) {
      loadProducerEvents();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isProducerView, me?.producer, view]);

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

  const loadOwnerBarSummaries = async (eventsList = []) => {
    const slugs = (eventsList || [])
      .map((ev) => String(ev?.slug || ev?.event_slug || "").trim())
      .filter(Boolean);
    if (slugs.length === 0) {
      setOwnerBarSummaryBySlug({});
      return;
    }

    const owner = String(me?.producer || me?.email || "").trim();
    const next = {};

    await Promise.all(
      slugs.map(async (slug) => {
        try {
          const summary = await getOwnerSummary({ slug, owner });
          if (!summary) return;
          next[slug] = summary;
        } catch {
          // fallback silencioso: mantenemos datos de /api/producer/events
        }
      })
    );

    setOwnerBarSummaryBySlug(next);
  };

  const loadProducerEvents = async () => {
    setProducerEventsLoading(true);
    setProducerEventsError(null);
    try {
      const data = await listProducerEvents({ tenantId });
      const list = Array.isArray(data?.events) ? data.events : Array.isArray(data) ? data : [];
      setProducerEvents(list);
      loadOwnerBarSummaries(list);

      // Auto-select first event with sales if none selected yet
      if (!selectedProducerEventSlug && list.length > 0) {
        const firstSlug = list[0]?.event_slug || list[0]?.eventSlug || list[0]?.slug;
        if (firstSlug) setSelectedProducerEventSlug(firstSlug);
      }
    } catch (e) {
      setProducerEventsError(e?.message || "No se pudo cargar la lista de eventos.");
      setProducerEvents([]);
      setOwnerBarSummaryBySlug({});
    } finally {
      setProducerEventsLoading(false);
    }
  };

  const loadProducerDashboard = async (eventSlug) => {
    if (!eventSlug) return;
    setProducerDashboardLoading(true);
    setProducerDashboardError(null);
    try {
      const data = await getProducerDashboard({ tenantId, eventSlug });
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

  const openQrValidator = (ev) => {
    const slug = ev?.slug || ev?.event_slug;
    setValidatorEvent({
      slug: String(slug || "").trim(),
      title: ev?.title || ev?.event_title || "Evento",
    });
    setValidatorInput("");
    setValidatorResult(null);
    setView(staffValidatorView);
  };

  const openPosTaquilla = (ev) => {
    // El POS vive dentro de la pestaña "Tickets" del editor del evento.
    openEditor(ev, "tickets");
    setTimeout(() => {
      try {
        const el = document.getElementById("pos-taquilla-box");
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch {}
    }, 120);
  };

  const loadStaffEventContext = async (slug) => {
    const safeSlug = String(slug || "").trim();
    if (!safeSlug) return;
    try {
      const eventRes = await fetch(`/api/public/events/${encodeURIComponent(safeSlug)}?tenant=${encodeURIComponent(publicTenant)}`, {
        credentials: "include",
      });
      const eventData = await readJsonOrText(eventRes);
      const itemsRes = await fetch(
        `/api/public/sale-items?tenant=${encodeURIComponent(publicTenant)}&event_slug=${encodeURIComponent(safeSlug)}`,
        { credentials: "include" }
      );
      const itemsData = await readJsonOrText(itemsRes);
      const items = Array.isArray(itemsData) ? itemsData : itemsData?.items || [];
      const ticketItems = (items || []).filter((it) => String(it?.kind || "ticket").toLowerCase() === "ticket");
      setStaffSaleItems(ticketItems);
      setStaffAccess((prev) => ({
        ...prev,
        title: String(eventData?.title || prev.title || safeSlug),
      }));
      setValidatorEvent({ slug: safeSlug, title: String(eventData?.title || safeSlug) });
      if (ticketItems?.[0]?.id) {
        setStaffPosDraft((prev) => ({ ...prev, sale_item_id: String(prev.sale_item_id || ticketItems[0].id) }));
      }
    } catch (e) {
      setStaffPosError(String(e?.message || "No se pudo cargar el contexto de staff."));
    }
  };

  const issueStaffPosSale = async () => {
    const eventSlug = String(staffAccess?.slug || "").trim();
    const staffToken = String(staffAccess?.token || "").trim();
    const saleItemId = parseInt(String(staffPosDraft.sale_item_id || "").trim(), 10);
    const quantity = parseInt(String(staffPosDraft.quantity || "").trim(), 10);

    if (!eventSlug || !staffToken) {
      setStaffPosError("Link staff inválido o vencido.");
      return;
    }
    if (!Number.isFinite(saleItemId) || saleItemId <= 0) {
      setStaffPosError("Seleccioná un ticket para registrar la venta.");
      return;
    }
    if (!Number.isFinite(quantity) || quantity <= 0) {
      setStaffPosError("Ingresá una cantidad válida.");
      return;
    }

    setStaffPosBusy(true);
    setStaffPosError("");
    setStaffPosResult(null);
    try {
      const qs = new URLSearchParams({ tenant_id: publicTenant });
      const res = await fetchJson(`/api/producer/events/${encodeURIComponent(eventSlug)}/pos-sale?${qs.toString()}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-staff-token": staffToken,
        },
        body: JSON.stringify(buildStaffPosPayload({ publicTenant, staffPosDraft, saleItemId, quantity })),
      });
      setStaffPosResult(normalizeStaffPosResult({
        response: res,
        quantity,
        paymentMethod: staffPosDraft.payment_method,
      }));
    } catch (e) {
      setStaffPosError(String(e?.message || e));
    } finally {
      setStaffPosBusy(false);
    }
  };

  const stopQrScanner = () => {
    if (scannerRafRef.current) {
      cancelAnimationFrame(scannerRafRef.current);
      scannerRafRef.current = null;
    }
    if (scannerStreamRef.current) {
      try {
        scannerStreamRef.current.getTracks().forEach((t) => t.stop());
      } catch {}
      scannerStreamRef.current = null;
    }
    if (scannerVideoRef.current) {
      try {
        scannerVideoRef.current.srcObject = null;
      } catch {}
    }
    scannerBusyRef.current = false;
    setScannerActive(false);
  };

  const submitQrValidation = async (tokenFromScanner = "") => {
    const qrToken = String(tokenFromScanner || validatorInput || "").trim();
    if (!qrToken) {
      setValidatorResult({ ok: false, detail: "Ingresá o escaneá un QR token para validar." });
      return;
    }

    setValidatorLoading(true);
    setValidatorResult(null);
    try {
      const staffToken = String(staffAccess?.token || "").trim();
      const r = await fetch("/api/orders/validate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(staffToken ? { "x-staff-token": staffToken } : {}),
        },
        credentials: "include",
        body: JSON.stringify(buildValidateQrPayload({ qrToken, validatorEvent, staffToken })),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) {
        setValidatorResult({ ok: false, detail: data?.detail || "No se pudo validar el QR." });
        return;
      }
      setValidatorResult({ ok: true, ...data });
    } catch (e) {
      setValidatorResult({ ok: false, detail: e?.message || "No se pudo validar el QR." });
    } finally {
      setValidatorLoading(false);
    }
  };

  const prepareNextQrScan = async () => {
    setValidatorInput("");
    setValidatorResult(null);
    setScannerError("");
    if (!scannerActive) {
      await startQrScanner();
    }
    requestAnimationFrame(() => {
      try {
        validatorInputRef.current?.focus();
      } catch {}
    });
  };

  const startQrScanner = async () => {
    setScannerError("");
    if (!navigator?.mediaDevices?.getUserMedia) {
      setScannerError("Tu navegador no permite abrir la cámara.");
      return;
    }

    if (!("BarcodeDetector" in window)) {
      setScannerError("Tu navegador no soporta escaneo QR automático. Pegá el token manualmente.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      scannerStreamRef.current = stream;
      const video = scannerVideoRef.current;
      if (!video) {
        stopQrScanner();
        return;
      }
      video.srcObject = stream;
      await video.play();
      setScannerActive(true);

      const detector = new window.BarcodeDetector({ formats: ["qr_code"] });

      const scan = async () => {
        const v = scannerVideoRef.current;
        if (!v || !scannerStreamRef.current) return;

        try {
          if (!scannerBusyRef.current) {
            const codes = await detector.detect(v);
            if (codes?.length) {
              const raw = String(codes[0]?.rawValue || "").trim();
              if (raw) {
                scannerBusyRef.current = true;
                setValidatorInput(raw);
                stopQrScanner();
                await submitQrValidation(raw);
                return;
              }
            }
          }
        } catch {
          // seguimos intentando mientras la cámara esté activa
        }

        scannerRafRef.current = requestAnimationFrame(scan);
      };

      scannerRafRef.current = requestAnimationFrame(scan);
    } catch (e) {
      stopQrScanner();
      setScannerError(e?.message || "No se pudo iniciar la cámara.");
    }
  };

  useEffect(() => {
    if (!isStaffValidatorView) stopQrScanner();
    return () => stopQrScanner();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStaffValidatorView, view]);

  const normalizeSoldTicketRow = (t = {}) => {
    let qrData = {};
    if (t?.qr_payload && typeof t.qr_payload === "object") qrData = t.qr_payload;
    if (t?.qr_payload && typeof t.qr_payload === "string") {
      try {
        const parsed = JSON.parse(t.qr_payload);
        if (parsed && typeof parsed === "object") qrData = parsed;
      } catch {}
    }

    const holderData = qrData?.buyer || qrData?.holder || qrData?.customer || {};
    const metaData = qrData?.metadata || {};
    const pickFirst = (...values) => {
      for (const value of values) {
        if (value === null || value === undefined) continue;
        const str = String(value).trim();
        if (str) return str;
      }
      return "-";
    };

    const fullName = pickFirst(t.buyer_name, t.full_name, t.holder_name, t.name, holderData.full_name, holderData.name, holderData.fullName, metaData.full_name, metaData.name);
    const dni = pickFirst(t.buyer_dni, t.dni, t.document, t.document_number, t.documentNumber, holderData.dni, holderData.document, holderData.document_number, metaData.dni, metaData.document, metaData.document_number);
    const email = pickFirst(t.buyer_email, t.email, t.mail, holderData.email, metaData.email);
    const phone = pickFirst(t.buyer_phone, t.phone, t.cellphone, t.mobile, holderData.phone, holderData.cellphone, holderData.mobile, metaData.phone, metaData.cellphone, metaData.mobile);
    const address = pickFirst(t.buyer_address, t.address, holderData.address, metaData.address);
    const province = pickFirst(t.buyer_province, t.province, holderData.province, metaData.province);
    const postalCode = pickFirst(t.buyer_postal_code, t.postal_code, t.zip_code, holderData.postal_code, holderData.zip_code, metaData.postal_code, metaData.zip_code);
    const birthDate = pickFirst(
      t.buyer_birth_date,
      t.birth_date,
      t.birthDate,
      t.date_of_birth,
      holderData.birth_date,
      holderData.birthDate,
      holderData.date_of_birth,
      metaData.birth_date,
      metaData.birthDate,
      metaData.date_of_birth
    );
    const status = t.status || "-";
    const ticketId = t.ticket_id || t.ticketId || "-";
    const orderId = t.order_id || t.orderId || t.external_reference || "-";
    const soldAtRaw = t.sold_at || t.created_at || t.purchased_at || null;
    const soldAtDate = soldAtRaw ? new Date(soldAtRaw) : null;
    const soldAt = soldAtDate && !Number.isNaN(soldAtDate.getTime())
      ? soldAtDate.toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" })
      : "-";
    return { fullName, dni, email, phone, address, province, postalCode, birthDate, status, ticketId, orderId, soldAt, soldAtRaw };
  };

  const filteredSoldTicketRows = useMemo(() => {
    const q = (soldTicketsSearch || "").trim().toLowerCase();
    if (!q) return soldTicketsModal.rows || [];
    return (soldTicketsModal.rows || []).filter((row) => {
      const n = normalizeSoldTicketRow(row);
      const haystack = `${n.fullName} ${n.email} ${n.phone} ${n.dni} ${n.address} ${n.province} ${n.postalCode} ${n.birthDate} ${n.orderId} ${n.ticketId}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [soldTicketsModal.rows, soldTicketsSearch]);

  const filteredBarOrderRows = useMemo(() => {
    const q = (barOrdersSearch || "").trim().toLowerCase();
    if (!q) return barOrdersModal.rows || [];
    return (barOrdersModal.rows || []).filter((row) => {
      const n = normalizeBarOrderRow(row);
      const haystack = `${n.fullName} ${n.email} ${n.phone} ${n.dni} ${n.orderId}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [barOrdersModal.rows, barOrdersSearch]);

  const filteredSellerSalesRows = useMemo(() => {
    const q = (sellerSalesSearch || "").trim().toLowerCase();
    if (!q) return sellerSalesModal.rows || [];
    return (sellerSalesModal.rows || []).filter((row) => {
      const haystack = `${row?.seller_name || ""} ${row?.seller_code || ""} ${row?.tickets_sold || 0} ${row?.orders_paid || 0}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [sellerSalesModal.rows, sellerSalesSearch]);

  const filteredAdminBarSalesRows = useMemo(() => {
    const q = (adminBarSalesSearch || "").trim().toLowerCase();
    if (!q) return adminBarSalesModal.rows || [];
    return (adminBarSalesModal.rows || []).filter((o) => {
      const haystack = `${o?.id || ""} ${o?.buyer_email || ""}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [adminBarSalesModal.rows, adminBarSalesSearch]);

  const downloadSoldTicketsCsv = (ev, rows = []) => {
    const slug = ev?.slug || ev?.event_slug || "evento";
    const headers = ["Nombre", "DNI", "Mail", "Celular", "Domicilio", "Provincia", "Código Postal", "Nacimiento", "Estado", "Fecha/Hora compra", "Ticket ID", "Order ID"];
    const escapeCsv = (value) => {
      const safe = String(value ?? "-").replace(/\r?\n|\r/g, " ");
      return `"${safe.replace(/"/g, '""')}"`;
    };

    const lines = rows.map((row) => {
      const normalized = normalizeSoldTicketRow(row);
      return [
        normalized.fullName,
        normalized.dni,
        normalized.email,
        normalized.phone,
        normalized.address,
        normalized.province,
        normalized.postalCode,
        normalized.birthDate,
        normalized.status,
        normalized.soldAt,
        normalized.ticketId,
        normalized.orderId,
      ].map(escapeCsv).join(",");
    });

    const csv = [headers.join(","), ...lines].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = `${slug}-tickets-vendidos.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(href);
  };

  const openSoldTicketsModal = async (ev, opts = {}) => {
    const slug = ev?.slug || ev?.event_slug;
    if (!slug) return;

    const isAdminMode = !!opts?.adminMode || view === "supportAI";
    setSoldTicketsSearch("");
    setSoldTicketsModal({ open: true, event: ev, rows: [], loading: true, error: "" });
    try {
      const url = isAdminMode
        ? `/api/support/ai/admin/sold-tickets?tenant_id=${encodeURIComponent(tenantId)}&event_slug=${encodeURIComponent(slug)}`
        : `/api/producer/events/${encodeURIComponent(slug)}/sold-tickets?tenant_id=${encodeURIComponent(tenantId)}&format=json`;
      const res = await fetch(url, { credentials: "include" });
      if (!res.ok) {
        const err = await res.text().catch(() => "");
        throw new Error(err || `No se pudo obtener el listado (${res.status})`);
      }
      const data = await res.json();
      const rows = Array.isArray(data?.tickets) ? data.tickets : [];
      setSoldTicketsModal({ open: true, event: ev, rows, loading: false, error: "" });
    } catch (e) {
      setSoldTicketsModal({
        open: true,
        event: ev,
        rows: [],
        loading: false,
        error: e?.message || "No se pudo cargar el listado de tickets.",
      });
    }
  };

  const cancelTicketFromAdmin = async (ticket) => {
    const slug = soldTicketsModal?.event?.slug || soldTicketsModal?.event?.event_slug;
    const ticketId = String(ticket?.ticket_id || ticket?.id || "").trim();
    if (!slug || !ticketId) return;

    const ok = confirm(`¿Cancelar ticket ${ticketId}? Esta acción lo dejará inválido para validación.`);
    if (!ok) return;

    setAdminCancelingTicketId(ticketId);
    try {
      const url = `/api/producer/events/${encodeURIComponent(slug)}/tickets/${encodeURIComponent(ticketId)}/cancel?tenant_id=${encodeURIComponent(tenantId)}`;
      const res = await fetch(url, { method: "POST", credentials: "include" });
      const data = await readJsonOrText(res);
      if (!res.ok || !data?.ok) throw new Error(data?.detail || "No se pudo cancelar el ticket.");

      setSoldTicketsModal((prev) => ({
        ...prev,
        rows: (prev.rows || []).map((r) =>
          String(r?.ticket_id || r?.id || "") === ticketId
            ? { ...r, status: "cancelled" }
            : r
        ),
      }));
      alert("Ticket cancelado correctamente.");
    } catch (e) {
      alert(e?.message || "No se pudo cancelar el ticket.");
    } finally {
      setAdminCancelingTicketId("");
    }
  };

  const normalizeBarOrderRow = (o = {}) => {
    const fullName = o.buyer_name || o.full_name || o.name || "-";
    const dni = o.buyer_dni || o.dni || o.document_number || "-";
    const email = o.buyer_email || o.email || "-";
    const phone = o.buyer_phone || o.phone || o.cellphone || "-";
    const status = o.status || "-";
    const orderId = o.order_id || o.id || "-";
    const totalCents = Number(o.total_cents || 0);
    const total = `$${Math.round(totalCents / 100).toLocaleString()}`;
    const soldAtRaw = o.created_at || o.sold_at || null;
    const soldAtDate = soldAtRaw ? new Date(soldAtRaw) : null;
    const soldAt = soldAtDate && !Number.isNaN(soldAtDate.getTime())
      ? soldAtDate.toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" })
      : "-";
    return { fullName, dni, email, phone, status, orderId, total, soldAt };
  };

  const openBarOrdersModal = async (ev) => {
    const slug = ev?.slug || ev?.event_slug;
    if (!slug) return;

    setBarOrdersSearch("");
    setBarOrdersModal({ open: true, event: ev, rows: [], loading: true, error: "", totalCents: 0 });

    try {
      const url = `/api/producer/events/${encodeURIComponent(slug)}/bar-orders?tenant_id=${encodeURIComponent(tenantId)}`;
      const res = await fetch(url, { credentials: "include" });
      if (!res.ok) {
        if (res.status === 404) {
          setBarOrdersModal({ open: true, event: ev, rows: [], loading: false, error: "", totalCents: 0 });
          return;
        }
        const txt = await res.text().catch(() => "");
        throw new Error(txt || `producer_bar_orders_${res.status}`);
      }
      const data = await res.json().catch(() => ({}));
      const rows = Array.isArray(data?.orders) ? data.orders : [];
      setBarOrdersModal({
        open: true,
        event: ev,
        rows,
        loading: false,
        error: "",
        totalCents: Number(data?.bar_revenue_cents || 0),
      });
    } catch (e) {
      const raw = String(e?.message || "");
      const friendly = raw.includes('{"detail":"Not Found"}') || raw.includes('Not Found')
        ? "No se encontró el endpoint de detalle de barra en este deploy."
        : (e?.message || "No se pudo cargar el listado de pedidos de barra.");
      setBarOrdersModal({
        open: true,
        event: ev,
        rows: [],
        loading: false,
        error: friendly,
        totalCents: 0,
      });
    }
  };

  const openSellerSalesModal = async (ev) => {
    const slug = ev?.slug || ev?.event_slug;
    if (!slug) return;

    setSellerSalesSearch("");
    setSellerSalesModal({ open: true, event: ev, rows: [], loading: true, error: "", totalTickets: 0 });

    try {
      const url = `/api/producer/events/${encodeURIComponent(slug)}/seller-sales?tenant_id=${encodeURIComponent(tenantId)}`;
      const data = await fetchJson(url);
      const rows = Array.isArray(data?.sellers) ? data.sellers : [];
      setSellerSalesModal({
        open: true,
        event: ev,
        rows,
        loading: false,
        error: "",
        totalTickets: Number(data?.total_tickets || 0),
      });
    } catch (e) {
      const raw = String(e?.message || "");
      const friendly = raw.includes("404")
        ? "No se encontró el endpoint de ventas por vendedores en este deploy."
        : (e?.message || "No se pudo cargar el listado de vendedores.");
      setSellerSalesModal({
        open: true,
        event: ev,
        rows: [],
        loading: false,
        error: friendly,
        totalTickets: 0,
      });
    }
  };

  const buildAudienceQueryParams = () => {
    const qs = new URLSearchParams({ tenant_id: tenantId, page: "1", page_size: "100" });
    const eventSlug = String(audienceFilters.event_slug || "").trim();
    const dateFrom = String(audienceFilters.date_from || "").trim();
    const dateTo = String(audienceFilters.date_to || "").trim();
    const saleItemId = String(audienceFilters.sale_item_id || "").trim();
    const q = String(audienceFilters.q || "").trim();
    if (eventSlug) qs.set("event_slug", eventSlug);
    if (dateFrom) qs.set("date_from", dateFrom);
    if (dateTo) qs.set("date_to", dateTo);
    if (saleItemId) qs.set("sale_item_id", saleItemId);
    if (q) qs.set("q", q);
    return qs.toString();
  };

  const loadAudience = async () => {
    setAudienceLoading(true);
    setAudienceError("");
    try {
      const data = await fetchJson(`/api/producer/audience?${buildAudienceQueryParams()}`);
      setAudienceRows(Array.isArray(data?.contacts) ? data.contacts : []);
      setAudienceTotal(Number(data?.total || 0));
    } catch (e) {
      setAudienceRows([]);
      setAudienceTotal(0);
      setAudienceError(String(e?.message || "No se pudo cargar la audiencia."));
    } finally {
      setAudienceLoading(false);
    }
  };

  const exportAudienceCsv = () => {
    const url = `/api/producer/audience/export?${buildAudienceQueryParams()}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const loadCampaigns = async () => {
    setCampaignsLoading(true);
    setCampaignsError("");
    try {
      const data = await fetchJson(`/api/producer/campaigns?tenant_id=${encodeURIComponent(tenantId)}&page=1&page_size=50`);
      setCampaignsRows(Array.isArray(data?.campaigns) ? data.campaigns : []);
    } catch (e) {
      setCampaignsRows([]);
      setCampaignsError(String(e?.message || "No se pudieron cargar campañas."));
    } finally {
      setCampaignsLoading(false);
    }
  };

  const saveCampaignDraft = async (sendNow = false) => {
    const subject = String(campaignDraft.subject || "").trim();
    const bodyHtml = String(campaignDraft.body_html || "").trim();
    const bodyText = String(campaignDraft.body_text || "").trim();
    if (!subject) {
      alert("Completá el asunto de la campaña.");
      return;
    }
    if (!bodyHtml && !bodyText) {
      alert("Completá body_html o body_text.");
      return;
    }
    setCampaignSaving(true);
    try {
      const created = await fetchJson(`/api/producer/campaigns`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId,
          name: String(campaignDraft.name || "").trim() || null,
          subject,
          body_html: bodyHtml || null,
          body_text: bodyText || null,
          audience_filters: {
            event_slug: String(audienceFilters.event_slug || "").trim() || null,
            date_from: String(audienceFilters.date_from || "").trim() || null,
            date_to: String(audienceFilters.date_to || "").trim() || null,
            sale_item_id: String(audienceFilters.sale_item_id || "").trim() ? Number(audienceFilters.sale_item_id) : null,
            q: String(audienceFilters.q || "").trim() || null,
          },
        }),
      });
      const campaignId = String(created?.campaign?.id || "").trim();
      if (sendNow && campaignId) {
        await fetchJson(`/api/producer/campaigns/${encodeURIComponent(campaignId)}/send?tenant_id=${encodeURIComponent(tenantId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirm: true }),
        });
      }
      setCampaignDraft({ name: "", subject: "", body_html: "", body_text: "" });
      setMarketingSection("campaigns");
      await loadCampaigns();
      alert(sendNow ? "Campaña enviada." : "Campaña guardada en draft.");
    } catch (e) {
      alert(String(e?.message || e));
    } finally {
      setCampaignSaving(false);
    }
  };

  const openCampaignDetail = async (campaign) => {
    if (!campaign?.id) return;
    setSelectedCampaign(campaign);
    setCampaignDeliveries([]);
    setCampaignDeliveriesLoading(true);
    try {
      const detail = await fetchJson(`/api/producer/campaigns/${encodeURIComponent(campaign.id)}?tenant_id=${encodeURIComponent(tenantId)}`);
      const deliveries = await fetchJson(`/api/producer/campaigns/${encodeURIComponent(campaign.id)}/deliveries?tenant_id=${encodeURIComponent(tenantId)}&page=1&page_size=100`);
      setSelectedCampaign(detail?.campaign || campaign);
      setCampaignDeliveries(Array.isArray(deliveries?.deliveries) ? deliveries.deliveries : []);
      setMarketingSection("detail");
    } catch (e) {
      alert(String(e?.message || e));
    } finally {
      setCampaignDeliveriesLoading(false);
    }
  };

  const openStaffLinksModal = (ev) => {
    setStaffLinksModal({
      open: true,
      event: ev,
      loading: false,
      error: "",
      hours_valid: 12,
      validateLink: "",
      posLink: "",
    });
  };

  const generateStaffLink = async (scope) => {
    const ev = staffLinksModal?.event;
    const slug = String(ev?.slug || ev?.event_slug || "").trim();
    if (!slug) return;
    setStaffLinksModal((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const qs = new URLSearchParams({ tenant_id: tenantId });
      const data = await fetchJson(`/api/producer/events/${encodeURIComponent(slug)}/staff-link?${qs.toString()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId,
          scope,
          hours_valid: Number(staffLinksModal.hours_valid || 12),
        }),
      });
      const link = String(data?.link || "").trim();
      if (!link) throw new Error("No se pudo generar el link.");
      setStaffLinksModal((prev) => ({
        ...prev,
        loading: false,
        error: "",
        validateLink: scope === "validate" ? link : prev.validateLink,
        posLink: scope === "pos" ? link : prev.posLink,
      }));
      try { await navigator.clipboard.writeText(link); } catch {}
    } catch (e) {
      setStaffLinksModal((prev) => ({ ...prev, loading: false, error: String(e?.message || e) }));
    }
  };

  useEffect(() => {
    if (isProducerView) {
      window.scrollTo({ top: 0, behavior: "auto" });
      loadProducerEvents();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, adminEventFilter]);

  useEffect(() => {
    if (!isProducerView) return;
    if (marketingSection === "audience") {
      loadAudience();
    } else if (marketingSection === "campaigns") {
      loadCampaigns();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, marketingSection, audienceFilters.event_slug, audienceFilters.date_from, audienceFilters.date_to, audienceFilters.sale_item_id, audienceFilters.q]);

  useEffect(() => {
    if (me?.email) {
      loadSupportAIStatus();
    } else {
      setSupportAiStatus(null);
      if (view === "supportAI") setView("public");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.email]);

  useEffect(() => {
    if (isProducerView && selectedProducerEventSlug) {
      loadProducerDashboard(selectedProducerEventSlug);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, selectedProducerEventSlug]);

  const handleCheckout = async (method, forcedUser = null) => {
  // Validación visual (sin alerts)
  setCheckoutTouched({
    fullName: true,
    dni: true,
    phone: true,
    address: true,
    province: true,
    postalCode: true,
    birthDate: true,
    acceptTerms: true,
  });

  if (!selectedTicket || hasCheckoutErrors) {
    return;
  }
  if (isEventSoldOut(selectedEvent)) {
    alert("Este evento está SOLD OUT. No se pueden comprar más entradas.");
    return;
  }

  // login obligatorio en checkout
    const userNow = forcedUser || me;
    if (!userNow) {
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
        body: JSON.stringify(buildOrderPayload({
          publicTenant,
          selectedEvent,
          selectedTicket,
          quantity,
          method,
          selectedSellerCode,
          checkoutForm,
          userNow,
        })),
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
        const pref = await createMpPreference({
          publicTenant,
          orderId: data.order_id,
          readJsonOrText,
        });
        try {
          const debugPayload = {
            at: new Date().toISOString(),
            order_id: pref?.order_id || data?.order_id || null,
            mp_preference_id: pref?.mp_preference_id || null,
            split_applied: pref?.split_applied,
            split_collector_id: pref?.split_collector_id || null,
            split_collector_source: pref?.split_collector_source || null,
            split_platform_user_id: pref?.split_platform_user_id || null,
            settlement_mode: pref?.settlement_mode || null,
            split_event_cfg_found: pref?.split_event_cfg_found,
            split_event_settlement_mode: pref?.split_event_settlement_mode || null,
            split_event_mp_collector_id: pref?.split_event_mp_collector_id || null,
            split_event_slug: pref?.split_event_slug || null,
          };
          sessionStorage.setItem("mp_last_create_preference", JSON.stringify(debugPayload));
          console.info("[MP create-preference debug]", debugPayload);
        } catch (_) {}
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

  useEffect(() => {
    if (view !== "success") return;
    const orderId = String(purchaseData?.order_id || "").trim();
    if (!orderId) return;

    let cancelled = false;
    let tries = 0;
    setSuccessProcessing(true);
    setSuccessTries(0);
    setSuccessMessage(null);

    const run = async () => {
      if (cancelled) return;
      tries += 1;
      setSuccessTries(tries);
      try {
        const r = await fetch(`/api/orders/my-assets?tenant=${encodeURIComponent(publicTenant)}`, { credentials: "include" });
        const data = await readJsonOrText(r);
        if (r.ok && data?.ok) {
          const assets = Array.isArray(data.assets) ? data.assets : [];
          const orderAssets = assets.filter((a) => String(a?.order_id || "") === orderId);
          const found = orderAssets.filter((a) => a?.ticket_id || a?.qr_payload);
          if (found.length > 0) {
            setPurchaseData((prev) => ({
              ...prev,
              tickets: found,
              quantity: found.length || prev?.quantity || 1,
              event: (prev?.event?.title && prev?.event?.title !== "Tu evento") ? prev.event : { title: found[0]?.event_title || found[0]?.event_slug || "Tu evento" },
            }));
            setSuccessProcessing(false);
            setSuccessMessage("Podés descargar y compartir tus tickets. También te los enviamos por mail.");
            return;
          }
        }
      } catch (e) {
        // keep polling, we only show final timeout message
      }

      if (tries >= 12) {
        setSuccessProcessing(false);
        setSuccessMessage("Estamos confirmando el pago, revisá Mis Tickets en unos segundos.");
      }
    };

    run();
    const id = setInterval(run, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [view, purchaseData?.order_id]);

  useEffect(() => {
    const syncViewFromPath = () => {
      const route = parseAppLocation(window.location);

      if (route.type === "event") {
        if (selectedEvent?.slug !== route.slug || view !== "detail") {
          openPublicEvent(route.slug);
        }
        return;
      }

      if (route.type === "staff") {
        setStaffAccess({
          active: !!route.token,
          slug: route.slug,
          mode: route.mode,
          token: route.token,
          title: route.slug,
        });
        setValidatorEvent({ slug: route.slug, title: route.slug });
        setValidatorInput("");
        setValidatorResult(null);
        setStaffPosError(route.token ? "" : "Falta token de staff en el link.");
        setView(route.mode === "pos" ? staffPosView : staffValidatorView);
        loadStaffEventContext(route.slug);
        return;
      }

      setView((prev) => (prev === "detail" ? "public" : prev));
    };

    syncViewFromPath();
    window.addEventListener("popstate", syncViewFromPath);
    return () => window.removeEventListener("popstate", syncViewFromPath);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);



  const connectMpOauth = async () => {
    try {
      if (!editFormData) return;
      setMpOauthBusy(true);
      const tenantIdForOauth = editFormData?.tenant_id || defaultRuntimeConfig.publicTenant;
      const r = await fetch(`/api/payments/mp/oauth/start?tenant=${encodeURIComponent(tenantIdForOauth)}`, {
        credentials: "include",
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error((data && data.detail) || "No se pudo iniciar OAuth de Mercado Pago");

      const authUrl = String(data?.auth_url || "").trim();
      if (!authUrl) throw new Error("No se recibió auth_url de Mercado Pago");

      const popup = window.open(authUrl, "mp_oauth", "width=560,height=760");
      if (!popup) throw new Error("No se pudo abrir la ventana de autorización. Revisá el bloqueador de popups.");

      await new Promise((resolve, reject) => {
        let done = false;
        let closeGraceTimeoutId = 0;

        const cleanup = () => {
          if (done) return;
          done = true;
          window.clearTimeout(timeoutId);
          window.clearTimeout(closeGraceTimeoutId);
          window.clearInterval(popupWatcher);
          window.removeEventListener("message", onMessage);
        };

        const timeoutId = window.setTimeout(() => {
          cleanup();
          reject(new Error("Tiempo de espera agotado para la autorización de Mercado Pago"));
        }, 120000);

        const onMessage = (ev) => {
          const msg = ev?.data || {};
          if (!msg || msg.type !== "mp_oauth_success") return;
          const userId = String(msg.user_id || "").trim();
          cleanup();
          if (!userId) {
            reject(new Error("Mercado Pago respondió sin user_id"));
            return;
          }
          setEditFormData((prev) => (prev ? { ...prev, mp_collector_id: userId } : prev));
          resolve(true);
        };

        const popupWatcher = window.setInterval(() => {
          if (!popup.closed || done) return;
          window.clearTimeout(closeGraceTimeoutId);
          closeGraceTimeoutId = window.setTimeout(() => {
            if (done) return;
            cleanup();
            reject(new Error("La ventana de autorización se cerró antes de completar el proceso"));
          }, 700);
        }, 500);

        window.addEventListener("message", onMessage);
      });

      alert("Cuenta de Mercado Pago conectada. Se cargó el Collector ID automáticamente.");
    } catch (e) {
      alert(`Error en conexión OAuth: ${e?.message || e}`);
    } finally {
      setMpOauthBusy(false);
    }
  };

  const openEditor = (ev = null, initialTab = "info") => {
    setIsEditing(true);
    setActiveTab(initialTab);
    if (ev) {
      const copy = JSON.parse(JSON.stringify(ev));
      copy._is_new = false;
      if (!copy.slug) copy.slug = copy.event_slug || copy.eventSlug || "";

      if (!copy.start_date && typeof copy.date_text === "string") {
        const m = copy.date_text.match(/^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?/);
        if (m) {
          copy.start_date = m[1];
          if (!copy.start_time && m[2]) copy.start_time = m[2];
        }
      }

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
        visibility: "public",
        settlement_mode: "manual_transfer",
        mp_collector_id: "",
        accept_terms: true,
        stock_total: 0,
        stock_sold: 0,
        revenue: 0,
        items: [{ id: 1, name: "General", price: 0, stock: 0, sold: 0 }],
        sellers: [{ id: 1, name: "Staff", code: "CODE", sales: 0 }],
      });
    }
  };


  // Subida de flyer al Disk de Render (backend). Devuelve URL relativa (/uploads/..)
  const uploadFlyerForEvent = async (slug, file) => {
    if (!slug) throw new Error("slug requerido para subir flyer");
    if (!file) throw new Error("archivo requerido para subir flyer");
    const tenantId = editFormData?.tenant_id || defaultRuntimeConfig.publicTenant;
    const fd = new FormData();
    fd.append("file", file);

    const r = await fetch(`/api/producer/events/${slug}/flyer?tenant_id=${encodeURIComponent(tenantId)}`, {
      method: "POST",
      credentials: "include",
      body: fd,
    });

    const data = await readJsonOrText(r);
    if (!r.ok) throw new Error(normalizeErrorDetail(data, r, "No se pudo subir el flyer"));
    return data?.url;
  };


  const saveEvent = async (finalize = true, closeOnSuccess = true) => {
    if (!editFormData) return;

    if (finalize && !editFormData.accept_terms) {
      alert("Para publicar un evento tenés que aceptar Términos y Condiciones.");
      return;
    }

    try {
      // login requerido para productor/admin
      if (!me) {
        openLoginModal({});
        return;
      }

      // En Administrador, usamos endpoints admin para crear/actualizar sin depender del owner del staff.
      if (view === "supportAI" && editFormData?._is_new) {
        const ownerEmail = String(adminOwnerEmailForEditor || "").trim();
        if (!ownerEmail) {
          alert("Antes de guardar, indicá email/owner para asignar el evento.");
          return;
        }

        const rAdmin = await fetch("/api/support/ai/admin/events/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            tenant_id: tenantId,
            owner_tenant: ownerEmail,
            title: editFormData.title || "Nuevo Evento",
            city: editFormData.city || null,
            date_text: editFormData.date_text || null,
            venue: editFormData.venue || null,
            description: editFormData.description || null,
            flyer_url: editFormData.flyer_url || null,
            hero_bg: editFormData.hero_bg || null,
            visibility: editFormData.visibility || "public",
          }),
        });
        const adminData = await readJsonOrText(rAdmin);
        if (!rAdmin.ok) throw new Error(normalizeErrorDetail(adminData, rAdmin, "No se pudo crear el evento desde Administrador"));

        await refreshPublicEvents();
        await loadAdminSupportData();
        setTransferForm((prev) => ({ ...prev, event_slug: String(adminData?.slug || "") }));
        alert(`Evento creado y asignado a ${ownerEmail}. Ahora podés cargar sale items en la pestaña Tickets del modal.`);
        setEditFormData((prev) => ({
          ...(prev || {}),
          _is_new: false,
          slug: String(adminData?.slug || prev?.slug || ""),
        }));
        setActiveTab("tickets");
        return true;
      }

      if (view === "supportAI" && editFormData?._is_new === false) {
        const adminUpdatePayload = {
          tenant_id: tenantId,
          event_slug: editFormData.slug,
          title: (editFormData.title ?? editFormData.name),
          date_text:
            formatEventDateText(editFormData.start_date, editFormData.start_time) ||
            editFormData.date_text ||
            editFormData.date ||
            null,
          city: editFormData.city,
          venue: editFormData.venue,
          description: editFormData.description,
          flyer_url: (editFormData.flyer_url && String(editFormData.flyer_url).startsWith("blob:")) ? null : editFormData.flyer_url,
          hero_bg: editFormData.hero_bg,
          visibility: editFormData.visibility === "unlisted" ? "unlisted" : "public",
          accept_terms: !!editFormData.accept_terms,
          contact_phone: editFormData.contact_phone,
          payout_alias: editFormData.payout_alias || null,
          cuit: editFormData.cuit || null,
          settlement_mode:
            editFormData.settlement_mode === undefined
              ? "manual_transfer"
              : editFormData.settlement_mode,
          mp_collector_id:
            editFormData.mp_collector_id === undefined
              ? null
              : editFormData.mp_collector_id,
        };

        const rAdminUpdate = await fetch("/api/support/ai/admin/events/update", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(adminUpdatePayload),
        });

        const adminUpdateData = await readJsonOrText(rAdminUpdate);
        if (!rAdminUpdate.ok) {
          throw new Error(normalizeErrorDetail(adminUpdateData, rAdminUpdate, "No se pudo guardar el evento desde Administrador"));
        }

        await refreshPublicEvents();
        await loadAdminSupportData();

        if (closeOnSuccess) {
          setIsEditing(false);
          setEditFormData(null);
        }
        return true;
      }

      const isUpdate = editFormData?._is_new === false;
      const url = isUpdate ? `/api/producer/events/${editFormData.slug}` : "/api/producer/events";
      const method = isUpdate ? "PUT" : "POST";

      const computedDateText =
        formatEventDateText(editFormData.start_date, editFormData.start_time) ||
        editFormData.date_text ||
        editFormData.date ||
        null;

      const payload = {
        title: (editFormData.title ?? editFormData.name),
        slug: editFormData.slug,
        date_text: computedDateText,
        city: editFormData.city,
        venue: editFormData.venue,
        description: editFormData.description,
        flyer_url: (editFormData.flyer_url && String(editFormData.flyer_url).startsWith("blob:")) ? null : editFormData.flyer_url,
        hero_bg: editFormData.hero_bg,
        address: editFormData.address,
        lat: editFormData.lat,
        lng: editFormData.lng,
        visibility: editFormData.visibility === "unlisted" ? "unlisted" : "public",
        accept_terms: !!editFormData.accept_terms,
        contact_phone: editFormData.contact_phone,
        payout_alias: editFormData.payout_alias || null,
        cuit: editFormData.cuit || null,
        settlement_mode:
          editFormData.settlement_mode === undefined
            ? "manual_transfer"
            : editFormData.settlement_mode,
        mp_collector_id:
          editFormData.mp_collector_id === undefined
            ? null
            : editFormData.mp_collector_id,
      };


      const r = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(payload),
      });

      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(normalizeErrorDetail(data, r, "No se pudo guardar el evento"));

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


// Si hay flyer pendiente (alta), ahora que tenemos slug real lo subimos y persistimos URL
try {
  const pendingFile = flyerPendingRef?.current || null;
  if (pendingFile && createdSlug) {
    const urlFlyer = await uploadFlyerForEvent(createdSlug, pendingFile);
    flyerPendingRef.current = null;
    // Persistimos en el form (ya está actualizado en DB por el endpoint)
    setEditFormData((p) => (p ? { ...p, flyer_url: urlFlyer } : p));
  }
} catch (e) {
  console.error(e);
  alert("Evento guardado, pero falló la subida del flyer: " + (e?.message || e));
}

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
      <header className="fixed top-0 left-0 right-0 z-50 bg-[#070912]/85 backdrop-blur-xl border-b border-white/10 overflow-x-hidden">
        <div className="max-w-7xl mx-auto w-full px-4 sm:px-6 py-3 sm:py-4">
          {/* TOP */}
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className="rounded-2xl border border-white/15 bg-[#111827]/70 p-2 shadow-[0_10px_32px_rgba(8,15,30,0.5)] flex-shrink-0">
                <img src="/logo-yendiin-casinos.svg" alt={brandConfig.headerLabel} className="h-10 sm:h-12 w-auto" loading="lazy" />
              </div>

              <div className="min-w-0">
                <div className="text-white font-black uppercase italic tracking-tight text-xl sm:text-2xl leading-none truncate">
                  {brandConfig.headerLabel}
                </div>
              </div>

              <nav className="hidden md:flex items-center justify-center gap-2 pl-3">
                <button
                  onClick={() => setView("public")}
                  className={`px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest transition-all border ${
                    view === "public" ? "bg-indigo-600/90 border-indigo-400/60 text-white" : "bg-white/5 border-white/10 hover:bg-white/10"
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
                  className={`px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest transition-all border ${
                    view === "myTickets" ? "bg-indigo-600/90 border-indigo-400/60 text-white" : "bg-white/5 border-white/10 hover:bg-white/10"
                  }`}
                >
                  Mis Tickets
                </button>


                {me && supportAiStatus?.is_staff && (
                  <button
                    onClick={() => setView("supportAI")}
                    className={`px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest transition-all border ${
                      view === "supportAI" ? "bg-indigo-600/90 border-indigo-400/60 text-white" : "bg-white/5 border-white/10 hover:bg-white/10"
                    }`}
                    title="Panel interno para staff"
                  >
                    {(featureFlags.brandedAdminLabels ? brandConfig.adminPanelLabel : "Administrador")}
                  </button>
                )}
              </nav>
            </div>

            <div className="flex items-center gap-2 flex-shrink-0">
              {/* Mobile Ingresar */}
              {!me ? (
                <button
                  onClick={() => setLoginRequired(true)}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest bg-indigo-500/15 hover:bg-indigo-500/25 transition-all border border-indigo-300/35 text-white"
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
                    className="px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/15 text-white"
                  >
                    Salir
                  </button>
                </>
              )}
            </div>
          </div>

          {/* TABS (mobile) */}
          <nav className="mt-3 md:hidden flex items-center justify-center sm:justify-start gap-2 w-full">
            <button
              onClick={() => setView("public")}
              className={`px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest transition-all border ${
                view === "public" ? "bg-indigo-600/90 border-indigo-400/60 text-white" : "bg-white/5 border-white/10 hover:bg-white/10"
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
              className={`px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest transition-all border ${
                view === "myTickets" ? "bg-indigo-600/90 border-indigo-400/60 text-white" : "bg-white/5 border-white/10 hover:bg-white/10"
              }`}
            >
              Mis Tickets
            </button>

            {me && supportAiStatus?.is_staff && (
              <button
                onClick={() => setView("supportAI")}
                className={`px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest transition-all border ${
                  view === "supportAI" ? "bg-indigo-600/90 border-indigo-400/60 text-white" : "bg-white/5 border-white/10 hover:bg-white/10"
                }`}
                title="Panel interno para staff"
              >
                {(featureFlags.brandedAdminLabels ? brandConfig.adminPanelLabel : "Administrador")}
              </button>
            )}
          </nav>
        </div>
      </header>
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
      if ((ev?.visibility || "public") !== "public") return false;
      if (filterCity !== "all" && (ev?.city || "") !== filterCity) return false;
      if (filterType !== "all" && (ev?.category || "") !== filterType) return false;
      if (!q) return true;
      const haystack = `${ev?.title || ""} ${ev?.venue || ""} ${ev?.city || ""} ${ev?.category || ""}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [events, filterCity, filterType, searchQuery]);

  const adminEventsBySlug = useMemo(() => {
    const map = new Map();
    for (const ev of adminEvents || []) {
      const slug = String(ev?.slug || "").trim();
      if (slug) map.set(slug, ev);
    }
    return map;
  }, [adminEvents]);

  const adminReportProducers = useMemo(() => {
    const set = new Set();
    for (const ev of adminEvents || []) {
      const producer = String(ev?.producer || ev?.tenant || "").trim();
      if (producer) set.add(producer);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b, "es"));
  }, [adminEvents]);

  const filteredAndSortedAdminReportEvents = useMemo(() => {
    const rows = Array.isArray(adminDashboard?.events) ? [...adminDashboard.events] : [];
    const q = String(adminReportSearch || "").trim().toLowerCase();

    const filtered = rows.filter((ev) => {
      const meta = adminEventsBySlug.get(String(ev?.slug || "")) || {};
      const title = String(ev?.title || meta?.title || "");
      const slug = String(ev?.slug || meta?.slug || "");
      const city = String(meta?.city || "");
      const venue = String(meta?.venue || "");
      const haystack = `${title} ${slug} ${city} ${venue}`.toLowerCase();
      if (q && !haystack.includes(q)) return false;

      if (adminReportSettlementFilter !== "all") {
        const mode = String(meta?.settlement_mode || "manual_transfer");
        if (adminReportSettlementFilter === "split" && mode !== "mp_split") return false;
        if (adminReportSettlementFilter === "manual" && mode === "mp_split") return false;
      }

      if (adminReportStatusFilter !== "all") {
        const paused = meta?.active === false;
        const soldOut = !!ev?.sold_out;
        if (adminReportStatusFilter === "active" && (paused || soldOut)) return false;
        if (adminReportStatusFilter === "paused" && !paused) return false;
        if (adminReportStatusFilter === "soldout" && !soldOut) return false;
      }

      if (adminReportProducerFilter !== "all") {
        const producer = String(meta?.producer || meta?.tenant || "").trim();
        if (producer !== adminReportProducerFilter) return false;
      }

      return true;
    });

    const sorted = filtered.sort((a, b) => {
      const metaA = adminEventsBySlug.get(String(a?.slug || "")) || {};
      const metaB = adminEventsBySlug.get(String(b?.slug || "")) || {};
      const titleA = String(a?.title || metaA?.title || a?.slug || "").toLowerCase();
      const titleB = String(b?.title || metaB?.title || b?.slug || "").toLowerCase();
      const ticketsA = Number(a?.tickets_sold || 0);
      const ticketsB = Number(b?.tickets_sold || 0);
      const ticketRevenueA = Number(a?.ticket_revenue_cents || 0);
      const ticketRevenueB = Number(b?.ticket_revenue_cents || 0);
      const barRevenueA = Number(a?.bar_revenue_cents || 0);
      const barRevenueB = Number(b?.bar_revenue_cents || 0);
      const scA = Number(metaA?.service_charge_pct ?? 0.15);
      const scB = Number(metaB?.service_charge_pct ?? 0.15);

      switch (adminReportSortBy) {
        case "title_desc":
          return titleB.localeCompare(titleA, "es");
        case "tickets_desc":
          return ticketsB - ticketsA;
        case "tickets_asc":
          return ticketsA - ticketsB;
        case "ticket_revenue_desc":
          return ticketRevenueB - ticketRevenueA;
        case "bar_revenue_desc":
          return barRevenueB - barRevenueA;
        case "service_desc":
          return scB - scA;
        case "service_asc":
          return scA - scB;
        case "title_asc":
        default:
          return titleA.localeCompare(titleB, "es");
      }
    });

    return sorted;
  }, [
    adminDashboard?.events,
    adminEventsBySlug,
    adminReportSearch,
    adminReportSettlementFilter,
    adminReportStatusFilter,
    adminReportProducerFilter,
    adminReportSortBy,
  ]);

  useEffect(() => {
    if (view === "supportAI") {
      loadSupportAIStatus();
      loadAdminSupportData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  useEffect(() => {
    if (view !== "supportAI") return;
    loadAdminSupportData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminEventFilter]);

  useEffect(() => {
    if (me?.email) {
      loadSupportAIStatus();
    } else {
      setSupportAiStatus(null);
      if (view === "supportAI") setView("public");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.email]);



  const loadSupportAIStatus = async () => {
    try {
      const r = await fetch("/api/support/ai/status", { credentials: "include" });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(data?.detail || "No se pudo leer estado de Soporte IA");
      setSupportAiStatus(data || null);
    } catch (e) {
      setSupportAiStatus({ error: String(e?.message || "No disponible") });
    }
  };


  const loadAdminSupportData = async () => {
    setAdminOpsError(null);
    setAdminOpsLoading(true);
    try {
      const [dR, eR, rqR] = await Promise.all([
        fetch(`/api/support/ai/admin/dashboard?tenant_id=${encodeURIComponent(tenantId)}${adminEventFilter ? `&event_slug=${encodeURIComponent(adminEventFilter)}` : ""}`, { credentials: "include" }),
        fetch(`/api/support/ai/admin/events?tenant_id=${encodeURIComponent(tenantId)}`, { credentials: "include" }),
        fetch(`/api/support/ai/admin/events/delete-requests?tenant_id=${encodeURIComponent(tenantId)}&status=pending`, { credentials: "include" }),
      ]);
      const dData = await readJsonOrText(dR);
      const eData = await readJsonOrText(eR);
      const rqData = await readJsonOrText(rqR);
      if (!dR.ok) throw new Error(dData?.detail || "No se pudo cargar dashboard admin");
      if (!eR.ok) throw new Error(eData?.detail || "No se pudo cargar eventos admin");
      if (!rqR.ok) throw new Error(rqData?.detail || "No se pudo cargar solicitudes de eliminación");
      setAdminDashboard(dData || null);
      setAdminEvents(Array.isArray(eData?.events) ? eData.events : []);
      setAdminDeleteRequests(Array.isArray(rqData?.requests) ? rqData.requests : []);
    } catch (e) {
      setAdminOpsError(String(e?.message || "No se pudieron cargar datos admin"));
      setAdminDashboard(null);
      setAdminEvents([]);
      setAdminDeleteRequests([]);
    } finally {
      setAdminOpsLoading(false);
    }
  };

  const createEventAsAdmin = async () => {
    if (!newEventForm.title.trim() || !newEventForm.owner_tenant.trim()) {
      setAdminOpsError("Title y owner_tenant son obligatorios");
      return;
    }
    setAdminOpsError(null);
    setAdminOpsLoading(true);
    try {
      const r = await fetch("/api/support/ai/admin/events/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          tenant_id: tenantId,
          owner_tenant: newEventForm.owner_tenant,
          title: newEventForm.title,
          city: newEventForm.city || null,
          date_text: newEventForm.date_text || null,
          venue: newEventForm.venue || null,
        }),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(data?.detail || "No se pudo crear evento");
      setNewEventForm({ title: "", owner_tenant: "", city: "", date_text: "", venue: "" });
      await loadAdminSupportData();
    } catch (e) {
      setAdminOpsError(String(e?.message || "No se pudo crear evento"));
    } finally {
      setAdminOpsLoading(false);
    }
  };

  const transferEventAsAdmin = async () => {
    if (!transferForm.event_slug.trim() || !transferForm.new_owner_tenant.trim()) {
      setAdminOpsError("event_slug y new_owner_tenant son obligatorios");
      return;
    }
    setAdminOpsError(null);
    setAdminOpsLoading(true);
    try {
      const r = await fetch("/api/support/ai/admin/events/transfer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          tenant_id: tenantId,
          event_slug: transferForm.event_slug,
          new_owner_tenant: transferForm.new_owner_tenant,
        }),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(data?.detail || "No se pudo transferir evento");
      setTransferForm({ event_slug: "", new_owner_tenant: "" });
      await loadAdminSupportData();
    } catch (e) {
      setAdminOpsError(String(e?.message || "No se pudo transferir evento"));
    } finally {
      setAdminOpsLoading(false);
    }
  };

  const openAdminEventCreator = () => {
    if (!adminOwnerEmailForEditor.trim()) {
      setAdminOpsError("Ingresá un email/owner para asignar el evento antes de crearlo");
      return;
    }
    setAdminOpsError(null);
    openEditor(null, "info");
  };

  const openAdminEventManager = (eventSlug, initialTab = "tickets") => {
    const slug = String(eventSlug || "").trim();
    if (!slug) {
      setAdminOpsError("Seleccioná un evento para gestionar tickets o vendedores.");
      return;
    }
    const eventMeta = adminEventsBySlug.get(slug) || { slug, title: slug };
    setAdminOpsError(null);
    openEditor(eventMeta, initialTab);
  };

  const requestDeleteEventAsProducer = async (eventSlug) => {
    if (!eventSlug) return;
    const reason = window.prompt(`Motivo de solicitud de eliminación para ${eventSlug}`) || "";
    try {
      const r = await fetch("/api/producer/events/delete-request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ tenant_id: tenantId, event_slug: eventSlug, reason }),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(data?.detail || "No se pudo solicitar eliminación");
      alert("Solicitud enviada. El admin debe aprobar y ejecutar la eliminación.");
    } catch (e) {
      alert(String(e?.message || "No se pudo solicitar eliminación"));
    }
  };

  const toggleEventPauseAsAdmin = async (eventSlug, isActive) => {
    if (!eventSlug) return;
    setAdminEventActionLoading(true);
    setAdminOpsError(null);
    try {
      const r = await fetch("/api/support/ai/admin/events/pause", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ tenant_id: tenantId, event_slug: eventSlug, is_active: !!isActive }),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(data?.detail || "No se pudo actualizar estado del evento");
      await loadAdminSupportData();
    } catch (e) {
      setAdminOpsError(String(e?.message || "No se pudo actualizar estado del evento"));
    } finally {
      setAdminEventActionLoading(false);
    }
  };

  const toggleEventSoldOutAsAdmin = async (eventSlug, soldOut) => {
    if (!eventSlug) return;
    setAdminEventActionLoading(true);
    setAdminOpsError(null);
    try {
      const r = await fetch("/api/support/ai/admin/events/sold-out", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ tenant_id: tenantId, event_slug: eventSlug, sold_out: !!soldOut }),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(data?.detail || "No se pudo actualizar estado SOLD OUT");
      await loadAdminSupportData();
      await loadProducerEvents();
      if (selectedProducerEventSlug === eventSlug) {
        await loadProducerDashboard(eventSlug);
      }
    } catch (e) {
      setAdminOpsError(String(e?.message || "No se pudo actualizar estado SOLD OUT"));
    } finally {
      setAdminEventActionLoading(false);
    }
  };

  const updateEventServiceChargeAsAdmin = async (eventSlug, currentPct) => {
    if (!eventSlug) return;
    const currentPercent = Number(currentPct || 0) * 100;
    const raw = window.prompt(
      `Nuevo service charge para ${eventSlug} (en %).\nEj: 15 para 15%`,
      Number.isFinite(currentPercent) ? String(Math.round(currentPercent * 100) / 100) : "15"
    );
    if (raw == null) return;

    const parsed = Number(String(raw).replace(",", "."));
    if (!Number.isFinite(parsed) || parsed < 0 || parsed > 100) {
      alert("Valor inválido. Ingresá un porcentaje entre 0 y 100.");
      return;
    }

    setAdminEventActionLoading(true);
    setAdminOpsError(null);
    try {
      const r = await fetch("/api/support/ai/admin/events/service-charge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          tenant_id: tenantId,
          event_slug: eventSlug,
          service_charge_pct: parsed / 100,
        }),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(data?.detail || "No se pudo actualizar service charge");
      await loadAdminSupportData();
    } catch (e) {
      setAdminOpsError(String(e?.message || "No se pudo actualizar service charge"));
    } finally {
      setAdminEventActionLoading(false);
    }
  };

  const toggleEventPauseAsProducer = async (eventSlug, isActive) => {
    if (!eventSlug) return;
    setProducerEventsLoading(true);
    setProducerEventsError(null);
    try {
      const r = await fetch("/api/producer/events/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ tenant_id: tenantId, event_slug: eventSlug, is_active: !!isActive }),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(data?.detail || "No se pudo actualizar el estado del evento");
      await loadProducerEvents();
      if (selectedProducerEventSlug === eventSlug) {
        await loadProducerDashboard(eventSlug);
      }
    } catch (e) {
      setProducerEventsError(String(e?.message || "No se pudo actualizar el estado del evento"));
    } finally {
      setProducerEventsLoading(false);
    }
  };

  const toggleEventSoldOutAsProducer = async (eventSlug, soldOut) => {
    if (!eventSlug) return;
    setProducerEventsLoading(true);
    setProducerEventsError(null);
    try {
      const r = await fetch("/api/producer/events/sold-out", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ tenant_id: tenantId, event_slug: eventSlug, sold_out: !!soldOut }),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(data?.detail || "No se pudo actualizar estado SOLD OUT");
      await loadProducerEvents();
      if (selectedProducerEventSlug === eventSlug) {
        await loadProducerDashboard(eventSlug);
      }
    } catch (e) {
      setProducerEventsError(String(e?.message || "No se pudo actualizar estado SOLD OUT"));
    } finally {
      setProducerEventsLoading(false);
    }
  };

  const deleteEventAsAdmin = async (eventSlug) => {
    if (!eventSlug) return;
    const confirmation = window.prompt(`Para eliminar ${eventSlug}, escribí ELIMINAR`);
    if (confirmation == null) return;
    setAdminEventActionLoading(true);
    setAdminOpsError(null);
    try {
      const runDelete = async (forceDeletePaid = false) => fetch("/api/support/ai/admin/events/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          tenant_id: tenantId,
          event_slug: eventSlug,
          confirm_text: confirmation,
          force_delete_paid: !!forceDeletePaid,
        }),
      });

      let r = await runDelete(false);
      let data = await readJsonOrText(r);

      const detail = String(data?.detail || "");
      const hasOrdersConflict = r.status === 409 && detail.toLowerCase().includes("órdenes");
      if (hasOrdersConflict) {
        const forceText = window.prompt(
          `El evento ${eventSlug} tiene órdenes asociadas.\nSi querés borrarlo igual (solo pruebas), escribí FORZAR`
        );
        if ((forceText || "").trim().toUpperCase() === "FORZAR") {
          r = await runDelete(true);
          data = await readJsonOrText(r);
        } else {
          throw new Error("Eliminación cancelada. No se forzó el borrado de órdenes PAID.");
        }
      }

      if (!r.ok) throw new Error(data?.detail || "No se pudo eliminar el evento");
      await loadAdminSupportData();
      if (transferForm.event_slug === eventSlug) setTransferForm((p) => ({ ...p, event_slug: "" }));
    } catch (e) {
      setAdminOpsError(String(e?.message || "No se pudo eliminar el evento"));
    } finally {
      setAdminEventActionLoading(false);
    }
  };

  const openAdminBarSalesDetail = async (eventSlug) => {
    if (!eventSlug) return;
    setAdminBarSalesSearch("");
    setAdminBarSalesModal({ open: true, eventSlug, rows: [], loading: true, error: "", totalCents: 0 });
    try {
      const r = await fetch(`/api/support/ai/admin/bar-sales?tenant_id=${encodeURIComponent(tenantId)}&event_slug=${encodeURIComponent(eventSlug)}`, { credentials: "include" });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(data?.detail || "No se pudo cargar detalle de barra");
      setAdminBarSalesModal({
        open: true,
        eventSlug,
        rows: Array.isArray(data?.orders) ? data.orders : [],
        loading: false,
        error: "",
        totalCents: Number(data?.bar_revenue_cents || 0),
      });
    } catch (e) {
      setAdminBarSalesModal({ open: true, eventSlug, rows: [], loading: false, error: String(e?.message || "No se pudo cargar detalle de barra"), totalCents: 0 });
    }
  };

  const resolveDeleteRequestAsAdmin = async (requestId, approve) => {
    setAdminEventActionLoading(true);
    setAdminOpsError(null);
    try {
      const r = await fetch("/api/support/ai/admin/events/delete-requests/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ request_id: requestId, approve, resolution_note: approve ? "Aprobado por admin" : "Rechazado por admin" }),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(data?.detail || "No se pudo resolver solicitud");
      await loadAdminSupportData();
    } catch (e) {
      setAdminOpsError(String(e?.message || "No se pudo resolver solicitud"));
    } finally {
      setAdminEventActionLoading(false);
    }
  };

  const askSupportAI = async (message) => {
    const clean = String(message || "").trim();
    if (!clean || supportAiLoading) return;

    setSupportAiError(null);
    setSupportAiLoading(true);
    setSupportAiHistory((prev) => [...prev, { role: "user", text: clean }]);

    try {
      const history = (supportAiHistory || []).slice(-8).map((m) => ({ role: m.role, text: m.text }));
      const lower = clean.toLowerCase();
      const r = await fetch("/api/support/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          message: clean,
          tenant_id: tenantId,
          user_role_hint: "support",
          context: {
            history,
            confirm_resend_order_email: lower.includes("confirm") && lower.includes("reenvi"),
          },
        }),
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error(data?.detail || "No se pudo consultar Soporte IA");

      setSupportAiHistory((prev) => [
        ...prev,
        {
          role: "assistant",
          text: data?.answer || "Sin respuesta",
          traceId: data?.trace_id || "-",
          usedTools: Array.isArray(data?.used_tools) ? data.used_tools : [],
        },
      ]);
      setSupportAiInput("");
    } catch (e) {
      setSupportAiError(String(e?.message || "No se pudo consultar Soporte IA"));
    } finally {
      setSupportAiLoading(false);
    }
  };

  const onBackFromDetail = () => window.history.back();

  const openEventFromHome = (slug) => {
    setQuantity(1);
    setCheckoutForm({ fullName: "", dni: "", phone: "", address: "", province: "", postalCode: "", birthDate: "", acceptTerms: false });
    openPublicEvent(slug);
  };

  const openMyTicketsFromSuccess = () => {
    setView("myTickets");
    setTimeout(() => {
      try { loadMyAssets(); } catch (e) {}
    }, 0);
  };

  const supportAiQuickPrompts = [
    "¿Cuántas entradas llevamos vendidas en el mes?",
    "¿Cuántos eventos activos tenemos?",
    "¿Cuántas entradas llevamos vendidas de un evento puntual?",
  ];

  // -------------------------
  // VIEWS
  // -------------------------
  return (
    <div className="min-h-screen text-white overflow-x-hidden relative">
      <Header />

      <main className="min-h-screen pt-32 sm:pt-36 relative z-10">
        {/* PUBLIC */}
        {view === "public" && (
          <PublicHomeView
            featureFlags={featureFlags}
            UI={UI}
            filteredEvents={filteredEvents}
            totalEvents={events.length}
            cities={cities}
            types={types}
            filterCity={filterCity}
            setFilterCity={setFilterCity}
            filterType={filterType}
            setFilterType={setFilterType}
            searchQuery={searchQuery}
            setSearchQuery={setSearchQuery}
            onOpenEvent={openEventFromHome}
            isEventSoldOut={isEventSoldOut}
            SoldOutRibbon={SoldOutRibbon}
            formatMoney={formatMoney}
          />
        )}

        {/* DETAIL */}
        {view === "detail" && (
          <EventDetailView
            selectedEvent={selectedEvent}
            UI={UI}
            isEventSoldOut={isEventSoldOut}
            SoldOutRibbon={SoldOutRibbon}
            buildUberLink={buildUberLink}
            buildEventGoogleMapsLink={buildEventGoogleMapsLink}
            linkifyPlainText={linkifyPlainText}
            selectedTicket={selectedTicket}
            setSelectedTicket={setSelectedTicket}
            formatMoney={formatMoney}
            checkoutForm={checkoutForm}
            setCheckoutForm={setCheckoutForm}
            checkoutTouched={checkoutTouched}
            setCheckoutTouched={setCheckoutTouched}
            checkoutError={checkoutError}
            selectedSellerCode={selectedSellerCode}
            quantity={quantity}
            setQuantity={setQuantity}
            checkoutServicePct={checkoutServicePct}
            checkoutServicePctLabel={checkoutServicePctLabel}
            loading={loading}
            checkoutBlockReason={checkoutBlockReason}
            handleCheckout={handleCheckout}
            legalConfig={legalConfig}
            onBack={onBackFromDetail}
            useAltCheckoutUx={isAltCheckoutUxEnabled}
          />
        )}
{/* PRODUCER (demo) */}
        {isProducerView && (
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
            </div>

            <div className={`p-6 sm:p-8 rounded-[2.5rem] ${UI.card} mb-10`}>
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 rounded-2xl bg-indigo-600/20 border border-indigo-600/30">
                  <Info size={18} className="text-indigo-300" />
                </div>
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Ayuda rápida</div>
                  <div className="text-xl font-black uppercase italic">Cómo usar el panel productor</div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="text-[10px] font-black uppercase tracking-widest text-indigo-300 mb-2">1. Creá o editá</div>
                  <p className="text-[11px] text-white/80 leading-relaxed">Usá <b>Nuevo</b> para crear eventos y <b>Editar</b> para actualizar datos, precios y disponibilidad.</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="text-[10px] font-black uppercase tracking-widest text-indigo-300 mb-2">2. Activá ventas</div>
                  <p className="text-[11px] text-white/80 leading-relaxed">En cada evento podés <b>Pausar/Reactivar</b> sin perder configuración ni historial de ventas.</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="text-[10px] font-black uppercase tracking-widest text-indigo-300 mb-2">3. Seguimiento en vivo</div>
                  <p className="text-[11px] text-white/80 leading-relaxed">Revisá <b>Dashboard Cruzado</b>, tickets, pedidos de barra y vendedores para decidir rápido durante el evento.</p>
                </div>
              </div>

              <div className="space-y-2">
                {[
                  {
                    q: "¿Cómo agrego entradas o productos de barra?",
                    a: "Entrá al evento y usá Gestión de tickets/sale items para crear variantes, precio y stock. Podés activar o pausar cada item cuando quieras.",
                  },
                  {
                    q: "¿Qué hace el Validador QR?",
                    a: "Escanea entradas en puerta y marca cada QR como usado. Entrás desde el botón Validador QR en cada evento. Si el código ya se validó, el sistema te avisa para evitar ingresos duplicados.",
                  },
                  {
                    q: "¿Dónde está POS Taquilla?",
                    a: "Entrá al evento y tocá POS Taquilla. Se abre la pestaña Tickets del editor con el bloque de venta presencial para emitir entradas al instante.",
                  },
                  {
                    q: "¿Cómo controlo ventas por vendedor?",
                    a: "Usá la sección Vendedores para invitar códigos y luego revisá el detalle de ventas por seller desde el botón Vendedores de cada evento.",
                  },
                ].map((item) => (
                  <details key={item.q} className="rounded-2xl border border-white/10 bg-black/30 px-4 py-3 group" open={false}>
                    <summary className="cursor-pointer list-none flex items-center justify-between gap-3">
                      <span className="text-[11px] font-black uppercase tracking-wider text-white/90">{item.q}</span>
                      <span className="text-[10px] font-black uppercase text-neutral-500 group-open:text-indigo-300">Ver</span>
                    </summary>
                    <p className="mt-3 text-[11px] text-white/75 leading-relaxed">{item.a}</p>
                  </details>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 xl:grid-cols-4 gap-4 mb-12">
              {[
                {
                  label: "Recaudación total (todos los eventos)",
                  val: `$${Math.round(((producerEvents || []).reduce((acc, ev) => acc + Number(ev.revenue_cents || ev.total_cents || 0), 0) / 100)).toLocaleString()}`,
                  icon: DollarSign,
                },
                {
                  label: "Eventos activos (totales)",
                  val: `${(producerEvents || []).filter((e) => e.active).length}`,
                  icon: CheckCircle2,
                },
                {
                  label: "Tickets vendidos (todos los eventos)",
                  val: `${(producerEvents || []).reduce((acc, ev) => acc + Number(ev.stock_sold || ev.tickets_sold || 0), 0).toLocaleString()}`,
                  icon: Ticket,
                },
                {
                  label: "Sellers (todos los eventos)",
                  val: `${(producerEvents || []).reduce((acc, ev) => acc + Number(ev.sellers_count || ev.sellers?.length || 0), 0)}`,
                  icon: Users,
                },
              ].map((k, idx) => (
                <div key={idx} className={`p-4 sm:p-5 rounded-[2rem] ${UI.card}`}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                      {k.label}
                    </div>
                    <div className="p-2 rounded-2xl bg-indigo-600/20 border border-indigo-600/30">
                      <k.icon size={18} className="text-indigo-300" />
                    </div>
                  </div>
                  <div className="text-2xl sm:text-3xl font-black uppercase italic tracking-tight">{k.val}</div>
                </div>
              ))}
            </div>

            <div className="text-[11px] text-neutral-400 mb-8 -mt-6">
              Estas métricas resumen la actividad total del productor, sumando todos los eventos de la cuenta.
            </div>

            <div className="space-y-8 mb-16">
              {/* Lista de eventos (reales, filtrados por productor en backend) */}
              <div className={`p-8 rounded-[2.5rem] ${UI.card}`}>
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
                    (() => {
                      const progress = eventSalesProgress(ev);
                      const totalTickets = Number(progress.total || 0);
                      const soldTickets = Number(progress.sold || 0);
                      const soldPercent = Math.round(progress.pct || 0);
                      const totalRevenue = Number(ev.revenue || 0) || Number(ev.revenue_cents || ev.total_cents || 0) / 100;
                      const barRevenue = Number(ev.bar_total || ev.bar_revenue || ev.bar_sales || ev.bar_revenue_cents || 0) / (ev.bar_revenue_cents ? 100 : 1);
                      const barOrders = Number(ev.bar_orders || ev.bar_orders_count || 0);
                      const ticketRevenue = Number(ev.ticket_revenue || 0) || Number(ev.ticket_revenue_cents || 0) / 100 || Math.max(0, totalRevenue - barRevenue);
                      const avgTicket = soldTickets > 0 ? ticketRevenue / soldTickets : 0;
                      const barModuleUrl = `https://ticketera-mvp.onrender.com/c?event=${encodeURIComponent(ev.slug)}&bar=principal`;
                      return (
                        <div
                          key={ev.id || ev.slug}
                          className="p-6 rounded-3xl bg-white/5 border border-white/10 flex flex-col xl:flex-row gap-6 items-start justify-between"
                        >
                          <div className="flex flex-col gap-5 w-full">
                            <div className="flex items-center gap-4">
                              <img
                                src={flyerSrc(ev)}
                                alt={ev.title}
                                className="w-20 h-20 object-cover rounded-2xl border border-white/10"
                              />
                              <div>
                                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 flex items-center gap-2 flex-wrap">
                                  <span>{ev.slug}</span>
                                  {(ev.visibility || "public") === "unlisted" && (
                                    <span className="px-2 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-200 text-[9px] tracking-wider">
                                      PRIVADO
                                    </span>
                                  )}
                                  {ev.active === false && (
                                    <span className="px-2 py-0.5 rounded-full bg-amber-500/25 border border-amber-400/60 text-amber-100 text-[9px] tracking-wider">
                                      PAUSADO
                                    </span>
                                  )}
                                  {isEventSoldOut(ev) && (
                                    <span className="px-2 py-0.5 rounded-full bg-rose-500/20 border border-rose-500/40 text-rose-200 text-[9px] tracking-wider">
                                      SOLD OUT
                                    </span>
                                  )}
                                </div>
                                <button
                                  type="button"
                                  onClick={() => openPublicEvent(ev.slug)}
                                  className="text-xl font-black uppercase text-left underline decoration-indigo-400/60 hover:decoration-indigo-300 hover:text-indigo-200 transition-colors"
                                  title="Abrir evento"
                                >
                                  {ev.title}
                                </button>
                                <div className="text-[11px] text-neutral-400 mt-1 flex items-center gap-2">
                                  <Calendar size={14} /> {ev.date_text}
                                  <span className="text-neutral-600">·</span>
                                  <MapPin size={14} /> {ev.venue}
                                </div>
                              </div>
                            </div>

                            <div className="w-full">
                              <div className="flex items-center justify-between text-[10px] font-black uppercase tracking-widest mb-2">
                                <span className="text-neutral-400">Entradas vendidas</span>
                                <span className="text-white">{soldPercent}% · {soldTickets}/{totalTickets}</span>
                              </div>
                              <div className="h-2 rounded-full bg-white/10 overflow-hidden">
                                <div
                                  className="h-full rounded-full bg-indigo-500/90"
                                  style={{ width: `${soldPercent}%` }}
                                />
                              </div>
                            </div>

                            <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
                              <div className="p-2 rounded-xl bg-white/5 border border-white/10">
                                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Recaudación neta (entradas + barra)</div>
                                <div className="mt-1 text-base font-black">${Math.round(totalRevenue).toLocaleString()}</div>
                              </div>
                              <div className="p-2 rounded-xl bg-white/5 border border-white/10">
                                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Entradas (cantidad)</div>
                                <div className="mt-1 text-base font-black">{soldTickets.toLocaleString()}</div>
                              </div>
                              <div className="p-2 rounded-xl bg-white/5 border border-white/10">
                                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Entradas (monto neto)</div>
                                <div className="mt-1 text-base font-black">${Math.round(ticketRevenue).toLocaleString()}</div>
                              </div>
                              <div className="p-2 rounded-xl bg-white/5 border border-white/10">
                                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Barra (monto neto · pedidos)</div>
                                <div className="mt-1 text-base font-black">${Math.round(barRevenue).toLocaleString()} · {barOrders.toLocaleString()}</div>
                              </div>
                              <div className="p-2 rounded-xl bg-white/5 border border-white/10">
                                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Ticket promedio</div>
                                <div className="mt-1 text-base font-black">${Math.round(avgTicket).toLocaleString()}</div>
                              </div>
                            </div>
                          </div>

                          <div className="w-full xl:w-[330px] shrink-0 space-y-2">
                            <button
                              onClick={() => openStaffLinksModal(ev)}
                              className="h-12 w-full flex items-center justify-center gap-2 rounded-2xl bg-emerald-500 hover:bg-emerald-400 text-[10px] text-black font-black uppercase tracking-widest transition-all shadow-[0_0_28px_rgba(16,185,129,0.35)]"
                            >
                              <LinkIcon size={16} /> Acceso Staff (sin login productor)
                            </button>
                            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 w-full">
                            <button
                              onClick={() => openEditor(ev)}
                              className="h-20 w-full flex items-center justify-center gap-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
                            >
                              <Edit3 size={16} /> Editar
                            </button>
                            <button
                              onClick={() => openEditor(ev, "tickets")}
                              className={`h-20 w-full flex items-center justify-center gap-2 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all ${UI.button}`}
                            >
                              <Ticket size={16} /> Cortesía
                            </button>
                            <button
                              onClick={async () => {
                                const url = `${window.location.origin}/evento/${encodeURIComponent(ev.slug)}`;
                                try {
                                  await navigator.clipboard.writeText(url);
                                  alert("Link copiado: " + url);
                                } catch {
                                  alert("Copiá este link: " + url);
                                }
                              }}
                              className="h-20 w-full flex items-center justify-center gap-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
                            >
                              Link
                            </button>
                            <button
                              onClick={() => window.open(barModuleUrl, "_blank", "noopener,noreferrer")}
                              className={`h-20 w-full flex items-center justify-center gap-2 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all ${UI.button}`}
                            >
                              <ShoppingCart size={16} /> Barra
                            </button>
                            <button
                              onClick={() => openSoldTicketsModal(ev)}
                              className="h-20 w-full flex items-center justify-center gap-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
                            >
                              <Info size={16} /> Listado de tickets
                            </button>
                            <button
                              onClick={() => openBarOrdersModal(ev)}
                              className="h-20 w-full flex items-center justify-center gap-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
                            >
                              <ShoppingCart size={16} /> Pedidos barra
                            </button>
                            <button
                              onClick={() => openSellerSalesModal(ev)}
                              className="h-20 w-full flex items-center justify-center gap-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
                            >
                              <Users size={16} /> Vendedores
                            </button>
                            <button
                              onClick={async () => toggleEventPauseAsProducer(ev.slug, ev.active === false)}
                              disabled={producerEventsLoading}
                              className={`h-20 w-full flex items-center justify-center gap-2 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all ${ev.active === false ? "bg-emerald-600 hover:bg-emerald-500" : "bg-amber-600 hover:bg-amber-500"} disabled:opacity-60`}
                            >
                              {ev.active === false ? "Reactivar" : "Pausar"}
                            </button>
                            <button
                              onClick={async () => toggleEventSoldOutAsProducer(ev.slug, !isEventSoldOut(ev))}
                              disabled={producerEventsLoading}
                              className={`h-20 w-full flex items-center justify-center gap-2 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all ${isEventSoldOut(ev) ? "bg-emerald-600 hover:bg-emerald-500" : "bg-rose-600 hover:bg-rose-500"} disabled:opacity-60`}
                            >
                              {isEventSoldOut(ev) ? "Quitar SOLD OUT" : "Marcar SOLD OUT"}
                            </button>
                            <button
                              onClick={() => openQrValidator(ev)}
                              className="h-20 w-full flex items-center justify-center gap-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
                            >
                              <QrCode size={16} /> Validador QR
                            </button>
                            </div>
                          </div>
                        </div>
                      );
                    })()
                  ))}
                  {(producerEvents || []).length === 0 && (
                    <div className="p-6 rounded-3xl bg-white/5 border border-white/10 text-sm text-white/70">
                      No tenés eventos propios todavía. Creá uno con <b>Nuevo</b>.
                    </div>
                  )}
                </div>
              </div>

              {/* DASHBOARD CRUZADO (real) */}
              <div className={`p-8 rounded-[2.5rem] ${UI.card}`}>
              <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6 mb-8">
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                    Entradas + Barra
                  </div>
                  <h2 className="text-2xl font-black uppercase italic tracking-tight">
                    Dashboard Cruzado <span className="text-indigo-600">Real</span>
                  </h2>
                  <p className="text-[11px] text-neutral-400 mt-2 max-w-2xl">
                    Acá podés ver en un solo lugar el rendimiento del evento: ventas, tickets emitidos y resumen general.
                  </p>
                </div>

                <div className="w-full lg:w-auto flex flex-col sm:flex-row items-stretch sm:items-end gap-3">
                  <div className="flex-1 sm:min-w-[340px]">
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">
                      Evento (con ventas)
                    </div>
                    <select
                      value={selectedProducerEventSlug}
                      onChange={(e) => setSelectedProducerEventSlug(e.target.value)}
                      className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 text-[11px] font-black uppercase tracking-widest text-white focus:outline-none focus:ring-2 focus:ring-indigo-600"
                      style={{ backgroundColor: "#111319", color: "#fff" }}
                      disabled={producerEventsLoading}
                    >
                      {producerEventsLoading && <option value="" style={{ backgroundColor: "#111319", color: "#fff" }}>Cargando…</option>}
                      {!producerEventsLoading && producerEvents.length === 0 && (
                        <option value="" style={{ backgroundColor: "#111319", color: "#fff" }}>Sin ventas recientes</option>
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
                            <option key={slug} value={slug} style={{ backgroundColor: "#111319", color: "#fff" }}>
                              {label}
                            </option>
                          );
                        })}
                    </select>
                  </div>

                  <button
                    onClick={() => selectedProducerEventSlug && loadProducerDashboard(selectedProducerEventSlug)}
                    disabled={!selectedProducerEventSlug || producerDashboardLoading}
                    className={`px-6 py-3 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white transition-all flex items-center gap-2 ${UI.button}`}
                  >
                    {producerDashboardLoading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
                    Actualizar
                  </button>
                  <button
                    onClick={() => refreshProducerAnalytics()}
                    disabled={producerEventsLoading || producerDashboardLoading}
                    className={`px-4 py-3 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white transition-all flex items-center justify-center gap-2 ${UI.buttonGhost}`}
                    title="Refrescar"
                  >
                    {producerEventsLoading || producerDashboardLoading ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <RefreshCw size={16} />
                    )}
                  </button>
                </div>
              </div>
              {producerEventsError && (
                <div className="mt-2 text-[10px] font-bold text-rose-400">{producerEventsError}</div>
              )}

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

                  <div className="mt-6 p-6 rounded-3xl bg-white/5 border border-white/10">
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Ventas por vendedor</div>
                    <div className="text-xl font-black uppercase italic mb-4">Sellers</div>
                    <div className="space-y-3">
                      {(producerDashboard.sellerBreakdown || []).length === 0 && (
                        <div className="text-[11px] text-neutral-500">Sin ventas atribuidas por link de seller todavía.</div>
                      )}
                      {(producerDashboard.sellerBreakdown || []).slice(0, 10).map((s, idx) => (
                        <div key={`${s.seller_code}-${idx}`} className="flex items-center justify-between gap-4 p-3 rounded-2xl bg-white/5 border border-white/10">
                          <div className="min-w-0">
                            <div className="text-[11px] font-black truncate">{s.seller_code}</div>
                            <div className="text-[10px] text-neutral-500">{s.orders} órdenes</div>
                          </div>
                          <div className="text-[11px] font-black text-indigo-300">${Number(s.revenue || 0).toLocaleString()}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                </>
              )}
            </div>

              <div className={`p-8 rounded-[2.5rem] ${UI.card}`}>
                <div className="flex items-center justify-between gap-3 mb-6">
                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Clientes y Campañas</div>
                    <div className="text-2xl font-black uppercase italic mt-1">Fidelización</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={() => setMarketingSection("audience")} className={`px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest ${marketingSection === "audience" ? "bg-indigo-600" : "bg-white/10"}`}>Audiencia</button>
                    <button onClick={() => setMarketingSection("campaigns")} className={`px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest ${marketingSection === "campaigns" ? "bg-indigo-600" : "bg-white/10"}`}>Campañas</button>
                    <button onClick={() => setMarketingSection("new")} className={`px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest ${marketingSection === "new" ? "bg-indigo-600" : "bg-white/10"}`}>Nueva</button>
                  </div>
                </div>

                {marketingSection === "audience" && (
                  <div>
                    <div className="grid grid-cols-1 md:grid-cols-5 gap-2 mb-3">
                      <select value={audienceFilters.event_slug} onChange={(e) => setAudienceFilters((p) => ({ ...p, event_slug: e.target.value }))} className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]">
                        <option value="">Todos los eventos</option>
                        {(producerEvents || []).map((ev) => <option key={ev.slug} value={ev.slug}>{ev.slug}</option>)}
                      </select>
                      <input type="date" value={audienceFilters.date_from} onChange={(e) => setAudienceFilters((p) => ({ ...p, date_from: e.target.value }))} className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]" />
                      <input type="date" value={audienceFilters.date_to} onChange={(e) => setAudienceFilters((p) => ({ ...p, date_to: e.target.value }))} className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]" />
                      <input type="text" value={audienceFilters.sale_item_id} onChange={(e) => setAudienceFilters((p) => ({ ...p, sale_item_id: e.target.value }))} placeholder="sale_item_id" className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]" />
                      <input type="text" value={audienceFilters.q} onChange={(e) => setAudienceFilters((p) => ({ ...p, q: e.target.value }))} placeholder="Buscar email/nombre" className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]" />
                    </div>
                    <div className="flex items-center gap-2 mb-3">
                      <button onClick={loadAudience} className="px-4 py-2 rounded-xl bg-white/10 border border-white/10 text-[10px] font-black uppercase">Aplicar</button>
                      <button onClick={exportAudienceCsv} className="px-4 py-2 rounded-xl bg-white/10 border border-white/10 text-[10px] font-black uppercase">Export CSV</button>
                      <button onClick={() => setMarketingSection("new")} className="px-4 py-2 rounded-xl bg-indigo-600 text-[10px] font-black uppercase">Crear campaña con filtros</button>
                      <div className="text-[11px] text-neutral-400">Total: <b className="text-white">{audienceTotal}</b></div>
                    </div>
                    {audienceLoading && <div className="text-[11px] text-white/70">Cargando audiencia...</div>}
                    {!!audienceError && <div className="text-[11px] text-rose-300">{audienceError}</div>}
                    {!audienceLoading && !audienceError && (
                      <div className="overflow-auto rounded-2xl border border-white/10">
                        <table className="w-full min-w-[760px] text-[11px]">
                          <thead className="bg-white/5"><tr><th className="px-3 py-2 text-left">Email</th><th className="px-3 py-2 text-left">Nombre</th><th className="px-3 py-2 text-left">Última compra</th><th className="px-3 py-2 text-left">Órdenes</th><th className="px-3 py-2 text-left">Último evento</th><th className="px-3 py-2 text-left">Tipo ticket</th></tr></thead>
                          <tbody>
                            {(audienceRows || []).map((r, idx) => (
                              <tr key={`${r.email_norm || r.email}-${idx}`} className="border-t border-white/10">
                                <td className="px-3 py-2">{r.email}</td><td className="px-3 py-2">{r.name || "-"}</td><td className="px-3 py-2">{r.last_purchase_at ? new Date(r.last_purchase_at).toLocaleString("es-AR") : "-"}</td><td className="px-3 py-2">{r.orders_count || 0}</td><td className="px-3 py-2">{r.last_event_slug || "-"}</td><td className="px-3 py-2">{r.last_ticket_type || "-"}</td>
                              </tr>
                            ))}
                            {(audienceRows || []).length === 0 && <tr><td colSpan={6} className="px-3 py-6 text-center text-neutral-500">Sin resultados.</td></tr>}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}

                {marketingSection === "campaigns" && (
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <div className="text-[11px] text-neutral-400">Campañas del productor</div>
                      <button onClick={loadCampaigns} className="px-4 py-2 rounded-xl bg-white/10 border border-white/10 text-[10px] font-black uppercase">Refrescar</button>
                    </div>
                    {campaignsLoading && <div className="text-[11px] text-white/70">Cargando campañas...</div>}
                    {!!campaignsError && <div className="text-[11px] text-rose-300">{campaignsError}</div>}
                    {!campaignsLoading && !campaignsError && (
                      <div className="overflow-auto rounded-2xl border border-white/10">
                        <table className="w-full min-w-[760px] text-[11px]">
                          <thead className="bg-white/5"><tr><th className="px-3 py-2 text-left">Fecha</th><th className="px-3 py-2 text-left">Asunto</th><th className="px-3 py-2 text-left">Estado</th><th className="px-3 py-2 text-left">Destinatarios</th><th className="px-3 py-2 text-left">Enviados</th><th className="px-3 py-2 text-left">Fallidos</th><th className="px-3 py-2 text-left">Acción</th></tr></thead>
                          <tbody>
                            {(campaignsRows || []).map((c) => (
                              <tr key={c.id} className="border-t border-white/10">
                                <td className="px-3 py-2">{c.created_at ? new Date(c.created_at).toLocaleString("es-AR") : "-"}</td>
                                <td className="px-3 py-2">{c.subject}</td>
                                <td className="px-3 py-2">{c.status}</td>
                                <td className="px-3 py-2">{c.recipient_count || 0}</td>
                                <td className="px-3 py-2">{c.sent_count || 0}</td>
                                <td className="px-3 py-2">{c.failed_count || 0}</td>
                                <td className="px-3 py-2"><button onClick={() => openCampaignDetail(c)} className="px-3 py-1 rounded-lg bg-white/10">Detalle</button></td>
                              </tr>
                            ))}
                            {(campaignsRows || []).length === 0 && <tr><td colSpan={7} className="px-3 py-6 text-center text-neutral-500">Sin campañas.</td></tr>}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}

                {marketingSection === "new" && (
                  <div className="space-y-3">
                    <input value={campaignDraft.name} onChange={(e) => setCampaignDraft((p) => ({ ...p, name: e.target.value }))} placeholder="Nombre (opcional)" className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]" />
                    <input value={campaignDraft.subject} onChange={(e) => setCampaignDraft((p) => ({ ...p, subject: e.target.value }))} placeholder="Subject" className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]" />
                    <textarea value={campaignDraft.body_html} onChange={(e) => setCampaignDraft((p) => ({ ...p, body_html: e.target.value }))} placeholder="Body HTML (opcional)" className="w-full min-h-[120px] bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]" />
                    <textarea value={campaignDraft.body_text} onChange={(e) => setCampaignDraft((p) => ({ ...p, body_text: e.target.value }))} placeholder="Body texto (opcional si usás HTML)" className="w-full min-h-[120px] bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]" />
                    <div className="flex items-center gap-2">
                      <button disabled={campaignSaving} onClick={() => saveCampaignDraft(false)} className="px-4 py-2 rounded-xl bg-white/10 border border-white/10 text-[10px] font-black uppercase disabled:opacity-50">Guardar draft</button>
                      <button disabled={campaignSaving} onClick={() => saveCampaignDraft(true)} className="px-4 py-2 rounded-xl bg-indigo-600 text-[10px] font-black uppercase disabled:opacity-50">{campaignSaving ? "Enviando..." : "Guardar y enviar"}</button>
                    </div>
                  </div>
                )}

                {marketingSection === "detail" && (
                  <div>
                    <div className="text-[11px] text-neutral-400 mb-2">Campaña: <b className="text-white">{selectedCampaign?.subject || "-"}</b></div>
                    <div className="text-[11px] text-neutral-400 mb-3">Estado: <b className="text-white">{selectedCampaign?.status || "-"}</b></div>
                    {campaignDeliveriesLoading && <div className="text-[11px] text-white/70">Cargando deliveries...</div>}
                    {!campaignDeliveriesLoading && (
                      <div className="overflow-auto rounded-2xl border border-white/10">
                        <table className="w-full min-w-[760px] text-[11px]">
                          <thead className="bg-white/5"><tr><th className="px-3 py-2 text-left">Email</th><th className="px-3 py-2 text-left">Nombre</th><th className="px-3 py-2 text-left">Estado</th><th className="px-3 py-2 text-left">Error</th><th className="px-3 py-2 text-left">Fecha</th></tr></thead>
                          <tbody>
                            {(campaignDeliveries || []).map((d) => (
                              <tr key={d.id} className="border-t border-white/10">
                                <td className="px-3 py-2">{d.email}</td><td className="px-3 py-2">{d.contact_name || "-"}</td><td className="px-3 py-2">{d.delivery_status}</td><td className="px-3 py-2">{d.error_message || "-"}</td><td className="px-3 py-2">{d.sent_at ? new Date(d.sent_at).toLocaleString("es-AR") : "-"}</td>
                              </tr>
                            ))}
                            {(campaignDeliveries || []).length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-neutral-500">Sin deliveries.</td></tr>}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {soldTicketsModal.open && (
          <ModalErrorBoundary onClose={() => setSoldTicketsModal((s) => ({ ...s, open: false }))}>
          <div className="fixed inset-0 z-[120] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
            <div className={`w-full max-w-5xl p-6 rounded-[2rem] ${UI.card} text-white max-h-[88vh] overflow-y-auto`}>
              <div className="flex items-start justify-between gap-4 mb-6">
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Tickets vendidos</div>
                  <div className="text-2xl font-black uppercase italic">{soldTicketsModal.event?.title || soldTicketsModal.event?.slug || "Evento"}</div>
                  <div className="text-[11px] text-neutral-400 mt-1">
                    Listado con foco en <span className="font-bold text-white/90">nombre</span>, <span className="font-bold text-white/90">DNI</span> y <span className="font-bold text-white/90">contacto</span>.
                  </div>
                </div>
                <button
                  onClick={() => setSoldTicketsModal((s) => ({ ...s, open: false }))}
                  className="p-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10"
                >
                  <X size={16} />
                </button>
              </div>

              <div className="flex items-center justify-between gap-3 mb-4">
                <div className="text-[11px] text-neutral-400">
                  Total: <span className="font-black text-white">{filteredSoldTicketRows.length}</span>
                </div>
                <button
                  onClick={() => downloadSoldTicketsCsv(soldTicketsModal.event, filteredSoldTicketRows)}
                  className="px-4 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest"
                >
                  <Download size={14} /> Descargar listado
                </button>
              </div>

              <div className="mb-4">
                <input
                  value={soldTicketsSearch}
                  onChange={(e) => setSoldTicketsSearch(e.target.value)}
                  placeholder="Filtrar por mail, usuario, DNI, ticket u orden"
                  className="w-full bg-black/40 border border-white/10 rounded-2xl px-4 py-3 text-[11px] text-white outline-none"
                />
              </div>

              {soldTicketsModal.loading && (
                <div className="p-6 rounded-2xl bg-white/5 border border-white/10 flex items-center gap-2 text-[11px] text-neutral-300">
                  <Loader2 size={16} className="animate-spin" /> Cargando tickets...
                </div>
              )}

              {!soldTicketsModal.loading && soldTicketsModal.error && (
                <div className="p-6 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-[11px] text-rose-300 font-bold">
                  {soldTicketsModal.error}
                </div>
              )}

              {!soldTicketsModal.loading && !soldTicketsModal.error && (
                <div className="overflow-x-auto rounded-2xl border border-white/10">
                  <table className="w-full min-w-[760px] text-left text-[11px]">
                    <thead className="bg-white/5">
                      <tr>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Nombre</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">DNI</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Mail</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Celular</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Domicilio</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Provincia</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">CP</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Nacimiento</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Estado</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Fecha/Hora compra</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Ticket ID</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Order ID</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSoldTicketRows.map((t, idx) => {
                        const normalized = normalizeSoldTicketRow(t);
                        return (
                          <tr key={`${t.ticket_id || idx}-${idx}`} className="border-t border-white/10">
                            <td className="px-4 py-3 font-bold">{normalized.fullName}</td>
                            <td className="px-4 py-3">{normalized.dni}</td>
                            <td className="px-4 py-3">{normalized.email}</td>
                            <td className="px-4 py-3">{normalized.phone}</td>
                            <td className="px-4 py-3">{normalized.address}</td>
                            <td className="px-4 py-3">{normalized.province}</td>
                            <td className="px-4 py-3">{normalized.postalCode}</td>
                            <td className="px-4 py-3">{normalized.birthDate}</td>
                            <td className="px-4 py-3">{normalized.status}</td>
                            <td className="px-4 py-3">{normalized.soldAt}</td>
                            <td className="px-4 py-3">{normalized.ticketId}</td>
                            <td className="px-4 py-3">{normalized.orderId}</td>
                          </tr>
                        );
                      })}
                      {filteredSoldTicketRows.length === 0 && (
                        <tr>
                          <td colSpan={12} className="px-4 py-8 text-center text-neutral-400">
                            Sin tickets vendidos todavía.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
          </ModalErrorBoundary>
        )}

                {barOrdersModal.open && (
          <div className="fixed inset-0 z-[120] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
            <div className={`w-full max-w-5xl p-6 rounded-[2rem] ${UI.card} text-white max-h-[88vh] overflow-y-auto`}>
              <div className="flex items-start justify-between gap-4 mb-6">
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Pedidos de barra</div>
                  <div className="text-2xl font-black uppercase italic">{barOrdersModal.event?.title || barOrdersModal.event?.slug || "Evento"}</div>
                </div>
                <button
                  onClick={() => setBarOrdersModal((s) => ({ ...s, open: false }))}
                  className="p-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10"
                >
                  <X size={16} />
                </button>
              </div>

              <div className="text-[11px] text-neutral-400 mb-4">
                Pedidos: <span className="font-black text-white">{filteredBarOrderRows.length}</span> · Total barra: <span className="font-black text-white">${Math.round((Number(barOrdersModal.totalCents || 0) / 100)).toLocaleString()}</span>
              </div>

              <div className="mb-4">
                <input
                  value={barOrdersSearch}
                  onChange={(e) => setBarOrdersSearch(e.target.value)}
                  placeholder="Filtrar por mail, usuario, DNI u orden"
                  className="w-full bg-black/40 border border-white/10 rounded-2xl px-4 py-3 text-[11px] text-white outline-none"
                />
              </div>

              {barOrdersModal.loading && (
                <div className="p-6 rounded-2xl bg-white/5 border border-white/10 flex items-center gap-2 text-[11px] text-neutral-300">
                  <Loader2 size={16} className="animate-spin" /> Cargando pedidos de barra...
                </div>
              )}

              {!barOrdersModal.loading && barOrdersModal.error && (
                <div className="p-6 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-[11px] text-rose-300 font-bold">
                  {barOrdersModal.error}
                </div>
              )}

              {!barOrdersModal.loading && !barOrdersModal.error && (
                <div className="overflow-x-auto rounded-2xl border border-white/10">
                  <table className="w-full min-w-[760px] text-left text-[11px]">
                    <thead className="bg-white/5">
                      <tr>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Nombre</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">DNI</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Mail</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Celular</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Estado</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Fecha/Hora compra</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Total</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Order ID</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredBarOrderRows.map((o, idx) => {
                        const normalized = normalizeBarOrderRow(o);
                        return (
                          <tr key={`${o.order_id || idx}-${idx}`} className="border-t border-white/10">
                            <td className="px-4 py-3 font-bold">{normalized.fullName}</td>
                            <td className="px-4 py-3">{normalized.dni}</td>
                            <td className="px-4 py-3">{normalized.email}</td>
                            <td className="px-4 py-3">{normalized.phone}</td>
                            <td className="px-4 py-3">{normalized.status}</td>
                            <td className="px-4 py-3">{normalized.soldAt}</td>
                            <td className="px-4 py-3">{normalized.total}</td>
                            <td className="px-4 py-3">{normalized.orderId}</td>
                          </tr>
                        );
                      })}
                      {filteredBarOrderRows.length === 0 && (
                        <tr>
                          <td colSpan={8} className="px-4 py-8 text-center text-neutral-400">
                            Sin pedidos de barra todavía.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {sellerSalesModal.open && (
          <div className="fixed inset-0 z-[120] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
            <div className={`w-full max-w-4xl p-6 rounded-[2rem] ${UI.card} text-white max-h-[88vh] overflow-y-auto`}>
              <div className="flex items-start justify-between gap-4 mb-6">
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Ventas por vendedores</div>
                  <div className="text-2xl font-black uppercase italic">{sellerSalesModal.event?.title || sellerSalesModal.event?.slug || "Evento"}</div>
                </div>
                <button
                  onClick={() => setSellerSalesModal((s) => ({ ...s, open: false }))}
                  className="p-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10"
                >
                  <X size={16} />
                </button>
              </div>

              <div className="text-[11px] text-neutral-400 mb-4">
                Vendedores: <span className="font-black text-white">{filteredSellerSalesRows.length}</span> · Entradas vendidas por link: <span className="font-black text-white">{Number(sellerSalesModal.totalTickets || 0).toLocaleString()}</span>
              </div>

              <div className="mb-4">
                <input
                  value={sellerSalesSearch}
                  onChange={(e) => setSellerSalesSearch(e.target.value)}
                  placeholder="Filtrar por vendedor, código o cantidad"
                  className="w-full bg-black/40 border border-white/10 rounded-2xl px-4 py-3 text-[11px] text-white outline-none"
                />
              </div>

              {sellerSalesModal.loading && (
                <div className="p-6 rounded-2xl bg-white/5 border border-white/10 flex items-center gap-2 text-[11px] text-neutral-300">
                  <Loader2 size={16} className="animate-spin" /> Cargando ventas por vendedores...
                </div>
              )}

              {!sellerSalesModal.loading && sellerSalesModal.error && (
                <div className="p-6 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-[11px] text-rose-300 font-bold">
                  {sellerSalesModal.error}
                </div>
              )}

              {!sellerSalesModal.loading && !sellerSalesModal.error && (
                <div className="overflow-x-auto rounded-2xl border border-white/10">
                  <table className="w-full min-w-[640px] text-left text-[11px]">
                    <thead className="bg-white/5">
                      <tr>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Vendedor</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Código</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Entradas vendidas</th>
                        <th className="px-4 py-3 font-black uppercase tracking-widest text-neutral-400">Órdenes pagas</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSellerSalesRows.map((s, idx) => (
                        <tr key={`${s?.seller_code || 'sin-seller'}-${idx}`} className="border-t border-white/10">
                          <td className="px-4 py-3 font-bold">{s?.seller_name || "—"}</td>
                          <td className="px-4 py-3">{s?.seller_code || "sin_seller"}</td>
                          <td className="px-4 py-3">{Number(s?.tickets_sold || 0).toLocaleString()}</td>
                          <td className="px-4 py-3">{Number(s?.orders_paid || 0).toLocaleString()}</td>
                        </tr>
                      ))}
                      {filteredSellerSalesRows.length === 0 && (
                        <tr>
                          <td colSpan={4} className="px-4 py-8 text-center text-neutral-400">
                            Sin ventas atribuidas por link de seller todavía.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {staffLinksModal.open && (
          <div className="fixed inset-0 z-[120] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
            <div className={`w-full max-w-3xl p-6 rounded-[2rem] ${UI.card} text-white max-h-[88vh] overflow-y-auto`}>
              <div className="flex items-start justify-between gap-4 mb-4">
                <div>
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Acceso staff sin login productor</div>
                  <div className="text-2xl font-black uppercase italic">{staffLinksModal.event?.title || staffLinksModal.event?.slug || "Evento"}</div>
                </div>
                <button
                  onClick={() => setStaffLinksModal((s) => ({ ...s, open: false }))}
                  className="p-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10"
                >
                  <X size={16} />
                </button>
              </div>

              <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
                <div className="text-[11px] text-white/75 mb-3">
                  Generá links para compartir por WhatsApp con el staff. Esos links abren directo el módulo correspondiente sin iniciar sesión de productor.
                </div>
                <div className="flex flex-wrap items-center gap-2 mb-3">
                  <label className="text-[11px] text-white/70">Válido por</label>
                  <input
                    type="number"
                    min={1}
                    max={72}
                    value={staffLinksModal.hours_valid}
                    onChange={(e) => setStaffLinksModal((s) => ({ ...s, hours_valid: e.target.value }))}
                    className="w-24 rounded-xl bg-black/40 border border-white/10 px-3 py-2 text-sm"
                  />
                  <span className="text-[11px] text-white/60">horas</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={staffLinksModal.loading}
                    onClick={() => generateStaffLink("validate")}
                    className="px-3 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-[10px] font-black uppercase tracking-widest disabled:opacity-60"
                  >
                    Generar link Validador
                  </button>
                  <button
                    type="button"
                    disabled={staffLinksModal.loading}
                    onClick={() => generateStaffLink("pos")}
                    className="px-3 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-[10px] font-black uppercase tracking-widest disabled:opacity-60"
                  >
                    Generar link POS
                  </button>
                </div>
                {staffLinksModal.error ? (
                  <div className="mt-3 text-[11px] text-rose-300">{staffLinksModal.error}</div>
                ) : null}
              </div>

              <div className="mt-4 grid grid-cols-1 gap-3">
                <div className="rounded-2xl border border-white/10 bg-black/30 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-indigo-200 mb-2">Validador QR</div>
                  <div className="text-[11px] text-white/70 break-all">{staffLinksModal.validateLink || "Generá el link para validar QR."}</div>
                </div>
                <div className="rounded-2xl border border-white/10 bg-black/30 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200 mb-2">POS Taquilla</div>
                  <div className="text-[11px] text-white/70 break-all">{staffLinksModal.posLink || "Generá el link para ventas POS."}</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* VALIDADOR QR */}

        {isStaffValidatorView && (
          <div className="pt-0 pb-20 px-6 max-w-3xl mx-auto animate-in fade-in text-white">
            <button
              onClick={() => {
                stopQrScanner();
                if (staffAccess?.active) {
                  setView("public");
                  window.history.pushState({ ticketpro_view: "public" }, "", "/");
                } else {
                  setView(producerHomeView);
                }
              }}
              className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all mb-6"
            >
              <ChevronLeft size={16} /> {staffAccess?.active ? "Salir" : "Volver a productor"}
            </button>

            <div
              className={`p-8 rounded-[2.5rem] ${UI.card} transition-all duration-300 ${
                validatorResult
                  ? validatorResult.ok
                    ? validatorResult.valid
                      ? "bg-emerald-500/10 border-2 border-emerald-400/60 shadow-[0_0_0_1px_rgba(52,211,153,0.4),0_0_50px_rgba(16,185,129,0.25)]"
                      : "bg-amber-500/10 border-2 border-amber-400/60 shadow-[0_0_0_1px_rgba(251,191,36,0.4),0_0_50px_rgba(251,191,36,0.18)]"
                    : "bg-rose-500/10 border-2 border-rose-400/60 shadow-[0_0_0_1px_rgba(251,113,133,0.4),0_0_50px_rgba(244,63,94,0.18)]"
                  : ""
              }`}
            >
              <div className="text-[10px] font-black uppercase tracking-widest text-neutral-500">Scanner</div>
              <h2 className="text-3xl font-black uppercase italic mt-2">
                Validador <span className="text-indigo-400">QR</span>
              </h2>
              <div className="mt-2 text-[12px] text-white/70">
                Evento: <span className="font-black text-white">{validatorEvent?.title || "—"}</span>
                {validatorEvent?.slug ? <span className="text-white/50"> · {validatorEvent.slug}</span> : null}
              </div>
              {staffAccess?.active && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="text-[10px] px-2 py-1 rounded-lg bg-indigo-500/20 border border-indigo-400/30 text-indigo-100 font-black uppercase tracking-widest">
                    Acceso staff
                  </span>
                  {staffAccess.mode === "validate" ? (
                    <button
                      type="button"
                      onClick={() => setView(staffPosView)}
                      className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest bg-white/10 border border-white/15 hover:bg-white/15"
                    >
                      Ir a POS
                    </button>
                  ) : null}
                </div>
              )}
              <div className="mt-2 text-[12px] text-amber-200/90">
                Los QR son de un solo uso: si ya fue validado, se informará como inválido/reutilizado.
              </div>

              <div className="mt-5 rounded-2xl border border-white/10 bg-black/30 p-4">
                <div className="flex flex-col sm:flex-row gap-3">
                  {!scannerActive ? (
                    <button
                      onClick={startQrScanner}
                      className={`px-4 py-3 rounded-2xl font-black uppercase text-[10px] tracking-widest flex items-center justify-center gap-2 ${UI.button}`}
                    >
                      <QrCode size={16} /> Abrir cámara
                    </button>
                  ) : (
                    <button
                      onClick={stopQrScanner}
                      className="px-4 py-3 rounded-2xl font-black uppercase text-[10px] tracking-widest bg-white/5 hover:bg-white/10 border border-white/10"
                    >
                      Detener cámara
                    </button>
                  )}
                  <div className="text-[11px] text-white/60 flex items-center">
                    {scannerActive ? "Escaneando... apuntá al QR." : "También podés pegar el qr_token manualmente."}
                  </div>
                </div>
                <div className="mt-3 rounded-xl overflow-hidden border border-white/10 bg-black/40">
                  <video
                    ref={scannerVideoRef}
                    autoPlay
                    muted
                    playsInline
                    className="w-full max-h-[320px] object-cover"
                  />
                </div>
                {scannerError ? (
                  <div className="mt-3 text-[11px] text-amber-200">{scannerError}</div>
                ) : null}
              </div>

              <div className="mt-6 space-y-3">
                <input
                  ref={validatorInputRef}
                  value={validatorInput}
                  onChange={(e) => setValidatorInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submitQrValidation();
                  }}
                  placeholder="Pegá o escaneá el qr_token"
                  className="w-full rounded-2xl bg-white/5 border border-white/10 px-4 py-4 text-[13px] font-semibold"
                />
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <button
                    onClick={submitQrValidation}
                    disabled={validatorLoading}
                    className={`w-full py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white transition-all flex items-center justify-center gap-2 ${UI.button} disabled:opacity-50`}
                  >
                    {validatorLoading ? <Loader2 className="animate-spin" size={16} /> : <QrCode size={16} />}
                    Validar QR
                  </button>
                  <button
                    onClick={prepareNextQrScan}
                    className="w-full py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest bg-white/5 hover:bg-white/10 border border-white/10"
                  >
                    Escanear otro QR
                  </button>
                </div>
              </div>

              {validatorResult && (
                <div
                  className={`mt-6 p-5 rounded-2xl border text-[12px] ${
                    validatorResult.ok
                      ? validatorResult.valid
                        ? "bg-emerald-500/20 border-emerald-400/60 text-emerald-100"
                        : "bg-amber-500/20 border-amber-400/60 text-amber-100"
                      : "bg-rose-500/20 border-rose-400/60 text-rose-100"
                  }`}
                >
                  {validatorResult.ok ? (
                    validatorResult.valid ? (
                      <>
                        <div className="text-[11px] font-black uppercase tracking-[0.2em] text-emerald-200/90">Validación exitosa</div>
                        <div className="mt-2 text-2xl sm:text-3xl font-black uppercase leading-tight">✅ Ticket válido</div>
                        <div className="mt-1 text-lg sm:text-xl font-black uppercase leading-tight">Marcado como usado</div>
                        <div className="mt-3 text-white/80">Ticket: {validatorResult.ticket_id || "-"} · Orden: {validatorResult.order_id || "-"}</div>
                      </>
                    ) : (
                      <>
                        <div className="text-[11px] font-black uppercase tracking-[0.2em] text-amber-100/90">Atención</div>
                        <div className="mt-2 text-2xl sm:text-3xl font-black uppercase leading-tight">⚠️ Ticket no válido</div>
                        <div className="mt-3 text-white/80">Motivo: {validatorResult.reason || "estado inválido"}</div>
                      </>
                    )
                  ) : (
                    <>
                      <div className="text-[11px] font-black uppercase tracking-[0.2em] text-rose-100/90">Error de validación</div>
                      <div className="mt-2 text-2xl sm:text-3xl font-black uppercase leading-tight">❌ QR rechazado</div>
                      <div className="mt-3 text-white/80">{validatorResult.detail || "No se pudo validar el QR."}</div>
                    </>
                  )}
                  <div className="mt-4">
                    <button
                      onClick={prepareNextQrScan}
                      className="w-full sm:w-auto px-5 py-3 rounded-xl bg-black/30 hover:bg-black/40 border border-white/20 text-[10px] font-black uppercase tracking-widest"
                    >
                      Siguiente escaneo
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {isStaffPosView && (
          <div className="pt-0 pb-20 px-6 max-w-4xl mx-auto animate-in fade-in text-white">
            <button
              onClick={() => setView(staffValidatorView)}
              className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all mb-6"
            >
              <ChevronLeft size={16} /> Ir al validador
            </button>

            <div className={`p-8 rounded-[2.5rem] ${UI.card}`}>
              <div className="text-[10px] font-black uppercase tracking-widest text-neutral-500">Acceso staff</div>
              <h2 className="text-3xl font-black uppercase italic mt-2">
                POS <span className="text-indigo-400">Taquilla</span>
              </h2>
              <div className="mt-2 text-[12px] text-white/70">
                Evento: <span className="font-black text-white">{staffAccess?.title || staffAccess?.slug || "—"}</span>
                {staffAccess?.slug ? <span className="text-white/50"> · {staffAccess.slug}</span> : null}
              </div>

              {staffPosError ? (
                <div className="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-[12px] text-rose-200">
                  {staffPosError}
                </div>
              ) : null}

              <div className="mt-5 grid grid-cols-1 md:grid-cols-4 gap-2">
                <select
                  className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                  value={staffPosDraft.sale_item_id}
                  onChange={(e) => setStaffPosDraft((prev) => ({ ...prev, sale_item_id: e.target.value }))}
                >
                  <option value="">Seleccioná ticket…</option>
                  {(staffSaleItems || []).map((it) => (
                    <option key={it.id} value={it.id}>
                      {it.name} · ${(Number(it.price_cents || 0) / 100).toLocaleString()}
                    </option>
                  ))}
                </select>
                <input
                  className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                  placeholder="Cantidad"
                  value={staffPosDraft.quantity}
                  onChange={(e) => setStaffPosDraft((prev) => ({ ...prev, quantity: e.target.value }))}
                />
                <select
                  className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                  value={staffPosDraft.payment_method}
                  onChange={(e) => setStaffPosDraft((prev) => ({ ...prev, payment_method: e.target.value }))}
                >
                  <option value="cash">Efectivo</option>
                  <option value="card">Tarjeta</option>
                  <option value="transfer">Transferencia</option>
                  <option value="debit">Débito</option>
                  <option value="credit">Crédito</option>
                  <option value="mp_point">MP Point</option>
                  <option value="other">Otro</option>
                </select>
                <input
                  className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                  placeholder="Seller code (opcional)"
                  value={staffPosDraft.seller_code}
                  onChange={(e) => setStaffPosDraft((prev) => ({ ...prev, seller_code: e.target.value }))}
                />
                <input
                  className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm md:col-span-2"
                  placeholder="Comprador (opcional)"
                  value={staffPosDraft.buyer_name}
                  onChange={(e) => setStaffPosDraft((prev) => ({ ...prev, buyer_name: e.target.value }))}
                />
                <input
                  className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                  placeholder="Email (opcional)"
                  value={staffPosDraft.buyer_email}
                  onChange={(e) => setStaffPosDraft((prev) => ({ ...prev, buyer_email: e.target.value }))}
                />
                <input
                  className="rounded-xl bg-black/20 border border-white/10 px-3 py-2 text-sm"
                  placeholder="Celular (opcional)"
                  value={staffPosDraft.buyer_phone}
                  onChange={(e) => setStaffPosDraft((prev) => ({ ...prev, buyer_phone: e.target.value }))}
                />
                <button
                  className="rounded-xl bg-indigo-500/80 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold disabled:opacity-50"
                  disabled={staffPosBusy || !String(staffPosDraft.sale_item_id || "").trim()}
                  onClick={issueStaffPosSale}
                >
                  {staffPosBusy ? "Registrando..." : "Registrar venta POS"}
                </button>
              </div>

              {staffPosResult && (
                <div className="mt-4 rounded-xl border border-emerald-400/30 bg-emerald-500/10 p-3 text-xs text-emerald-100">
                  {(() => {
                    const staffOrderId = String(staffPosResult.order_id || "").trim();
                    const staffOrderPdfUrl = `/api/tickets/orders/${encodeURIComponent(staffOrderId)}/pdf`;
                    return (
                      <>
                  <div className="font-semibold">Venta registrada</div>
                  <div>Orden: <span className="font-mono">{staffPosResult.order_id || "-"}</span></div>
                  <div>Entradas: {staffPosResult.quantity} · Pago: {staffPosResult.payment_method}</div>
                  <div>Total: ${(Number(staffPosResult.total_cents || 0) / 100).toLocaleString()}</div>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <a
                      href={staffOrderPdfUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded-lg border border-white/20 bg-white/5 px-2 py-1 text-[11px] text-white/85 hover:bg-white/10"
                    >
                      ver PDF
                    </a>
                    <button
                      type="button"
                      className="rounded-lg border border-white/20 bg-white/5 px-2 py-1 text-[11px] text-white/85 hover:bg-white/10"
                      onClick={() => sendOrderPdfByEmail(staffPosResult.order_id, staffPosDraft.buyer_email)}
                    >
                      <span className="inline-flex items-center gap-1"><Mail size={12} /> enviar PDF por mail</span>
                    </button>
                    <button
                      type="button"
                      className="rounded-lg border border-white/20 bg-white/5 px-2 py-1 text-[11px] text-white/85 hover:bg-white/10"
                      onClick={() => {
                        const text = `🎟️ ${brandConfig.shortName}\nOrden: ${staffOrderId}\nPDF: ${window.location.origin}${staffOrderPdfUrl}`;
                        window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener,noreferrer");
                      }}
                    >
                      compartir PDF por whatsapp
                    </button>
                  </div>
                  {!!staffPosResult.tickets?.length && (
                    <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                      {staffPosResult.tickets.map((t, idx) => {
                        const payload = t?.qr_payload || t?.qr_token || t?.ticket_id || "";
                        return (
                          <div key={t?.ticket_id || idx} className="rounded-xl border border-white/10 bg-black/20 p-3 flex items-center gap-3">
                            <img
                              src={qrImgUrl(payload, 150)}
                              alt={`QR staff pos ${idx + 1}`}
                              className="h-20 w-20 rounded-lg border border-white/10 bg-white"
                            />
                            <div className="min-w-0 flex-1">
                              <div className="text-xs text-white/80">{t?.ticket_type || "Entrada"}</div>
                              <div className="text-[11px] text-white/60 truncate">ID: {t?.ticket_id}</div>
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <button
                                  type="button"
                                  className="text-[11px] text-emerald-300 hover:text-emerald-200 underline"
                                  onClick={() => navigator.clipboard?.writeText(String(payload || ""))}
                                >
                                  copiar QR payload
                                </button>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                      </>
                    );
                  })()}
                </div>
              )}
            </div>
          </div>
        )}

        {/* SUCCESS */}


        {/* SOPORTE IA (interno staff) */}
        {view === "supportAI" && (
          <div className="pt-0 pb-20 px-6 max-w-5xl mx-auto animate-in fade-in text-white">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 mb-8">
              <div>
                <h1 className="text-5xl font-black uppercase italic tracking-tight">
                  Panel <span className="text-indigo-600">Administrador</span>
                </h1>
                <p className="text-[11px] text-white/60 mt-2 max-w-2xl leading-relaxed">
                  Panel interno para admins. Incluye Soporte IA + dashboard + operaciones de eventos.
                </p>
              </div>
            </div>

            <div className="p-5 rounded-3xl bg-indigo-500/10 border border-indigo-500/30 mb-6">
              <div className="flex items-center justify-between gap-3 mb-3">
                <div className="text-[9px] font-black uppercase tracking-widest text-indigo-200">NUEVO · Consola Admin</div>
                <div className="text-[10px] text-indigo-100/80">tenant: <b>{tenantId}</b></div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
                <select
                  value={adminEventFilter}
                  onChange={(e)=> {
                    const next = e.target.value;
                    setAdminEventFilter(next);
                    setTransferForm((prev) => ({ ...prev, event_slug: next }));
                  }}
                  onBlur={(e)=> {
                    const next = e.target.value;
                    setAdminEventFilter(next);
                    setTransferForm((prev) => ({ ...prev, event_slug: next }));
                  }}
                  className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]"
                >
                  <option value="">Todos los eventos</option>
                  {adminEvents.map((ev)=> <option key={ev.slug} value={ev.slug}>{ev.slug} · {ev.title}</option>)}
                </select>
                <div className="text-[10px] text-white/70 flex items-center">Filtrá por evento para ver métricas detalladas y separar entradas vs barra.</div>
              </div>
              {adminOpsError && <div className="text-[11px] text-rose-300 mb-2">{adminOpsError}</div>}
              {adminDashboard ? (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px]">
                  <div className="p-3 rounded-2xl bg-black/30 border border-white/10">Eventos activos: <b>{adminDashboard.active_events}</b></div>
                  <div className="p-3 rounded-2xl bg-black/30 border border-white/10">Eventos totales: <b>{adminDashboard.total_events}</b></div>
                  <div className="p-3 rounded-2xl bg-black/30 border border-white/10">Órdenes paid: <b>{adminDashboard.paid_orders}</b></div>
                  <div className="p-3 rounded-2xl bg-black/30 border border-white/10">Ventas totales: <b>${Math.round((Number(adminDashboard.revenue_cents || 0) / 100)).toLocaleString()}</b></div>
                  <div className="p-3 rounded-2xl bg-black/30 border border-white/10">Tickets vendidos: <b>{adminDashboard.total_tickets_sold || 0}</b></div>
                  <div className="p-3 rounded-2xl bg-black/30 border border-white/10">Ventas barra: <b>${Math.round((Number(adminDashboard.bar_revenue_cents || 0) / 100)).toLocaleString()}</b></div>
                  <div className="p-3 rounded-2xl bg-black/30 border border-white/10">Órdenes barra: <b>{adminDashboard.total_bar_orders || 0}</b></div>
                  <div className="p-3 rounded-2xl bg-black/30 border border-white/10">Usuarios compradores: <b>{adminDashboard.unique_buyers || 0}</b></div>
                </div>
              ) : (
                <div className="text-[11px] text-white/60">{adminOpsLoading ? "Cargando dashboard admin..." : "Sin datos de dashboard"}</div>
              )}
              <div className="mt-3 text-[10px] text-white/60">Si no ves métricas, revisá que backend tenga SUPPORT_AI_ENABLED=true y que tu email esté en SUPPORT_AI_STAFF_EMAILS.</div>
              <div className="mt-3 grid grid-cols-1 md:grid-cols-5 gap-2">
                <input
                  value={adminReportSearch}
                  onChange={(e) => setAdminReportSearch(e.target.value)}
                  placeholder="Buscar por título, slug, ciudad o venue"
                  className="md:col-span-2 bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]"
                />
                <select
                  value={adminReportProducerFilter}
                  onChange={(e) => setAdminReportProducerFilter(e.target.value)}
                  className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]"
                >
                  <option value="all">Todos los productores</option>
                  {adminReportProducers.map((producer) => (
                    <option key={producer} value={producer}>{producer}</option>
                  ))}
                </select>
                <select
                  value={adminReportSettlementFilter}
                  onChange={(e) => setAdminReportSettlementFilter(e.target.value)}
                  className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]"
                >
                  <option value="all">Todos los cobros</option>
                  <option value="split">Solo Split MP</option>
                  <option value="manual">Solo Manual</option>
                </select>
                <select
                  value={adminReportStatusFilter}
                  onChange={(e) => setAdminReportStatusFilter(e.target.value)}
                  className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]"
                >
                  <option value="all">Todos los estados</option>
                  <option value="active">Solo Activos</option>
                  <option value="paused">Solo Pausados</option>
                  <option value="soldout">Solo Sold Out</option>
                </select>
              </div>
              <div className="mt-2 grid grid-cols-1 md:grid-cols-3 gap-2">
                <select
                  value={adminReportSortBy}
                  onChange={(e) => setAdminReportSortBy(e.target.value)}
                  className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]"
                >
                  <option value="title_asc">Orden: Nombre (A-Z)</option>
                  <option value="title_desc">Orden: Nombre (Z-A)</option>
                  <option value="tickets_desc">Orden: Tickets (mayor a menor)</option>
                  <option value="tickets_asc">Orden: Tickets (menor a mayor)</option>
                  <option value="ticket_revenue_desc">Orden: Entradas $ (mayor a menor)</option>
                  <option value="bar_revenue_desc">Orden: Barra $ (mayor a menor)</option>
                  <option value="service_desc">Orden: Service % (mayor a menor)</option>
                  <option value="service_asc">Orden: Service % (menor a mayor)</option>
                </select>
                <div className="md:col-span-2 text-[10px] text-white/60 flex items-center">
                  Mostrando <b className="mx-1">{filteredAndSortedAdminReportEvents.length}</b> de <b className="mx-1">{(adminDashboard?.events || []).length}</b> eventos.
                </div>
              </div>
              <div className="mt-3 max-h-52 overflow-auto rounded-2xl border border-white/10">
                <table className="w-full text-[11px]">
                  <thead className="bg-black/40 text-white/60">
                    <tr>
                      <th className="text-left px-3 py-2">Evento</th>
                      <th className="text-left px-3 py-2">Productor</th>
                      <th className="text-right px-3 py-2">Tickets</th>
                      <th className="text-right px-3 py-2">Entradas $</th>
                      <th className="text-right px-3 py-2">Barra $</th>
                      <th className="text-left px-3 py-2">Split / Cobro</th>
                      <th className="text-right px-3 py-2">Service %</th>
                      <th className="text-left px-3 py-2">Estado</th>
                      <th className="text-right px-3 py-2">Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredAndSortedAdminReportEvents.slice(0, 200).map((ev) => (
                      <tr key={ev.slug} className="border-t border-white/10">
                        <td className="px-3 py-2">
                          <button
                            type="button"
                            onClick={() => openPublicEvent(ev.slug)}
                            className="underline decoration-indigo-400/60 hover:decoration-indigo-300 hover:text-indigo-200 transition-colors text-left"
                            title="Abrir evento"
                          >
                            {ev.title || ev.slug}
                          </button>
                        </td>
                        <td className="px-3 py-2 text-[10px] text-white/75">
                          {(() => {
                            const eventMeta = adminEventsBySlug.get(String(ev.slug || "")) || {};
                            return String(eventMeta.producer || eventMeta.tenant || "-");
                          })()}
                        </td>
                        <td className="px-3 py-2 text-right">{ev.tickets_sold || 0}</td>
                        <td className="px-3 py-2 text-right">${Math.round((Number(ev.ticket_revenue_cents || 0) / 100)).toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">${Math.round((Number(ev.bar_revenue_cents || 0) / 100)).toLocaleString()}</td>
                        <td className="px-3 py-2 text-[10px] text-white/80">
                          {(() => {
                            const eventMeta = adminEventsBySlug.get(String(ev.slug || "")) || {};
                            const isSplit = String(eventMeta.settlement_mode || "manual_transfer") === "mp_split";
                            const collector = String(eventMeta.mp_collector_id || "").trim();
                            const alias = String(eventMeta.payout_alias || "").trim();
                            if (isSplit) {
                              return (
                                <div>
                                  <div className="text-indigo-200 font-semibold">Split MP</div>
                                  <div className="text-white/60">Collector: {collector || "(faltante)"}</div>
                                </div>
                              );
                            }
                            return (
                              <div>
                                <div className="text-amber-200 font-semibold">Manual</div>
                                <div className="text-white/60">Alias: {alias || "-"}</div>
                              </div>
                            );
                          })()}
                        </td>
                        <td className="px-3 py-2 text-right">
                          {(() => {
                            const eventMeta = adminEventsBySlug.get(String(ev.slug || "")) || {};
                            const pct = Number(eventMeta.service_charge_pct ?? 0.15);
                            const pctLabel = Number.isFinite(pct) ? (pct * 100).toFixed(2) : "15.00";
                            return (
                              <div className="flex items-center justify-end gap-2">
                                <span>{pctLabel}%</span>
                                <button
                                  type="button"
                                  onClick={() => updateEventServiceChargeAsAdmin(ev.slug, pct)}
                                  disabled={adminEventActionLoading}
                                  className="px-2 py-1 rounded-lg border border-indigo-400/40 bg-indigo-500/20 hover:bg-indigo-500/30 text-[9px] font-black uppercase tracking-widest disabled:opacity-50"
                                >
                                  Editar
                                </button>
                              </div>
                            );
                          })()}
                        </td>
                        <td className="px-3 py-2">
                          {(() => {
                            const eventMeta = adminEventsBySlug.get(String(ev.slug || "")) || {};
                            const paused = eventMeta.active === false;
                            const soldOut = !!ev.sold_out;
                            if (!paused && !soldOut) return <span className="text-emerald-300">Activo</span>;
                            return (
                              <div className="flex gap-1 flex-wrap">
                                {paused && <span className="px-2 py-0.5 rounded-full bg-amber-500/25 border border-amber-400/60 text-amber-100">PAUSADO</span>}
                                {soldOut && <span className="px-2 py-0.5 rounded-full bg-rose-500/20 border border-rose-500/40 text-rose-200">SOLD OUT</span>}
                              </div>
                            );
                          })()}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => openAdminEventManager(ev.slug, "tickets")}
                              className="px-2 py-1 rounded-lg border border-indigo-400/40 bg-indigo-500/20 hover:bg-indigo-500/30 text-[9px] font-black uppercase tracking-widest"
                            >
                              Tickets
                            </button>
                            <button
                              type="button"
                              onClick={() => openAdminEventManager(ev.slug, "sellers")}
                              className="px-2 py-1 rounded-lg border border-white/20 bg-white/10 hover:bg-white/15 text-[9px] font-black uppercase tracking-widest"
                            >
                              Sellers
                            </button>
                            <button
                              type="button"
                              onClick={() => deleteEventAsAdmin(ev.slug)}
                              disabled={adminEventActionLoading}
                              className="px-2 py-1 rounded-lg border border-rose-500/40 bg-rose-500/20 hover:bg-rose-500/30 text-[9px] font-black uppercase tracking-widest disabled:opacity-50"
                            >
                              Eliminar
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="mb-6 p-6 md:p-7 rounded-3xl border border-indigo-400/40 bg-gradient-to-br from-indigo-500/20 via-indigo-500/10 to-black/30 shadow-[0_12px_40px_rgba(99,102,241,0.2)]">
              <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-[0.2em] text-indigo-200/90">Centro de control soporte IA</div>
                  <p className="mt-3 text-[12px] md:text-[13px] text-indigo-50/95 max-w-3xl leading-relaxed">
                    Desde acá podés: consultar al Soporte IA, crear eventos de prueba o para productores, y transferir ownership.
                  </p>
                </div>
                <button
                  onClick={() => {
                    loadSupportAIStatus();
                    loadAdminSupportData();
                  }}
                  className="px-4 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-widest bg-white/10 hover:bg-white/15 border border-white/20 shrink-0"
                >
                  Revalidar
                </button>
              </div>

              <div className="mt-5 p-4 rounded-2xl bg-black/35 border border-white/15 text-[12px] text-white/85">
                {supportAiStatus?.error ? (
                  <span className="text-rose-300">{supportAiStatus.error}</span>
                ) : supportAiStatus ? (
                  <div className="flex flex-wrap gap-x-4 gap-y-2">
                    <span>enabled: <b>{String(!!supportAiStatus.enabled)}</b></span>
                    <span>staff: <b>{String(!!supportAiStatus.is_staff)}</b></span>
                    <span>model: <b>{supportAiStatus.model || "-"}</b></span>
                    <span>openai_key: <b>{String(!!supportAiStatus.has_openai_key)}</b></span>
                    <span>vector_store: <b>{String(!!supportAiStatus.has_vector_store)}</b></span>
                  </div>
                ) : (
                  <span className="text-white/60">Cargando estado...</span>
                )}
              </div>
            </div>

            <div className="p-5 rounded-3xl bg-white/5 border border-white/10 mb-6">
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-3">Crear evento (mismo modal que Productor)</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
                <input value={adminOwnerEmailForEditor} onChange={(e)=>setAdminOwnerEmailForEditor(e.target.value)} placeholder="Email del productor (puede no tener cuenta aún)" className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]" />
                <div className="text-[10px] text-white/70 flex items-center">Abrí el creador completo y al guardar se asigna al email indicado.</div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button onClick={openAdminEventCreator} disabled={adminOpsLoading} className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50">Abrir creador completo</button>
                <button onClick={createEventAsAdmin} disabled={adminOpsLoading} className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest bg-white/10 hover:bg-white/20 border border-white/10 disabled:opacity-50">Creación rápida</button>
              </div>
            </div>

            <div className="p-5 rounded-3xl bg-white/5 border border-white/10 mb-6">
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-3">Transferir evento a otro usuario (admin)</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
                <select value={transferForm.event_slug} onChange={(e)=>setTransferForm(v=>({...v,event_slug:e.target.value}))} className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]">
                  <option value="">Seleccionar evento</option>
                  {adminEvents.map((ev)=> <option key={ev.slug} value={ev.slug}>{ev.slug} · {ev.title}</option>)}
                </select>
                <input value={transferForm.new_owner_tenant} onChange={(e)=>setTransferForm(v=>({...v,new_owner_tenant:e.target.value}))} placeholder="Nuevo dueño (tenant/email)" className="bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]" />
              </div>
              <button onClick={transferEventAsAdmin} disabled={adminOpsLoading} className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50">Transferir evento</button>
            </div>

            <div className="p-5 rounded-3xl bg-rose-950/30 border border-rose-500/40 mb-6">
              <div className="text-[10px] font-black uppercase tracking-widest text-rose-300 mb-2">Eliminar evento (solo admin)</div>
              <div className="text-[10px] text-rose-100/80 mb-3">
                Si el evento tiene órdenes asociadas, te pedirá confirmación adicional para forzar.
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2 items-center">
                <select value={transferForm.event_slug} onChange={(e)=>setTransferForm(v=>({...v,event_slug:e.target.value}))} className="md:col-span-2 bg-black/40 border border-rose-400/30 rounded-xl px-3 py-2 text-[11px]">
                  <option value="">Seleccionar evento a eliminar</option>
                  {adminEvents.map((ev)=> <option key={ev.slug} value={ev.slug}>{ev.slug} · {ev.title}</option>)}
                </select>
                <button
                  onClick={() => deleteEventAsAdmin(transferForm.event_slug)}
                  disabled={!transferForm.event_slug || adminEventActionLoading}
                  className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest bg-rose-700 hover:bg-rose-600 disabled:opacity-50"
                >
                  Eliminar ahora
                </button>
              </div>
            </div>

            <div className="p-5 rounded-3xl bg-white/5 border border-white/10 mb-6">
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-3">Acciones de eventos (pausar y eliminar)</div>
              <div className="text-[10px] text-white/60 mb-3">Estas acciones piden confirmación y afectan al evento seleccionado.</div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mb-3">
                <select value={transferForm.event_slug} onChange={(e)=>setTransferForm(v=>({...v,event_slug:e.target.value}))} className="md:col-span-2 bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]">
                  <option value="">Seleccionar evento</option>
                  {adminEvents.map((ev)=> <option key={ev.slug} value={ev.slug}>{ev.slug} · {ev.title}</option>)}
                </select>
                <button onClick={() => transferForm.event_slug && openPublicEvent(transferForm.event_slug)} className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest bg-white/10 hover:bg-white/20 border border-white/10">Ver evento</button>
                <button onClick={() => transferForm.event_slug && openAdminBarSalesDetail(transferForm.event_slug)} className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest bg-indigo-700/70 hover:bg-indigo-600 border border-indigo-400/30">Detalle barra</button>
                <button
                  onClick={() => {
                    if (!transferForm.event_slug) return;
                    const selectedEv = adminEvents.find((ev) => ev.slug === transferForm.event_slug) || { slug: transferForm.event_slug, title: transferForm.event_slug };
                    openSoldTicketsModal(selectedEv, { adminMode: true });
                  }}
                  className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest bg-white/10 hover:bg-white/20 border border-white/10"
                >
                  Entradas vendidas
                </button>
                <button
                  onClick={() => openAdminEventManager(transferForm.event_slug, "tickets")}
                  disabled={!transferForm.event_slug}
                  className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest bg-indigo-600 hover:bg-indigo-500 border border-indigo-400/30 disabled:opacity-50"
                >
                  Gestionar tickets/sellers
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                <button onClick={() => toggleEventPauseAsAdmin(transferForm.event_slug, false)} disabled={!transferForm.event_slug || adminEventActionLoading} className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest bg-amber-600 hover:bg-amber-500 disabled:opacity-50">Pausar</button>
                <button onClick={() => toggleEventPauseAsAdmin(transferForm.event_slug, true)} disabled={!transferForm.event_slug || adminEventActionLoading} className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50">Reactivar</button>
                <button onClick={() => deleteEventAsAdmin(transferForm.event_slug)} disabled={!transferForm.event_slug || adminEventActionLoading} className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest bg-rose-700 hover:bg-rose-600 disabled:opacity-50">Eliminar</button>
              </div>
              <div className="mt-3 text-[10px] text-rose-200/80">
                Eliminar es una acción solo admin. Si el evento tiene órdenes PAID, vas a poder forzar la limpieza escribiendo <b>FORZAR</b>.
              </div>
            </div>

            <div className="p-5 rounded-3xl bg-white/5 border border-white/10 mb-6">
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-3">Soporte IA (consultas rápidas)</div>
              <div className="flex flex-wrap gap-2">
                {supportAiQuickPrompts.map((p) => (
                  <button
                    key={p}
                    onClick={() => askSupportAI(p)}
                    disabled={supportAiLoading}
                    className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 border border-white/10 disabled:opacity-50"
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>

            <div className="p-5 rounded-3xl bg-white/5 border border-white/10 mb-6">
              <div className="flex items-center gap-2">
                <input
                  value={supportAiInput}
                  onChange={(e) => setSupportAiInput(e.target.value)}
                  placeholder="Escribí tu consulta (ej: ¿cuántas entradas vendimos hoy para evento-x?)"
                  className="w-full bg-black/40 border border-white/10 rounded-2xl px-4 py-3 text-[11px] text-white outline-none"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") askSupportAI(supportAiInput);
                  }}
                />
                <button
                  onClick={() => askSupportAI(supportAiInput)}
                  disabled={supportAiLoading || !supportAiInput.trim()}
                  className="px-4 py-3 rounded-2xl text-[10px] font-black uppercase tracking-widest bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
                >
                  {supportAiLoading ? "Consultando..." : "Consultar"}
                </button>
              </div>
              {supportAiError && (
                <div className="mt-3 text-[11px] text-rose-300">{supportAiError}</div>
              )}
            </div>

            <div className="space-y-3">
              {supportAiHistory.length === 0 && (
                <div className="p-5 rounded-3xl bg-white/5 border border-white/10 text-[11px] text-white/60">
                  Aún no hay consultas en esta sesión.
                </div>
              )}
              {supportAiHistory.map((m, idx) => (
                <div
                  key={`${m.role}-${idx}`}
                  className={`p-4 rounded-2xl border ${m.role === "assistant" ? "bg-indigo-500/10 border-indigo-500/30" : "bg-white/5 border-white/10"}`}
                >
                  <div className="text-[9px] font-black uppercase tracking-widest text-neutral-400 mb-2">
                    {m.role === "assistant" ? "Soporte IA" : "Staff"}
                  </div>
                  <div className="text-[12px] whitespace-pre-wrap">{m.text}</div>
                  {m.role === "assistant" && (
                    <div className="mt-2 text-[10px] text-white/60">
                      trace: {m.traceId || "-"} · tools: {(m.usedTools || []).join(", ") || "sin tools"}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* MIS TICKETS (cliente) */}
        {view === "myTickets" && (
          <MyTicketsView
            myAssetsLoading={myAssetsLoading}
            myAssetsError={myAssetsError}
            myAssets={myAssets}
            myFilters={myFilters}
            setMyFilters={setMyFilters}
            loadMyAssets={loadMyAssets}
            normalizeAssetUrl={normalizeAssetUrl}
            qrImgUrl={qrImgUrl}
            transferOrder={transferOrder}
            requestCancel={requestCancel}
          />
        )}

        {view === "success" && purchaseData && (
          <PurchaseSuccessView
            purchaseData={purchaseData}
            UI={UI}
            successProcessing={successProcessing}
            successTries={successTries}
            me={me}
            selectedEvent={selectedEvent}
            onOpenMyTickets={openMyTicketsFromSuccess}
            onBackToPublic={() => {
              setView("public");
              setSelectedEvent(null);
            }}
          />
        )}
      </main>

      <AppFooter
        me={me}
        openLoginModal={openLoginModal}
        setView={setView}
        loadProducerEvents={loadProducerEvents}
        brand={brandConfig}
        legal={legalConfig}
        features={featureFlags}
      />

      {isEditing && (
        <EditorModal
          editFormData={editFormData}
          setEditFormData={setEditFormData}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          setIsEditing={setIsEditing}
          saveEvent={saveEvent}
          onFlyerPicked={(file) => { flyerPendingRef.current = file; }}
          currentView={view}
          onOpenStaffAccess={openStaffLinksModal}
          legalConfig={legalConfig}
        />
      )}

      {adminBarSalesModal.open && (
        <div className="fixed inset-0 z-[130] bg-black/75 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setAdminBarSalesModal((s)=>({ ...s, open:false }))}>
          <div className="w-full max-w-3xl rounded-3xl bg-[#14141a] border border-white/10 p-5" onClick={(e)=>e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <div className="text-[11px] font-black uppercase tracking-widest text-neutral-400">Detalle venta barra · {adminBarSalesModal.eventSlug}</div>
              <button className="px-3 py-2 rounded-xl bg-white/10 border border-white/10 text-[10px] font-black uppercase" onClick={() => setAdminBarSalesModal((s)=>({ ...s, open:false }))}>Cerrar</button>
            </div>
            <div className="text-[12px] font-bold mb-3">Total barra: ${Math.round((Number(adminBarSalesModal.totalCents || 0) / 100)).toLocaleString()} · Pedidos: {filteredAdminBarSalesRows.length}</div>
            <input
              value={adminBarSalesSearch}
              onChange={(e)=>setAdminBarSalesSearch(e.target.value)}
              placeholder="Filtrar por email u order id"
              className="w-full mb-3 bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-[11px]"
            />
            {adminBarSalesModal.loading && <div className="text-[11px] text-white/70">Cargando...</div>}
            {!!adminBarSalesModal.error && <div className="text-[11px] text-rose-300">{adminBarSalesModal.error}</div>}
            {!adminBarSalesModal.loading && !adminBarSalesModal.error && (
              <div className="max-h-[50vh] overflow-auto rounded-2xl border border-white/10">
                <table className="w-full text-[11px]">
                  <thead className="bg-black/40 text-white/60">
                    <tr><th className="px-3 py-2 text-left">Fecha</th><th className="px-3 py-2 text-left">Order</th><th className="px-3 py-2 text-left">Email</th><th className="px-3 py-2 text-right">Monto</th></tr>
                  </thead>
                  <tbody>
                    {filteredAdminBarSalesRows.map((o) => (
                      <tr key={o.id} className="border-t border-white/10">
                        <td className="px-3 py-2">{String(o.created_at || '').replace('T',' ').slice(0,19)}</td>
                        <td className="px-3 py-2">{o.id}</td>
                        <td className="px-3 py-2">{o.buyer_email || '-'}</td>
                        <td className="px-3 py-2 text-right">${Math.round((Number(o.total_cents || 0)/100)).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

<GoogleLoginModal
        open={loginRequired}
        onClose={closeLoginModal}
        googleClientId={googleClientId}
        featureFlags={featureFlags}
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

          if (method) setTimeout(() => handleCheckout(method, u), 0);
        }}
      />

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
        html, body { width: 100%; overflow-x: hidden; }
        body { font-family: 'Inter', sans-serif; }
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
