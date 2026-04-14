import React, { useState, useEffect } from "react";
import {
  Loader2,
  MapPin,
  Ticket,
  Search,
  ChevronLeft,
  Sparkles,
  CreditCard,
  CheckCircle2,
  User,
  Mail,
  Fingerprint,
  Phone,
  Tag,
  Share2,
  Calendar,
  Info,
  Clock,
  AlertCircle,
  Plus,
  LayoutDashboard,
  Users,
  ShoppingCart,
  Power,
  Edit3,
  TrendingUp,
  BarChart3,
  Settings,
  Save,
  Trash2,
  ExternalLink,
  X,
} from "lucide-react";

import { initializeApp } from "firebase/app";
import {
  getAuth, signInWithPopup, GoogleAuthProvider,
  onAuthStateChanged, signOut,
} from "firebase/auth";

// --- CONFIGURACIÓN ---
const apiKey = ""; 
const firebaseConfig = typeof __firebase_config !== 'undefined' 
  ? JSON.parse(__firebase_config) 
  : { apiKey: "AIza...", authDomain: "tu-app.firebaseapp.com", projectId: "tu-app" };

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

// --- COMPONENTE PRINCIPAL ---
const App = () => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [role, setRole] = useState("client"); // 'client' o 'producer'
  
  // Estados de Productor
  const [producerTab, setProducerTab] = useState("events"); // 'events', 'dashboard', 'sellers', 'items'
  const [producerEvents, setProducerEvents] = useState([]);
  const [selectedProducerEvent, setSelectedProducerEvent] = useState(null);
  const [stats, setStats] = useState(null);
  const [sellers, setSellers] = useState([]);
  const [items, setItems] = useState([]);
  
  // Modales y Formularios
  const [showModal, setShowModal] = useState(false); // 'event', 'seller', 'item'
  const [isActionLoading, setIsActionLoading] = useState(false);

  useEffect(() => {
    onAuthStateChanged(auth, (u) => {
      setUser(u);
      setLoading(false);
    });
  }, []);

  // --- LÓGICA DE DATOS (API) ---

  const fetchProducerEvents = async () => {
    try {
      const res = await fetch('/api/producer/events');
      if (res.ok) setProducerEvents(await res.json());
    } catch (e) { console.error("Error cargando eventos:", e); }
  };

  const fetchEventDashboard = async (slug) => {
    try {
      const res = await fetch(`/api/producer/events/${slug}/dashboard`);
      if (res.ok) setStats(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchSellers = async (slug) => {
    try {
      const res = await fetch(`/api/producer/events/${slug}/sellers`);
      if (res.ok) setSellers(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchItems = async (slug) => {
    try {
      const res = await fetch(`/api/producer/events/${slug}/items`);
      if (res.ok) setItems(await res.json());
    } catch (e) { console.error(e); }
  };

  useEffect(() => {
    if (role === "producer") {
      fetchProducerEvents();
    }
  }, [role]);

  useEffect(() => {
    if (selectedProducerEvent) {
      if (producerTab === "dashboard") fetchEventDashboard(selectedProducerEvent.slug);
      if (producerTab === "sellers") fetchSellers(selectedProducerEvent.slug);
      if (producerTab === "items") fetchItems(selectedProducerEvent.slug);
    }
  }, [producerTab, selectedProducerEvent]);

  // --- HANDLERS ---

  const toggleEventStatus = async (slug, currentActive) => {
    try {
      const res = await fetch('/api/producer/events/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slug, active: !currentActive })
      });
      if (res.ok) fetchProducerEvents();
    } catch (e) { console.error(e); }
  };

  const handleCreateEvent = async (e) => {
    e.preventDefault();
    setIsActionLoading(true);
    const form = e.target;
    const payload = {
      slug: form.slug.value,
      title: form.title.value,
      category: form.category.value,
      date_text: form.date_text.value,
      venue: form.venue.value,
      city: form.city.value,
      flyer_url: form.flyer_url.value
    };

    try {
      const res = await fetch('/api/producer/events/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        setShowModal(false);
        fetchProducerEvents();
      }
    } catch (e) { console.error(e); }
    setIsActionLoading(false);
  };

  const handleAddSeller = async (e) => {
    e.preventDefault();
    setIsActionLoading(true);
    try {
      const res = await fetch('/api/producer/sellers/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event_slug: selectedProducerEvent.slug,
          code: e.target.code.value,
          name: e.target.name.value
        })
      });
      if (res.ok) {
        setShowModal(false);
        fetchSellers(selectedProducerEvent.slug);
      }
    } catch (e) { console.error(e); }
    setIsActionLoading(false);
  };

  if (loading) return (
    <div className="h-screen bg-[#0a0a0a] flex items-center justify-center">
      <Loader2 className="w-10 h-10 animate-spin text-indigo-500" />
    </div>
  );

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white font-sans selection:bg-indigo-500/30">
      {/* Navbar Premium */}
      <nav className="sticky top-0 z-50 bg-black/80 backdrop-blur-xl border-b border-white/5 px-6 py-4 flex justify-between items-center">
        <div className="flex items-center gap-2 cursor-pointer group" onClick={() => setRole("client")}>
          <div className="w-9 h-9 bg-indigo-600 rounded-xl flex items-center justify-center font-black italic shadow-lg shadow-indigo-500/20 group-hover:scale-110 transition-transform">T</div>
          <span className="font-black tracking-tighter text-2xl italic uppercase">Ticket<span className="text-indigo-500">Pro</span></span>
        </div>
        
        <div className="flex items-center gap-4">
          <button 
            onClick={() => setRole(role === "client" ? "producer" : "client")}
            className="flex items-center gap-2 bg-neutral-900 border border-white/10 px-4 py-2 rounded-full text-[10px] font-black uppercase hover:bg-white hover:text-black transition-all"
          >
            {role === "client" ? <LayoutDashboard className="w-3 h-3" /> : <ExternalLink className="w-3 h-3" />}
            {role === "client" ? "Modo Productor" : "Ver como Cliente"}
          </button>
          
          {user && (
            <div className="flex items-center gap-3 bg-neutral-900 border border-white/10 pl-1 pr-4 py-1 rounded-full">
              <img src={user.photoURL} className="w-7 h-7 rounded-full shadow-inner" alt="avatar" />
              <button onClick={() => signOut(auth)} className="text-[10px] font-black text-neutral-500 hover:text-white uppercase transition-colors">Salir</button>
            </div>
          )}
        </div>
      </nav>

      {role === "client" ? (
        /* VISTA CLIENTE (Portal que ya teníamos) */
        <main className="max-w-7xl mx-auto px-6 py-16 animate-in fade-in duration-700">
          <h1 className="text-7xl md:text-9xl font-black mb-12 tracking-tighter uppercase italic leading-[0.85]">
            Explorá <br /> <span className="text-indigo-500">experiencias</span>
          </h1>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {/* Aquí iría el mapeo de eventos que ya construimos */}
            <p className="text-neutral-500 italic">Cargando cartelera principal...</p>
          </div>
        </main>
      ) : (
        /* VISTA PRODUCTOR (Dashboard) */
        <main className="max-w-7xl mx-auto px-6 py-12 animate-in slide-in-from-right-4 duration-500">
          <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-12 gap-6">
            <div>
              <h2 className="text-4xl font-black uppercase italic tracking-tighter">Panel de Producción</h2>
              <p className="text-neutral-500 text-sm font-bold uppercase tracking-widest mt-1">Gestión de Eventos y Ventas</p>
            </div>
            <button 
              onClick={() => { setShowModal('event'); }}
              className="bg-indigo-600 px-6 py-3 rounded-2xl font-black text-xs uppercase flex items-center gap-2 hover:bg-indigo-500 transition-all shadow-xl shadow-indigo-600/20 active:scale-95"
            >
              <Plus className="w-4 h-4" /> Nuevo Evento
            </button>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
            {/* Sidebar de Eventos */}
            <div className="lg:col-span-1 space-y-4">
              <h3 className="text-[10px] font-black text-neutral-600 uppercase tracking-[0.2em] mb-4">Tus Eventos</h3>
              {producerEvents.length === 0 ? (
                <div className="p-8 border-2 border-dashed border-white/5 rounded-3xl text-center">
                  <p className="text-neutral-700 text-[10px] font-bold uppercase">No hay eventos</p>
                </div>
              ) : (
                producerEvents.map(ev => (
                  <div 
                    key={ev.slug} 
                    onClick={() => { setSelectedProducerEvent(ev); setProducerTab("dashboard"); }}
                    className={`p-5 rounded-3xl cursor-pointer transition-all border ${selectedProducerEvent?.slug === ev.slug ? 'bg-indigo-600 border-indigo-400 shadow-xl' : 'bg-neutral-900 border-white/5 hover:border-white/10'}`}
                  >
                    <div className="flex justify-between items-start mb-2">
                      <span className={`text-[8px] font-black px-2 py-0.5 rounded-full uppercase ${ev.active ? 'bg-white text-black' : 'bg-black text-white/40'}`}>
                        {ev.active ? 'Activo' : 'Pausado'}
                      </span>
                      <Settings className="w-3 h-3 text-white/20" />
                    </div>
                    <h4 className="font-black uppercase italic text-sm leading-tight truncate">{ev.title}</h4>
                    <p className="text-[10px] text-white/50 mt-1">{ev.date_text}</p>
                  </div>
                ))
              )}
            </div>


            {/* Contenido Dinámico del Dashboard */}
            <div className="lg:col-span-3">
              {selectedProducerEvent ? (
                <div className="bg-neutral-900/40 border border-white/5 rounded-[3rem] p-10 backdrop-blur-sm animate-in fade-in duration-500">
                  <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-10 gap-6">
                    <div>
                      <h3 className="text-3xl font-black uppercase italic tracking-tighter leading-none">{selectedProducerEvent.title}</h3>
                      <div className="flex items-center gap-4 mt-3">
                        <span className="flex items-center gap-1 text-[10px] font-bold text-neutral-500 uppercase"><MapPin className="w-3 h-3" /> {selectedProducerEvent.venue}</span>
                        <span className="w-1 h-1 bg-neutral-700 rounded-full"></span>
                        <span className="flex items-center gap-1 text-[10px] font-bold text-neutral-500 uppercase"><Calendar className="w-3 h-3" /> {selectedProducerEvent.date_text}</span>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button 
                        onClick={() => toggleEventStatus(selectedProducerEvent.slug, selectedProducerEvent.active)}
                        className={`p-4 rounded-2xl border transition-all ${selectedProducerEvent.active ? 'border-red-500/30 text-red-500 hover:bg-red-500 hover:text-white' : 'border-green-500/30 text-green-500 hover:bg-green-500 hover:text-white'}`}
                        title={selectedProducerEvent.active ? "Pausar Evento" : "Activar Evento"}
                      >
                        <Power className="w-5 h-5" />
                      </button>
                      <button className="p-4 bg-neutral-800 border border-white/5 rounded-2xl hover:bg-neutral-700 transition-all">
                        <Edit3 className="w-5 h-5" />
                      </button>
                    </div>
                  </div>
                <button onClick={() => nav("/")}>Ver como Cliente</button>
                  {/* Tabs del Evento */}
                  <div className="flex gap-1 bg-black/40 p-1.5 rounded-2xl mb-10 overflow-x-auto no-scrollbar">
                    <button 
                      onClick={() => setProducerTab("dashboard")} 
                      className={`flex items-center gap-2 px-6 py-3 rounded-xl font-black text-[10px] uppercase transition-all ${producerTab === "dashboard" ? 'bg-indigo-600 text-white' : 'text-neutral-500 hover:text-white'}`}
                    >
                      <TrendingUp className="w-4 h-4" /> Ventas
                    </button>
                    <button 
                      onClick={() => setProducerTab("items")} 
                      className={`flex items-center gap-2 px-6 py-3 rounded-xl font-black text-[10px] uppercase transition-all ${producerTab === "items" ? 'bg-indigo-600 text-white' : 'text-neutral-500 hover:text-white'}`}
                    >
                      <ShoppingCart className="w-4 h-4" /> Sale Items
                    </button>
                    <button 
                      onClick={() => setProducerTab("sellers")} 
                      className={`flex items-center gap-2 px-6 py-3 rounded-xl font-black text-[10px] uppercase transition-all ${producerTab === "sellers" ? 'bg-indigo-600 text-white' : 'text-neutral-500 hover:text-white'}`}
                    >
                      <Users className="w-4 h-4" /> Vendedores
                    </button>
                  </div>

                  {/* Contenido de la Tab */}
                  <div className="animate-in fade-in slide-in-from-bottom-2 duration-500">
                    {producerTab === "dashboard" && stats && (
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                        <div className="bg-black/40 border border-white/5 p-8 rounded-[2.5rem]">
                          <BarChart3 className="w-8 h-8 text-indigo-500 mb-6" />
                          <p className="text-[10px] font-black text-neutral-500 uppercase tracking-widest mb-1">Recaudación Total</p>
                          <h4 className="text-4xl font-black italic tracking-tighter">${(stats.total_cents / 100).toLocaleString()}</h4>
                        </div>
                        <div className="bg-black/40 border border-white/5 p-8 rounded-[2.5rem]">
                          <Ticket className="w-8 h-8 text-indigo-500 mb-6" />
                          <p className="text-[10px] font-black text-neutral-500 uppercase tracking-widest mb-1">Entradas Emitidas</p>
                          <h4 className="text-4xl font-black italic tracking-tighter">{stats.tickets_issued}</h4>
                        </div>
                        <div className="bg-black/40 border border-white/5 p-8 rounded-[2.5rem]">
                          <TrendingUp className="w-8 h-8 text-green-500 mb-6" />
                          <p className="text-[10px] font-black text-neutral-500 uppercase tracking-widest mb-1">Órdenes Pagas</p>
                          <h4 className="text-4xl font-black italic tracking-tighter">{stats.order_count}</h4>
                        </div>
                      </div>
                    )}

                    {producerTab === "items" && (
                      <div className="space-y-4">
                        <div className="flex justify-between items-center mb-6">
                          <h4 className="text-xs font-black uppercase text-neutral-500 tracking-widest">Productos para la Venta</h4>
                          <button onClick={() => setShowModal('item')} className="text-[10px] font-black text-indigo-500 uppercase hover:underline">+ Agregar Item</button>
                        </div>
                        {items.length === 0 ? (
                          <p className="text-center py-12 text-neutral-700 font-bold uppercase text-[10px]">No hay productos cargados</p>
                        ) : (
                          <div className="grid grid-cols-1 gap-3">
                            {items.map(item => (
                              <div key={item.id} className="bg-black/40 border border-white/5 p-6 rounded-3xl flex justify-between items-center group">
                                <div className="flex items-center gap-4">
                                  <div className={`w-2 h-2 rounded-full ${item.active ? 'bg-green-500' : 'bg-red-500'}`}></div>
                                  <div>
                                    <p className="font-black uppercase italic text-sm">{item.name}</p>
                                    <p className="text-[10px] text-neutral-600 uppercase font-bold">Tipo: {item.kind} | Stock: {item.stock_sold}/{item.stock_total}</p>
                                  </div>
                                </div>
                                <div className="flex items-center gap-6">
                                  <span className="font-black text-lg text-indigo-500 italic">${(item.price_cents / 100)}</span>
                                  <Settings className="w-4 h-4 text-neutral-700 group-hover:text-white transition-colors" />
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {producerTab === "sellers" && (
                      <div className="space-y-4">
                         <div className="flex justify-between items-center mb-6">
                          <h4 className="text-xs font-black uppercase text-neutral-500 tracking-widest">Vendedores Asignados</h4>
                          <button onClick={() => setShowModal('seller')} className="text-[10px] font-black text-indigo-500 uppercase hover:underline">+ Invitar Vendedor</button>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {sellers.map(seller => (
                            <div key={seller.id} className="bg-black/40 border border-white/5 p-6 rounded-3xl flex justify-between items-center group">
                              <div className="flex items-center gap-4">
                                <div className="w-10 h-10 bg-neutral-900 rounded-full flex items-center justify-center font-black text-indigo-500 text-xs">
                                  {seller.code.slice(0, 2).toUpperCase()}
                                </div>
                                <div>
                                  <p className="font-black uppercase italic text-sm">{seller.name}</p>
                                  <p className="text-[10px] text-indigo-500 font-bold tracking-widest uppercase">CÓDIGO: {seller.code}</p>
                                </div>
                              </div>
                              <Trash2 className="w-4 h-4 text-neutral-700 group-hover:text-red-500 cursor-pointer transition-colors" />
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center border-2 border-dashed border-white/5 rounded-[4rem] py-32 text-center opacity-30">
                  <LayoutDashboard className="w-16 h-16 mb-6" />
                  <h3 className="text-2xl font-black uppercase italic">Selecciona un evento</h3>
                  <p className="text-sm font-bold uppercase tracking-widest">Para ver el detalle de producción</p>
                </div>
              )}
            </div>
          </div>
        </main>
      )}

      {/* Modales de Gestión */}
      {showModal === 'event' && (
        <div className="fixed inset-0 z-[100] bg-black/90 backdrop-blur-xl flex items-center justify-center p-6 animate-in fade-in duration-300">
          <div className="bg-neutral-900 border border-white/10 p-10 rounded-[4rem] max-w-2xl w-full relative shadow-2xl">
            <button onClick={() => setShowModal(false)} className="absolute top-8 right-8 text-neutral-500 hover:text-white"><X className="w-6 h-6" /></button>
            <h3 className="text-4xl font-black uppercase italic mb-8 tracking-tighter">Crear Nuevo Evento</h3>
            <form onSubmit={handleCreateEvent} className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <input required name="title" placeholder="Nombre del Evento" className="bg-black border border-white/5 p-5 rounded-2xl outline-none focus:border-indigo-500" />
              <input required name="slug" placeholder="Slug único (ej: rock-fest-2026)" className="bg-black border border-white/5 p-5 rounded-2xl outline-none focus:border-indigo-500" />
              <input required name="category" placeholder="Categoría" className="bg-black border border-white/5 p-5 rounded-2xl outline-none focus:border-indigo-500" />
              <input required name="date_text" placeholder="Fecha Display (ej: 12 Oct, 21hs)" className="bg-black border border-white/5 p-5 rounded-2xl outline-none focus:border-indigo-500" />
              <input required name="venue" placeholder="Lugar" className="bg-black border border-white/5 p-5 rounded-2xl outline-none focus:border-indigo-500" />
              <input required name="city" placeholder="Ciudad" className="bg-black border border-white/5 p-5 rounded-2xl outline-none focus:border-indigo-500" />
              <input required name="flyer_url" placeholder="URL del Flyer" className="col-span-full bg-black border border-white/5 p-5 rounded-2xl outline-none focus:border-indigo-500" />
              
              <button disabled={isActionLoading} className="col-span-full bg-indigo-600 py-5 rounded-2xl font-black uppercase text-xs tracking-widest mt-6 hover:bg-white hover:text-black transition-all shadow-xl shadow-indigo-600/20">
                {isActionLoading ? "Procesando..." : "Lanzar Evento"}
              </button>
            </form>
          </div>
        </div>
      )}

      {showModal === 'seller' && (
        <div className="fixed inset-0 z-[100] bg-black/90 backdrop-blur-xl flex items-center justify-center p-6">
          <div className="bg-neutral-900 border border-white/10 p-10 rounded-[3rem] max-w-md w-full relative shadow-2xl">
            <button onClick={() => setShowModal(false)} className="absolute top-8 right-8 text-neutral-500"><X className="w-6 h-6" /></button>
            <h3 className="text-3xl font-black uppercase italic mb-6">Invitar Vendedor</h3>
            <form onSubmit={handleAddSeller} className="space-y-4">
               <input required name="name" placeholder="Nombre del Vendedor" className="w-full bg-black border border-white/5 p-5 rounded-2xl outline-none focus:border-indigo-500" />
               <input required name="code" placeholder="Código Único (ej: BAR01)" className="w-full bg-black border border-white/5 p-5 rounded-2xl outline-none focus:border-indigo-500 uppercase" />
               <button className="w-full bg-indigo-600 py-5 rounded-2xl font-black uppercase text-xs tracking-widest shadow-xl">Asignar Código</button>
            </form>
          </div>
        </div>
      )}

      <footer className="mt-32 border-t border-white/5 py-12 text-center opacity-40">
        <p className="text-neutral-700 font-bold text-[9px] uppercase tracking-widest">Yendiin Producer Suite © 2026</p>
      </footer>
    </div>
  );
};

export default App;