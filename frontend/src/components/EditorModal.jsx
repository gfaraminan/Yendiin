import React, { useEffect, useMemo, useRef, useState } from "react";
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
  ShieldCheck,
  Image as ImageIcon,
  PlusCircle,
  Minus,
  Trash2,
  Check,
  X,
  Save,
  RefreshCw,
} from "lucide-react";
import { FALLBACK_FLYER, UI } from "../app/constants";
import { normalizeAssetUrl, slugify } from "../app/helpers";

export default function EditorModal({
  editFormData,
  setEditFormData,
  activeTab,
  setActiveTab,
  setIsEditing,
  saveEvent,
  onFlyerPicked,
}) {
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

  
  const [flyerFilePending, setFlyerFilePending] = useState(null);
  const [showTermsModal, setShowTermsModal] = useState(false);
  const [mpOauthBusy, setMpOauthBusy] = useState(false);
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
      `/api/producer/events/${encodeURIComponent(slug)}/flyer?tenant_id=${encodeURIComponent("default")}`,
      { method: "POST", body: fd, credentials: "include" }
    );
    const data = await readJsonOrText(r);
    if (!r.ok) throw new Error((data && data.detail) || "No se pudo subir el flyer");
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

  const connectMpOauth = async () => {
    try {
      setMpOauthBusy(true);
      const r = await fetch(`/api/payments/mp/oauth/start?tenant=${encodeURIComponent(tenantId)}`, {
        credentials: "include",
      });
      const data = await readJsonOrText(r);
      if (!r.ok) throw new Error((data && data.detail) || "No se pudo iniciar OAuth de Mercado Pago");

      const authUrl = String(data?.auth_url || "").trim();
      if (!authUrl) throw new Error("No se recibió auth_url de Mercado Pago");

      const popup = window.open(authUrl, "mp_oauth", "width=560,height=760");
      if (!popup) throw new Error("No se pudo abrir la ventana de autorización (popup bloqueado)");

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
                    className={`mt-2 w-full px-4 py-3 rounded-2xl resize-y ${UI.input}`}
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
                    className={`mt-2 w-full px-4 py-3 rounded-2xl resize-y ${UI.input}`}
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
                    className={`mt-2 w-full px-4 py-3 rounded-2xl resize-y ${UI.input}`}
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
                    className={`mt-2 w-full px-4 py-3 rounded-2xl resize-y ${UI.input}`}
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
                    className={`mt-2 w-full px-4 py-3 rounded-2xl resize-y ${UI.input}`}
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
                      className={`mt-2 w-full px-4 py-3 rounded-2xl resize-y ${UI.input}`}
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
                    CUIT
                  </label>
                  <input
                    value={editFormData.cuit || ""}
                    onChange={(e) =>
                      setEditFormData((s) => ({ ...s, cuit: e.target.value }))
                    }
                    className={`mt-2 w-full px-4 py-3 rounded-2xl resize-y ${UI.input}`}
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

        <label className="md:col-span-2 text-sm">
      <div className="text-white/60 mb-1">Detalle / descripción del evento</div>
      <textarea
        value={editFormData.description || ""}
        onChange={(e) => setEditFormData((p) => ({ ...p, description: e.target.value }))}
        rows={6}
        placeholder="Información del evento, artistas, horarios, condiciones, edad mínima, accesos, etc."
        className="w-full px-4 py-3 rounded-2xl bg-white/5 border border-white/10 outline-none focus:ring-2 focus:ring-white/20 resize-y"
      />
    </label>
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
                    <div><span className="text-white/40">Cobro:</span> {editFormData.payout_alias || "-"} · {editFormData.cuit || "-"} · {editFormData.settlement_mode === "mp_split" ? "Split MP" : "Manual"}</div>
                    <div><span className="text-white/40">Ubicación:</span> {editFormData.city} · {editFormData.venue}</div>
                    <div><span className="text-white/40">Tickets:</span> {eventItems?.length || 0}</div>
                    <div><span className="text-white/40">Vendedores:</span> {sellers?.length || 0}</div>
                  </div>
                </div>

                <div className="rounded-3xl border border-white/10 bg-white/5 p-5">
                  <label className="text-[11px] font-black uppercase tracking-widest text-white/60">
                    Descripción
                  </label>
                  <textarea
                    value={editFormData.description || ""}
                    onChange={(e) =>
                      setEditFormData((s) => ({ ...s, description: e.target.value }))
                    }
                    className={`mt-2 w-full px-4 py-3 rounded-2xl resize-y ${UI.input}`}
                    rows={ 8}
                    placeholder="Contá todo lo que quieras: artistas, horarios, condiciones, +18, etc."
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
                      rows={6}
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2 resize-y"
                      value={editFormData.description || ""}
                      onChange={(e) => setEditFormData({ ...editFormData, description: e.target.value })}
                      placeholder="Contá todo lo que quieras del evento..."
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

      {showTermsModal && (
        <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center px-4">
          <div className="bg-gray-900 rounded-xl max-w-lg w-full max-h-[80vh] flex flex-col">
            <div className="p-4 border-b border-gray-700 text-lg font-semibold">Términos y Condiciones</div>
            <div className="p-4 overflow-y-auto text-sm text-gray-300 space-y-3">
              <p>Próximamente se mostrará aquí el texto completo de términos y condiciones.</p>
              <p>Este modal queda listo para pegar el texto legal definitivo.</p>
            </div>
            <div className="p-4 border-t border-gray-700 flex justify-end">
              <button onClick={() => setShowTermsModal(false)} className="bg-violet-600 px-4 py-2 rounded-lg text-white">Cerrar</button>
            </div>
          </div>
        </div>
      )}

  );
}
