import React, { useEffect, useState } from "react";
import {
  Loader2,
  MapPin,
  Ticket,
  Search,
  ChevronLeft,
  Sparkles,
  Volume2,
  Image as ImageIcon,
  MessageSquare,
  CreditCard,
  CheckCircle2,
  User,
  Mail,
  Fingerprint,
  Phone,
  Tag,
  Share2,
  Clock,
} from "lucide-react";

import { initializeApp } from "firebase/app";
import {
  getAuth,
  signInWithPopup,
  GoogleAuthProvider,
  onAuthStateChanged,
  signOut,
} from "firebase/auth";
import { useNavigate } from "react-router-dom";
const nav = useNavigate();
<button onClick={() => nav("/producer")}>Modo Productor</button>


// ------------------------------------------------------------
// CONFIG
// ------------------------------------------------------------

// Si no vas a usar Gemini/TTS/Imagen: dejalo vacío y listo.
const apiKey = "";

// Render / entornos que inyectan config (opcional)
const firebaseConfig =
  typeof __firebase_config !== "undefined"
    ? JSON.parse(__firebase_config)
    : {
        apiKey: "AIza...",
        authDomain: "tu-app.firebaseapp.com",
        projectId: "tu-app",
      };

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

// ------------------------------------------------------------
// Fallbacks / Normalización (evita bugs tipo GET /flyer_url)
// ------------------------------------------------------------
const FALLBACK_FLYER =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(`
    <svg xmlns='http://www.w3.org/2000/svg' width='1200' height='800'>
      <defs>
        <linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>
          <stop offset='0' stop-color='#0f1326'/>
          <stop offset='0.48' stop-color='#1d3b6b'/>
          <stop offset='1' stop-color='#0f766e'/>
        </linearGradient>
        <radialGradient id='accent' cx='0.2' cy='0.2' r='0.9'>
          <stop offset='0' stop-color='rgba(251,191,36,0.35)'/>
          <stop offset='1' stop-color='rgba(251,191,36,0)'/>
        </radialGradient>
      </defs>
      <rect width='1200' height='800' fill='url(#g)'/>
      <rect width='1200' height='800' fill='url(#accent)'/>
      <circle cx='980' cy='220' r='170' fill='rgba(255,255,255,0.10)'/>
      <circle cx='810' cy='510' r='240' fill='rgba(255,255,255,0.06)'/>
      <circle cx='280' cy='660' r='220' fill='rgba(34,211,238,0.13)'/>
      <text x='80' y='160' fill='rgba(255,255,255,0.84)' font-size='54' font-family='Inter,Arial' font-weight='900'>YENDIIN</text>
      <text x='80' y='225' fill='rgba(255,255,255,0.94)' font-size='86' font-family='Inter,Arial' font-weight='900'>Yendiin</text>
      <text x='80' y='315' fill='rgba(255,255,255,0.68)' font-size='22' font-family='Inter,Arial' font-weight='700'>EVENTO · IMAGEN NO DISPONIBLE</text>
    </svg>
  `);

const safeStr = (v) => (typeof v === "string" ? v.trim() : "");

const normalizeEvent = (e) => {
  const flyer =
    safeStr(e.flyer_url) ||
    safeStr(e.image_url) ||
    safeStr(e.banner_url) ||
    safeStr(e.flyer) ||
    safeStr(e.hero_bg);

  return {
    slug: safeStr(e.slug) || safeStr(e.event_slug) || safeStr(e.id) || "",
    title:
      safeStr(e.title) || safeStr(e.name) || safeStr(e.event_title) || "Evento",
    category: safeStr(e.category) || safeStr(e.category_name) || "Todos",
    date_text:
      safeStr(e.date_text) ||
      safeStr(e.date) ||
      safeStr(e.start_date) ||
      "PRÓXIMAMENTE",
    city:
      safeStr(e.city) ||
      safeStr(e.location_city) ||
      safeStr(e.venue_city) ||
      safeStr(e.location) ||
      "",
    venue: safeStr(e.venue) || safeStr(e.location_name) || "",
    description: safeStr(e.description) || safeStr(e.details) || "",
    flyer_url: flyer || "",
    // tickets puede venir en detalle
    tickets: Array.isArray(e?.tickets) ? e.tickets : [],
  };
};

