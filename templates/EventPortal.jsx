import React, { useState, useEffect } from 'react';
import { 
  Loader2, Calendar, MapPin, Ticket, Search, LogIn, ChevronLeft, 
  CreditCard, CheckCircle2, ShoppingBag, X, Sparkles, MessageSquare
} from 'lucide-react';
import { initializeApp } from 'firebase/app';
import { 
  getAuth, signInWithPopup, GoogleAuthProvider, 
  onAuthStateChanged, signOut 
} from 'firebase/auth';

// --- CONFIGURACIÓN ---
// En Render, al estar integrado, dejamos API_BASE vacío para que use la misma URL
const API_BASE = ""; 

// Firebase Config (usa la que ya tienes configurada en tu entorno)
const firebaseConfig = JSON.parse(__firebase_config);
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

const App = () => {
  const [view, setView] = useState('list');
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [events, setEvents] = useState([]);
  const [categories, setCategories] = useState(["Todos"]);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [activeFilter, setActiveFilter] = useState("Todos");
  const [searchTerm, setSearchTerm] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [orderResult, setOrderResult] = useState(null);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (u) => {
      setUser(u);
      setLoading(false);
    });
    return () => unsubscribe();
  }, []);

  const getUrl = (path) => {
    if (path.startsWith('http')) return path;
    const base = API_BASE || (window.location.origin.startsWith('blob') ? "https://ticketera-entradas.onrender.com" : "");
    const normalizedBase = base.endsWith('/') ? base.slice(0, -1) : base;
    return `${normalizedBase}${path}`;
  };

  const fetchData = async () => {
    try {
      const catQuery = activeFilter !== "Todos" ? `?category=${activeFilter}` : "";
      const [evRes, catRes] = await Promise.all([
        fetch(getUrl(`/api/public/events${catQuery}`)),
        fetch(getUrl('/api/public/categories'))
      ]);
      
      if (evRes.ok) setEvents(await evRes.json());
      if (catRes.ok) setCategories(await catRes.json());
    } catch (error) {
      console.error("Error conectando al servidor:", error);
    }
  };

  useEffect(() => {
    fetchData();
  }, [activeFilter]);

  const openDetail = async (slug) => {
    setLoading(true);
    try {
      const res = await fetch(getUrl(`/api/public/events/${slug}`));
      if (res.ok) {
        setSelectedEvent(await res.json());
        setView('detail');
      }
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const handlePurchase = async (ticketId) => {
    if (!user) {
      const provider = new GoogleAuthProvider();
      await signInWithPopup(auth, provider);
      return;
    }
    
    setIsProcessing(true);
    try {
      const res = await fetch(getUrl('/api/orders/create'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event_slug: selectedEvent.slug,
          sale_item_id: ticketId,
          quantity: 1
        })
      });

      if (res.ok) {
        setOrderResult(await res.json());
        setView('success');
      } else {
        const err = await res.json();
        alert(err.detail || "Error en la compra");
      }
    } catch (e) { console.error(e); }
    setIsProcessing(false);
  };

  if (loading && view === 'list') {
    return (
      <div className="h-screen bg-neutral-950 flex flex-col items-center justify-center gap-4">
        <Loader2 className="w-10 h-10 animate-spin text-indigo-500" />
        <p className="text-neutral-500 font-bold uppercase tracking-widest text-xs">Cargando Cartelera...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-white font-sans selection:bg-indigo-500/30">
      {/* Navbar */}
      <nav className="sticky top-0 z-50 bg-black/80 backdrop-blur-xl border-b border-white/5 px-6 py-4 flex justify-between items-center">
        <div className="flex items-center gap-2 cursor-pointer" onClick={() => setView('list')}>
          <div className="w-8 h-8 bg-indigo-600 rounded flex items-center justify-center font-bold">T</div>
          <span className="font-bold tracking-tight text-xl italic uppercase">Ticket<span className="text-indigo-500">Pro</span></span>
        </div>
        <div>
          {user ? (
            <div className="flex items-center gap-3 bg-neutral-900 px-4 py-1.5 rounded-full border border-white/10">
              <img src={user.photoURL} className="w-6 h-6 rounded-full" alt="user" />
              <button onClick={() => signOut(auth)} className="text-[10px] font-bold text-neutral-500 hover:text-white uppercase">Salir</button>
            </div>
          ) : (
            <button onClick={() => signInWithPopup(auth, new GoogleAuthProvider())} className="bg-white text-black px-5 py-2 rounded-full font-bold text-sm flex items-center gap-2">
              <LogIn className="w-4 h-4" /> Entrar
            </button>
          )}
        </div>
      </nav>

      {/* Listado Principal */}
      {view === 'list' && (
        <div className="max-w-7xl mx-auto px-6 py-16 animate-in fade-in duration-500">
          <header className="mb-16">
            <h1 className="text-6xl font-black mb-8 uppercase italic tracking-tighter leading-none">Vivilo <span className="text-indigo-500">en vivo</span></h1>
            <div className="flex flex-col md:flex-row gap-4 mb-8">
              <div className="relative flex-grow">
                <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-neutral-500 w-5 h-5" />
                <input 
                  type="text" 
                  placeholder="Buscá artistas o ciudades..." 
                  className="w-full bg-neutral-900 border border-white/10 rounded-2xl py-5 pl-12 pr-4 outline-none focus:border-indigo-500"
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                />
              </div>
              <div className="flex gap-2 overflow-x-auto no-scrollbar">
                {categories.map(cat => (
                  <button 
                    key={cat}
                    onClick={() => setActiveFilter(cat)}
                    className={`px-8 py-5 rounded-2xl font-black text-sm transition-all border ${activeFilter === cat ? 'bg-indigo-600 border-indigo-500 shadow-xl' : 'bg-neutral-900 border-white/5 text-neutral-400'}`}
                  >
                    {cat.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          </header>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-10">
            {events.filter(e => e.title.toLowerCase().includes(searchTerm.toLowerCase())).map(event => (
              <div key={event.slug} onClick={() => openDetail(event.slug)} className="group bg-neutral-900/40 rounded-[2.5rem] overflow-hidden border border-white/5 hover:border-indigo-500/40 transition-all cursor-pointer">
                <div className="h-64 overflow-hidden bg-neutral-800 relative">
                  <img 
                    src={event.flyer_url || "/static/placeholder.jpg"} 
                    className="h-full w-full object-cover opacity-80 group-hover:opacity-100 group-hover:scale-110 transition-all duration-1000" 
                    onError={(e) => e.target.src = "https://via.placeholder.com/600x400/171717/333?text=TicketPro"}
                  />
                  <div className="absolute top-6 left-6 bg-indigo-600 px-4 py-1 rounded-full text-[10px] font-black tracking-widest uppercase">
                    {event.category}
                  </div>
                </div>
                <div className="p-8">
                  <p className="text-indigo-400 text-[10px] font-black uppercase tracking-widest mb-2">{event.date_text}</p>
                  <h3 className="text-2xl font-black mb-4 leading-tight group-hover:text-indigo-400 transition-colors">{event.title}</h3>
                  <div className="flex items-center gap-2 text-neutral-500 text-sm font-bold">
                    <MapPin className="w-4 h-4" /> {event.city}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Detalle del Evento */}
      {view === 'detail' && selectedEvent && (
        <div className="max-w-6xl mx-auto px-6 py-12 animate-in slide-in-from-right duration-500">
          <button onClick={() => setView('list')} className="flex items-center gap-2 text-neutral-500 hover:text-white mb-12 font-black text-xs uppercase tracking-widest">
            <ChevronLeft className="w-5 h-5" /> Volver
          </button>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-16">
            <img src={selectedEvent.flyer_url} className="rounded-[3rem] shadow-2xl aspect-[3/4] object-cover" onError={(e) => e.target.src = "https://via.placeholder.com/600x400/171717/333"} />
            <div>
              <span className="text-indigo-500 font-black tracking-widest uppercase text-xs mb-4 block">{selectedEvent.category}</span>
              <h2 className="text-6xl font-black mb-8 leading-none tracking-tighter uppercase italic">{selectedEvent.title}</h2>
              <p className="text-neutral-400 leading-relaxed text-lg mb-12">{selectedEvent.description}</p>
              
              <div className="space-y-4 bg-neutral-900/50 p-8 rounded-[2.5rem] border border-indigo-500/10">
                <p className="text-xs font-black uppercase text-indigo-400 mb-6 tracking-widest">Elegí tu entrada</p>
                {selectedEvent.tickets?.map(ticket => (
                  <div key={ticket.id} className="bg-black/40 border border-white/5 p-6 rounded-3xl flex justify-between items-center hover:border-indigo-500/30 transition-all">
                    <div>
                      <p className="font-black text-xl">{ticket.name}</p>
                      <p className="text-[10px] text-neutral-500 font-bold uppercase">Disponibles: {ticket.stock_total - ticket.stock_sold}</p>
                    </div>
                    <button 
                      onClick={() => handlePurchase(ticket.id)}
                      disabled={isProcessing}
                      className="bg-white text-black h-14 px-8 rounded-2xl font-black hover:bg-indigo-500 hover:text-white transition-all active:scale-95 disabled:opacity-50 flex items-center gap-3"
                    >
                      {isProcessing ? <Loader2 className="w-5 h-5 animate-spin" /> : <CreditCard className="w-5 h-5" />}
                      ${ticket.price_cents / 100}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Éxito de Compra */}
      {view === 'success' && orderResult && (
        <div className="min-h-[70vh] flex flex-col items-center justify-center p-6 animate-in zoom-in-95 duration-700">
          <div className="w-24 h-24 bg-indigo-600 rounded-[2rem] flex items-center justify-center mb-8 shadow-2xl">
            <CheckCircle2 className="w-12 h-12 text-white" />
          </div>
          <h2 className="text-7xl font-black mb-6 uppercase tracking-tighter italic">¡Éxito!</h2>
          <p className="text-neutral-400 text-xl max-w-md text-center mb-16 leading-relaxed">
            Tu entrada ha sido confirmada. Revisá tu email <span className="text-indigo-400 underline">{user?.email}</span>.
          </p>
          <button onClick={() => setView('list')} className="bg-white text-black px-12 py-5 rounded-2xl font-black shadow-xl">
            Volver al inicio
          </button>
        </div>
      )}
    </div>
  );
};

export default App;