const normalizeCategories = (rawCats) => {
  const cats = Array.isArray(rawCats) ? rawCats : [];
  const cleaned = cats.map(safeStr).filter(Boolean);
  return Array.from(new Set(["Todos", ...cleaned]));
};

const resolveFlyerSrc = (flyer_url) => {
  const f = safeStr(flyer_url);

  // Evita el bug “src='flyer_url'” -> GET /flyer_url (404)
  if (!f) return FALLBACK_FLYER;
  if (f === "flyer_url" || f === "/flyer_url") return FALLBACK_FLYER;

  return f;
};

// ------------------------------------------------------------
// Demo event (para que SIEMPRE haya 1 card aunque la API falle)
// ------------------------------------------------------------
const MOCK_EVENT = {
  slug: "demo-show-2025",
  title: "INDIE NIGHT MENDOZA 2025",
  category: "MÚSICA",
  date_text: "Sábado 12 de Julio, 21:00hs",
  venue: "N8 Club",
  city: "Mendoza",
  description:
    "Una noche única con bandas emergentes, visuales de vanguardia y una propuesta gastronómica exclusiva.",
  flyer_url:
    "https://images.unsplash.com/photo-1470225620780-dba8ba36b745?w=1200",
  tickets: [
    {
      id: 1,
      name: "Preventa General",
      price_cents: 150000,
      stock_total: 300,
      stock_sold: 150,
    },
    {
      id: 2,
      name: "Experiencia VIP Indigo",
      price_cents: 350000,
      stock_total: 50,
      stock_sold: 12,
    },
  ],
};

// ------------------------------------------------------------
// Gemini (opcional)
// ------------------------------------------------------------
const fetchGemini = async (prompt, systemInstruction = "") => {
  if (!apiKey) return "IA desactivada (no hay apiKey configurada).";

  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key=${apiKey}`;
  const payload = {
    contents: [{ parts: [{ text: prompt }] }],
    systemInstruction: systemInstruction
      ? { parts: [{ text: systemInstruction }] }
      : undefined,
  };

  for (let i = 0; i < 5; i++) {
    try {
      const res = await fetch(url, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        const result = await res.json();
        return result.candidates?.[0]?.content?.parts?.[0]?.text;
      }
    } catch (e) {}
    await new Promise((r) => setTimeout(r, Math.pow(2, i) * 1000));
  }
  return "Lo siento, la IA no está disponible en este momento.";
};

const generateImage = async (promptText) => {
  if (!apiKey) return null;

  const url = `https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key=${apiKey}`;
  const payload = {
    instances: { prompt: promptText },
    parameters: { sampleCount: 1 },
  };

  for (let i = 0; i < 5; i++) {
    try {
      const res = await fetch(url, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        const result = await res.json();
        return `data:image/png;base64,${result.predictions?.[0]?.bytesBase64Encoded}`;
      }
    } catch (e) {}
    await new Promise((r) => setTimeout(r, Math.pow(2, i) * 1000));
  }
  return null;
};

const fetchTTS = async (text) => {
  if (!apiKey) return null;

  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key=${apiKey}`;
  const payload = {
    contents: [{ parts: [{ text: `Di con entusiasmo: ${text}` }] }],
    generationConfig: {
      responseModalities: ["AUDIO"],
      speechConfig: {
        voiceConfig: { prebuiltVoiceConfig: { voiceName: "Aoede" } },
      },
    },
    model: "gemini-2.5-flash-preview-tts",
  };

  for (let i = 0; i < 5; i++) {
    try {
      const res = await fetch(url, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        const result = await res.json();
        return (
          result.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data || null
        );
      }
    } catch (e) {}
    await new Promise((r) => setTimeout(r, Math.pow(2, i) * 1000));
  }
  return null;
};

const playAudioFromPCM = (base64Data) => {
  const binaryString = window.atob(base64Data);
  const len = binaryString.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = binaryString.charCodeAt(i);

  // Header WAV simple (24k)
  const sampleRate = 24000;
  const wavHeader = new ArrayBuffer(44);
  const view = new DataView(wavHeader);
  const writeString = (offset, string) => {
    for (let i = 0; i < string.length; i++)
      view.setUint8(offset + i, string.charCodeAt(i));
  };

  writeString(0, "RIFF");
  view.setUint32(4, 32 + bytes.length, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, bytes.length, true);

  const blob = new Blob([wavHeader, bytes], { type: "audio/wav" });
  const audio = new Audio(URL.createObjectURL(blob));
  audio.play().catch(() => {});
};

// ------------------------------------------------------------
// APP
// ------------------------------------------------------------
const App = () => {
  const [view, setView] = useState("list");
  const [user, setUser] = useState(null);

  const [loading, setLoading] = useState(true);
  const [events, setEvents] = useState([]);
  const [categories, setCategories] = useState(["Todos"]);
  const [selectedEvent, setSelectedEvent] = useState(null);

  const [activeFilter, setActiveFilter] = useState("Todos");
  const [searchTerm, setSearchTerm] = useState("");

  // IA
  const [aiRecommendation, setAiRecommendation] = useState("");
  const [isAiLoading, setIsAiLoading] = useState(false);
  const [userInput, setUserInput] = useState("");
  const [isTtsLoading, setIsTtsLoading] = useState(false);
  const [fanArt, setFanArt] = useState(null);
  const [isFanArtLoading, setIsFanArtLoading] = useState(false);

  // Checkout
  const [checkoutStep, setCheckoutStep] = useState("selection"); // selection | form | success
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [formData, setFormData] = useState({
    dni: "",
    name: "",
    email: "",
    phone: "",
    seller_code: "",
  });
  const [isProcessing, setIsProcessing] = useState(false);
  const [checkoutError, setCheckoutError] = useState("");

  useEffect(() => {
    onAuthStateChanged(auth, (u) => {
      setUser(u);
      if (u) {
        setFormData((prev) => ({
          ...prev,
          name: u.displayName || prev.name,
          email: u.email || prev.email,
        }));
      }
      setLoading(false);
    });
  }, []);

  const fetchData = async () => {
    try {
      const catQuery =
        activeFilter !== "Todos"
          ? `?category=${encodeURIComponent(activeFilter)}`
          : "";

      const [evRes, catRes] = await Promise.all([
        fetch(`/api/public/events${catQuery}`),
        fetch(`/api/public/categories`),
      ]);

      // Events
      if (evRes.ok) {
        const rawEvents = await evRes.json();
        const normalized = (Array.isArray(rawEvents) ? rawEvents : []).map(
          normalizeEvent
        );

        // Siempre meto el MOCK arriba para no “quedarnos en cero” si hay data rara
        const withoutMock = normalized.filter((e) => e.slug !== MOCK_EVENT.slug);
        setEvents([MOCK_EVENT, ...withoutMock]);
      } else {
        setEvents([MOCK_EVENT]);
      }

      // Categories
      if (catRes.ok) {
        const rawCats = await catRes.json();
        setCategories(normalizeCategories(rawCats));
      } else {
        setCategories(["Todos"]);
      }
    } catch (e) {
      console.error("Error API:", e);
      setEvents([MOCK_EVENT]);
      setCategories(["Todos"]);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFilter]);

  const openDetail = async (slug) => {
    if (!slug || slug === "slug") return;

    setCheckoutError("");
    setSelectedTicket(null);
    setCheckoutStep("selection");
    setFanArt(null);

    if (slug === MOCK_EVENT.slug) {
      setSelectedEvent(MOCK_EVENT);
      setView("detail");
      window.scrollTo(0, 0);
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`/api/public/events/${slug}`);
      if (res.ok) {
        const raw = await res.json();
        const normalized = normalizeEvent(raw);
        setSelectedEvent({ ...normalized, ...raw, tickets: normalized.tickets });
        setView("detail");
        window.scrollTo(0, 0);
      }
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  const handleAiRecommend = async () => {
    if (!userInput) return;
    setIsAiLoading(true);

    const eventListStr = events
      .map((e) => `${e.title} (${e.category})`)
      .join(", ");

    const prompt = `Usuario dice: "${userInput}". Lista de eventos disponibles: ${eventListStr}. Recomienda el mejor evento de la lista de forma breve y persuasiva.`;
    const system =
      "Eres el Gurú de Experiencias de Yendiin. Responde de forma emocionante y breve.";

    const resp = await fetchGemini(prompt, system);
    setAiRecommendation(resp);
    setIsAiLoading(false);
  };

  const handleTts = async () => {
    if (!selectedEvent) return;
    setIsTtsLoading(true);

    const textToRead = `${selectedEvent.title}. Se presenta en ${
      selectedEvent.venue || "un lugar increíble"
    } el ${selectedEvent.date_text}. No te lo pierdas.`;

    const audioData = await fetchTTS(textToRead);
    if (audioData) playAudioFromPCM(audioData);

    setIsTtsLoading(false);
  };

  const handleGenerateFanArt = async () => {
    if (!selectedEvent) return;
    setIsFanArtLoading(true);

    const prompt = `A cinematic, ultra-realistic artistic fan poster for a concert or show titled "${selectedEvent.title}". Style: high-end lighting, futuristic indigo vibes, no text, masterpiece.`;

    const imgUrl = await generateImage(prompt);
    if (imgUrl) setFanArt(imgUrl);

    setIsFanArtLoading(false);
  };

  const startCheckout = (ticket) => {
    setCheckoutError("");

    // Si querés forzar login antes de comprar:
    if (!user) {
      setCheckoutError("Para comprar necesitás iniciar sesión con Google.");
      return;
    }

    setSelectedTicket(ticket);
    setCheckoutStep("form");
  };

  const handlePurchaseSubmit = async (e) => {
    e.preventDefault();
    setCheckoutError("");

    if (!selectedEvent || !selectedTicket) {
      setCheckoutError("Falta seleccionar el evento o la entrada.");
      return;
    }

    if (!user) {
      setCheckoutError("Para comprar necesitás iniciar sesión con Google.");
      return;
    }

    setIsProcessing(true);

    try {
      // ✅ ACA VA LA INTEGRACIÓN REAL AL BACK
      // Por ejemplo:
      // const payload = {
      //   event_slug: selectedEvent.slug,
      //   sale_item_id: selectedTicket.id,
      //   qty: 1,
      //   buyer: { ...formData },
      // };
      //
      // const res = await fetch("/api/orders/create", {
      //   method: "POST",
      //   headers: { "Content-Type": "application/json" },
      //   body: JSON.stringify(payload),
      // });
      // if (!res.ok) throw new Error("No se pudo iniciar el pago");
      // const data = await res.json();
      // -> redirigir a link de pago, etc.

      // Por ahora simulamos éxito
      await new Promise((r) => setTimeout(r, 1200));
      setCheckoutStep("success");
    } catch (err) {
      setCheckoutError(err?.message || "Error procesando la compra.");
    } finally {
      setIsProcessing(false);
    }
  };

  if (loading && view === "list") {
    return (
      <div className="h-screen bg-[#0a0a0a] flex flex-col items-center justify-center">
        <Loader2 className="w-10 h-10 animate-spin text-indigo-500 mb-4" />
        <p className="text-neutral-500 font-bold uppercase tracking-widest text-[10px]">
          Iniciando Yendiin
        </p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white font-sans selection:bg-indigo-500/30">
      {/* Navbar */}
      <nav className="sticky top-0 z-50 bg-black/80 backdrop-blur-xl border-b border-white/5 px-6 py-4 flex justify-between items-center">
        <div
          className="flex items-center gap-2 cursor-pointer group"
          onClick={() => {
            setView("list");
            setSelectedEvent(null);
          }}
        >
          <div className="w-9 h-9 bg-indigo-600 rounded-xl flex items-center justify-center font-black italic shadow-lg shadow-indigo-500/20 group-hover:scale-110 transition-transform">
            T
          </div>
          <span className="font-black tracking-tighter text-2xl italic uppercase">
            Yen<span className="text-indigo-500">diin</span>
          </span>
        </div>

        <button
          onClick={() =>
            user ? signOut(auth) : signInWithPopup(auth, new GoogleAuthProvider())
          }
          className="bg-white text-black px-6 py-2.5 rounded-full font-black text-[11px] uppercase hover:bg-indigo-500 hover:text-white transition-all active:scale-95 shadow-xl"
        >
          {user ? user.displayName?.split(" ")?.[0] || "Salir" : "Ingresar"}
        </button>
      </nav>

      {/* LIST */}
      {view === "list" && (
        <main className="max-w-7xl mx-auto px-6 py-16 animate-in fade-in duration-700">
          <h1 className="text-7xl md:text-9xl font-black mb-12 tracking-tighter uppercase italic leading-[0.85]">
            Vivilo <br /> <span className="text-indigo-500">en vivo</span>
          </h1>

          {/* AI */}
          <div className="mb-12 bg-indigo-900/10 border border-indigo-500/20 p-8 rounded-[3rem] backdrop-blur-sm">
            <div className="flex items-center gap-3 mb-6">
              <Sparkles className="text-indigo-400 w-6 h-6" />
              <h2 className="text-xl font-black uppercase italic tracking-tighter">
                ¿No sabés qué elegir? ✨
              </h2>
            </div>

            <div className="flex flex-col md:flex-row gap-4">
              <input
                type="text"
                placeholder="Ej: 'Algo emocionante este finde' o 'Me gusta el teatro'..."
                className="flex-grow bg-neutral-900/50 border border-white/10 rounded-2xl py-4 px-6 outline-none focus:border-indigo-500"
                value={userInput}
                onChange={(e) => setUserInput(e.target.value)}
              />
              <button
                onClick={handleAiRecommend}
                disabled={isAiLoading}
                className="bg-indigo-600 px-8 py-4 rounded-2xl font-black text-xs uppercase hover:bg-indigo-500 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {isAiLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <MessageSquare className="w-4 h-4" />
                )}
                Recomiéndame ✨
              </button>
            </div>

            {aiRecommendation && (
              <div className="mt-6 p-6 bg-indigo-600/20 rounded-2xl border border-indigo-500/30 animate-in zoom-in duration-300">
                <p className="text-indigo-100 font-medium italic">
                  "{aiRecommendation}"
                </p>
              </div>
            )}
          </div>

          {/* Search + Categories */}
          <div className="flex flex-col md:flex-row gap-4 mb-16">
            <div className="relative flex-grow">
              <Search className="absolute left-5 top-1/2 -translate-y-1/2 text-neutral-500 w-5 h-5" />
              <input
                type="text"
                placeholder="Buscá artistas o ciudades..."
                className="w-full bg-neutral-900 border border-white/10 rounded-2xl py-6 pl-14 pr-4 outline-none focus:border-indigo-500 text-lg"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>

            <div className="flex gap-2 overflow-x-auto no-scrollbar pb-2">
              {categories.map((cat) => (
                <button
                  key={cat}
                  onClick={() => setActiveFilter(cat)}
                  className={`px-8 py-4 rounded-2xl font-black text-[11px] uppercase transition-all border shrink-0 ${
                    activeFilter === cat
                      ? "bg-indigo-600 border-indigo-500 shadow-xl shadow-indigo-500/30"
                      : "bg-neutral-900 border-white/5 text-neutral-500 hover:text-white"
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          {/* Events Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-10">
            {events
              .filter((e) =>
                (e.title || "").toLowerCase().includes(searchTerm.toLowerCase())
              )
              .map((event) => (
                <div
                  key={event.slug || `${event.title}-${event.date_text}`}
                  onClick={() => openDetail(event.slug)}
                  className="group bg-neutral-900/40 rounded-[3rem] overflow-hidden border border-white/5 hover:border-indigo-500/40 transition-all cursor-pointer shadow-2xl hover:-translate-y-2 duration-500"
                >
                  <div className="h-72 overflow-hidden relative bg-neutral-800">
                    <img
                      src={resolveFlyerSrc(event.flyer_url)}
                      onError={(e) => (e.currentTarget.src = FALLBACK_FLYER)}
                      className="h-full w-full object-cover opacity-80 group-hover:scale-110 transition-transform duration-1000"
                      alt="flyer"
                    />
                    <div className="absolute top-6 left-6 bg-indigo-600 px-4 py-1.5 rounded-full text-[10px] font-black tracking-widest uppercase">
                      {event.category}
                    </div>
                  </div>

                  <div className="p-10">
                    <p className="text-indigo-400 text-[10px] font-black uppercase tracking-widest mb-3">
                      {event.date_text || "PRÓXIMAMENTE"}
                    </p>
                    <h3 className="text-3xl font-black mb-6 uppercase italic leading-none tracking-tighter group-hover:text-indigo-400 transition-colors">
                      {event.title}
                    </h3>
                    <div className="flex items-center justify-between text-neutral-500 text-[11px] font-bold uppercase">
                      <span className="flex items-center gap-2">
                        <MapPin className="w-4 h-4" /> {event.city || "—"}
                      </span>
                      <span className="text-indigo-500 font-black opacity-0 group-hover:opacity-100 transition-opacity">
                        Tickets →
                      </span>
                    </div>
                  </div>
                </div>
              ))}
          </div>
        </main>
      )}

      {/* DETAIL + CHECKOUT */}
      {view === "detail" && selectedEvent && (
        <div className="max-w-7xl mx-auto px-6 py-12 animate-in slide-in-from-right duration-500">
          <button
            onClick={() => {
              setView("list");
              setSelectedEvent(null);
            }}
            className="flex items-center gap-2 text-neutral-500 hover:text-white mb-12 font-black text-[10px] uppercase tracking-widest transition-colors"
          >
            <ChevronLeft className="w-5 h-5" /> Volver a cartelera
          </button>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-20">
            {/* Left */}
            <div className="space-y-8">
              <div className="relative group">
                <img
                  src={fanArt || resolveFlyerSrc(selectedEvent.flyer_url)}
                  onError={(e) => (e.currentTarget.src = FALLBACK_FLYER)}
                  className={`rounded-[4rem] shadow-2xl w-full aspect-[3/4] object-cover border border-white/10 transition-all duration-1000 ${
                    fanArt ? "animate-in zoom-in" : ""
                  }`}
                  alt="flyer"
                />
                <div className="absolute -bottom-6 -right-6 w-24 h-24 bg-indigo-600 rounded-[2.5rem] flex items-center justify-center rotate-12 shadow-2xl border-4 border-[#0a0a0a]">
                  <Ticket className="w-10 h-10 text-white -rotate-12" />
                </div>

                <button
                  onClick={handleGenerateFanArt}
                  disabled={isFanArtLoading}
                  className="absolute top-6 right-6 bg-black/60 backdrop-blur-md p-4 rounded-full border border-white/20 hover:bg-indigo-600 transition-all disabled:opacity-50 group-hover:scale-110"
                  title="Generar Póster Artístico ✨"
                >
                  {isFanArtLoading ? (
                    <Loader2 className="w-6 h-6 animate-spin" />
                  ) : (
                    <ImageIcon className="w-6 h-6" />
                  )}
                </button>
              </div>

              <div className="bg-neutral-900/50 p-8 rounded-[3rem] border border-white/5 relative overflow-hidden">
                <div className="flex items-center justify-between mb-6">
                  <h4 className="text-indigo-400 font-black text-[10px] uppercase tracking-widest">
                    Sobre el evento
                  </h4>
                  <button
                    onClick={handleTts}
                    disabled={isTtsLoading}
                    className="flex items-center gap-2 text-[9px] font-black uppercase text-neutral-500 hover:text-white transition-colors"
                  >
                    {isTtsLoading ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <Volume2 className="w-3 h-3" />
                    )}{" "}
                    Narrar ✨
                  </button>
                </div>

                <p className="text-neutral-400 italic text-xl leading-relaxed">
                  {selectedEvent.description || "—"}
                </p>

                <div className="mt-8 flex gap-6 opacity-30 items-center">
                  <Share2 className="w-5 h-5" />
                  <span className="text-[10px] font-black uppercase">
                    COMPARTIR
                  </span>
                </div>
              </div>
            </div>

            {/* Right */}
            <div className="flex flex-col">
              <span className="text-indigo-500 font-black tracking-widest uppercase text-[10px] mb-6 block">
                {selectedEvent.category}
              </span>

              <h2 className="text-7xl font-black mb-10 leading-[0.85] tracking-tighter uppercase italic drop-shadow-2xl">
                {selectedEvent.title}
              </h2>

              <div className="grid grid-cols-2 gap-4 mb-10">
                <div className="bg-neutral-900 border border-white/5 p-6 rounded-3xl">
                  <p className="text-[10px] font-black text-neutral-500 uppercase mb-1 tracking-widest">
                    Fecha
                  </p>
                  <p className="font-bold text-lg italic">
                    {selectedEvent.date_text || "—"}
                  </p>
                </div>
                <div className="bg-neutral-900 border border-white/5 p-6 rounded-3xl">
                  <p className="text-[10px] font-black text-neutral-500 uppercase mb-1 tracking-widest">
                    Lugar
                  </p>
                  <p className="font-bold text-lg italic leading-tight">
                    {selectedEvent.venue || "—"}
                  </p>
                </div>
              </div>

              <div className="bg-neutral-900/80 p-8 md:p-12 rounded-[4rem] border border-indigo-500/10 backdrop-blur-md shadow-2xl relative overflow-hidden">
                {checkoutStep === "selection" && (
                  <div className="animate-in fade-in duration-500">
                    <div className="flex items-center gap-3 mb-10">
                      <Clock className="w-4 h-4 text-indigo-400" />
                      <p className="text-xs font-black uppercase text-indigo-400 tracking-widest">
                        Elegí tu entrada
                      </p>
                    </div>

                    {checkoutError && (
                      <div className="mb-6 p-4 rounded-2xl bg-indigo-600/15 border border-indigo-500/30 text-indigo-100 text-sm">
                        {checkoutError}
                      </div>
                    )}

                    <div className="space-y-4">
                      {(selectedEvent.tickets || []).map((t) => {
                        const stockTotal = Number(t.stock_total ?? 0);
                        const stockSold = Number(t.stock_sold ?? 0);
                        const stockLeft = Math.max(0, stockTotal - stockSold);
                        const price = Number(t.price_cents ?? 0) / 100;

                        return (
                          <div
                            key={t.id || t.name}
                            onClick={() => startCheckout(t)}
                            className="bg-black/40 border border-white/5 p-7 rounded-[2.5rem] flex justify-between items-center group hover:border-indigo-500/30 cursor-pointer transition-all"
                          >
                            <div>
                              <p className="font-black text-2xl uppercase italic group-hover:text-indigo-400 transition-colors">
                                {t.name || "Entrada"}
                              </p>
                              <p className="text-[10px] font-bold text-neutral-600 uppercase tracking-widest">
                                Stock: {stockLeft}
                              </p>
                            </div>
                            <span className="bg-white text-black px-8 py-4 rounded-2xl font-black text-xs hover:bg-indigo-500 hover:text-white transition-all shadow-xl">
                              ${price.toFixed(0)}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {checkoutStep === "form" && selectedTicket && (
                  <div className="animate-in slide-in-from-bottom-4 duration-500">
                    <div className="flex items-center justify-between mb-10">
                      <p className="text-xs font-black uppercase text-indigo-400 tracking-widest">
                        Checkout de compra
                      </p>
                      <button
                        type="button"
                        onClick={() => {
                          setCheckoutStep("selection");
                          setSelectedTicket(null);
                          setCheckoutError("");
                        }}
                        className="text-[10px] font-black text-neutral-500 hover:text-white border-b border-white/10 pb-1"
                      >
                        Cambiar Entrada
                      </button>
                    </div>

                    {checkoutError && (
                      <div className="mb-6 p-4 rounded-2xl bg-indigo-600/15 border border-indigo-500/30 text-indigo-100 text-sm">
                        {checkoutError}
                      </div>
                    )}

                    <form onSubmit={handlePurchaseSubmit} className="space-y-4">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="relative">
                          <Fingerprint className="absolute left-5 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" />
                          <input
                            required
                            type="text"
                            placeholder="DNI / CUIT"
                            className="w-full bg-black/40 border border-white/10 rounded-[1.5rem] py-5 pl-14 pr-4 outline-none focus:border-indigo-500 transition-all text-sm"
                            value={formData.dni}
                            onChange={(e) =>
                              setFormData({ ...formData, dni: e.target.value })
                            }
                          />
                        </div>
                        <div className="relative">
                          <User className="absolute left-5 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" />
                          <input
                            required
                            type="text"
                            placeholder="Nombre Completo"
                            className="w-full bg-black/40 border border-white/10 rounded-[1.5rem] py-5 pl-14 pr-4 outline-none focus:border-indigo-500 transition-all text-sm"
                            value={formData.name}
                            onChange={(e) =>
                              setFormData({
                                ...formData,
                                name: e.target.value,
                              })
                            }
                          />
                        </div>
                      </div>

                      <div className="relative">
                        <Mail className="absolute left-5 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" />
                        <input
                          required
                          type="email"
                          placeholder="Correo Electrónico"
                          className="w-full bg-black/40 border border-white/10 rounded-[1.5rem] py-5 pl-14 pr-4 outline-none focus:border-indigo-500 transition-all text-sm"
                          value={formData.email}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              email: e.target.value,
                            })
                          }
                        />
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="relative">
                          <Phone className="absolute left-5 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" />
                          <input
                            required
                            type="tel"
                            placeholder="WhatsApp"
                            className="w-full bg-black/40 border border-white/10 rounded-[1.5rem] py-5 pl-14 pr-4 outline-none focus:border-indigo-500 transition-all text-sm"
                            value={formData.phone}
                            onChange={(e) =>
                              setFormData({
                                ...formData,
                                phone: e.target.value,
                              })
                            }
                          />
                        </div>
                        <div className="relative">
                          <Tag className="absolute left-5 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" />
                          <input
                            type="text"
                            placeholder="Seller Code (Opc.)"
                            className="w-full bg-black/40 border border-white/10 rounded-[1.5rem] py-5 pl-14 pr-4 outline-none focus:border-indigo-500 transition-all text-sm"
                            value={formData.seller_code}
                            onChange={(e) =>
                              setFormData({
                                ...formData,
                                seller_code: e.target.value,
                              })
                            }
                          />
                        </div>
                      </div>

                      <div className="pt-8 mt-4 border-t border-white/5">
                        <div className="flex justify-between items-center mb-8">
                          <span className="text-neutral-500 font-black text-xs uppercase tracking-widest">
                            Total compra
                          </span>
                          <span className="text-4xl font-black text-indigo-500 italic">
                            ${(Number(selectedTicket.price_cents ?? 0) / 100).toFixed(0)}
                          </span>
                        </div>

                        <button
                          disabled={isProcessing}
                          className="w-full bg-white text-black h-20 rounded-[2rem] font-black uppercase text-xs tracking-widest hover:bg-indigo-600 hover:text-white transition-all shadow-2xl flex items-center justify-center gap-4 active:scale-95 disabled:opacity-50"
                        >
                          {isProcessing ? (
                            <Loader2 className="w-6 h-6 animate-spin" />
                          ) : (
                            <CreditCard className="w-6 h-6" />
                          )}
                          Confirmar Pago Seguro
                        </button>
                      </div>
                    </form>
                  </div>
                )}

                {checkoutStep === "success" && (
                  <div className="text-center py-16 animate-in zoom-in-95 duration-500">
                    <div className="w-24 h-24 bg-indigo-600 rounded-[2.5rem] flex items-center justify-center mx-auto mb-10 shadow-2xl shadow-indigo-500/50">
                      <CheckCircle2 className="w-12 h-12 text-white" />
                    </div>
                    <h3 className="text-5xl font-black mb-6 uppercase italic leading-none">
                      ¡Compra Exitosa!
                    </h3>
                    <p className="text-neutral-500 text-lg mb-12 italic leading-relaxed">
                      Tu entrada para{" "}
                      <span className="text-white font-bold">
                        {selectedEvent.title}
                      </span>{" "}
                      ya está lista. Te enviamos el QR a{" "}
                      <span className="text-indigo-400 font-bold">
                        {formData.email}
                      </span>
                      .
                    </p>
                    <button
                      onClick={() => {
                        setView("list");
                        setSelectedEvent(null);
                      }}
                      className="bg-neutral-800 text-white px-12 py-5 rounded-[1.5rem] font-black text-[10px] uppercase tracking-widest hover:bg-indigo-600 transition-all shadow-xl"
                    >
                      Volver a Cartelera
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <footer className="mt-40 border-t border-white/5 py-32 text-center bg-black/40 relative">
        <div className="flex items-center justify-center gap-3 mb-10 opacity-30">
          <div className="w-8 h-8 bg-white rounded-xl flex items-center justify-center font-black text-black text-xs">
            T
          </div>
          <span className="font-black text-xs tracking-[1em] uppercase italic">
            Yendiin
          </span>
        </div>
        <p className="text-neutral-800 font-bold text-[9px] uppercase tracking-[0.5em]">
          © 2026 Yendiin · UI
        </p>
      </footer>
    </div>
  );
};

export default App;
