import { Calendar, MapPin, Search } from "lucide-react";
import FeaturedCarousel from "../components/FeaturedCarousel";
import { FALLBACK_FLYER } from "../app/constants";
import { flyerSrc, priceLabelForEvent } from "../app/helpers";
import { HOME_BRAND_THEME } from "../app/homeTheme";

export default function PublicHomeView({
  brandConfig,
  featureFlags,
  UI,
  filteredEvents,
  totalEvents,
  cities,
  types,
  filterCity,
  setFilterCity,
  filterType,
  setFilterType,
  searchQuery,
  setSearchQuery,
  onOpenEvent,
  isEventSoldOut,
  SoldOutRibbon,
  formatMoney,
}) {
  return (
    <div className="pt-0 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
      <section className={`relative overflow-hidden rounded-none border border-white/25 bg-gradient-to-br ${HOME_BRAND_THEME.bgBase} px-6 sm:px-10 py-10 mb-10`}>
        <div className={`absolute -top-20 -right-10 w-64 h-64 rounded-none ${HOME_BRAND_THEME.glowSecondary} blur-3xl pointer-events-none`} />
        <div className={`absolute -bottom-24 -left-10 w-64 h-64 rounded-none ${HOME_BRAND_THEME.glowPrimary} blur-3xl pointer-events-none`} />
        <div className="relative flex flex-col md:flex-row justify-between items-start md:items-center gap-8">
          <div className="max-w-3xl">
            <div className="inline-flex items-center rounded-none px-3 py-1 text-[10px] font-black uppercase tracking-[0.2em] bg-white/25 text-white/90 border border-white/35 shadow-[0_10px_30px_rgba(148,163,184,0.25)] mb-4">
              Eventos activos
            </div>
            <div className="mb-5 inline-flex items-center rounded-none border border-white/15 bg-white/20 p-3">
              <img src="/logo-yendiin-casinos.svg" alt="Yendiin & Casinos" className="h-16 w-auto" loading="lazy" />
            </div>
            <h1 className="text-4xl sm:text-5xl font-black uppercase italic tracking-tight leading-[0.95]">
              {brandConfig.heroTitle}
            </h1>
            <p className="text-[11px] sm:text-[12px] font-black uppercase tracking-widest text-[#D6DEEF] mt-4">
              {brandConfig.heroSubtitle}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3 min-w-[220px]">
            <div className="rounded-none bg-white/15 border border-white/30 backdrop-blur-xl p-3">
              <div className="text-[9px] uppercase font-black tracking-widest text-white/70">Disponibles</div>
              <div className="text-2xl font-black mt-1">{filteredEvents.length}</div>
            </div>
            <div className="rounded-none bg-white/15 border border-white/30 backdrop-blur-xl p-3">
              <div className="text-[9px] uppercase font-black tracking-widest text-white/70">Ciudades</div>
              <div className="text-2xl font-black mt-1">{cities.length}</div>
            </div>
          </div>
        </div>
      </section>

      {featureFlags.featuredCarousel && (
        <div className="mt-10">
          <div className="text-[10px] font-black uppercase tracking-widest text-white/65">Destacados</div>
          <div className={`text-2xl font-black uppercase mt-2 ${HOME_BRAND_THEME.accentText}`}>Eventos recomendados</div>
          <div className="mt-4">
            <FeaturedCarousel events={filteredEvents} formatMoneyFn={formatMoney} onOpen={(ev) => onOpenEvent(ev.slug)} />
          </div>
        </div>
      )}

      <div className={`mt-6 rounded-none border ${HOME_BRAND_THEME.inputBorder} p-4 sm:p-5 overflow-x-hidden shadow-[0_18px_40px_rgba(148,163,184,0.28)] ${HOME_BRAND_THEME.inputBg}`}>
        <div className="flex flex-col lg:flex-row gap-3 lg:items-center">
          <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="text-[10px] font-black uppercase tracking-widest text-white/65">
              Ciudad
              <select value={filterCity} onChange={(e) => setFilterCity(e.target.value)} className={`mt-2 w-full rounded-none ${HOME_BRAND_THEME.inputBg} border ${HOME_BRAND_THEME.inputBorder} px-4 py-3 text-white text-[12px] font-black`}>
                <option value="all">Todas</option>
                {cities.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>

            <label className="text-[10px] font-black uppercase tracking-widest text-white/65">
              Tipo
              <select value={filterType} onChange={(e) => setFilterType(e.target.value)} className={`mt-2 w-full rounded-none ${HOME_BRAND_THEME.inputBg} border ${HOME_BRAND_THEME.inputBorder} px-4 py-3 text-white text-[12px] font-black`}>
                <option value="all">Todos</option>
                {types.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
          </div>

          <div className="flex-1">
            <div className="text-[10px] font-black uppercase tracking-widest text-white/65">Búsqueda</div>
            <div className={`mt-2 flex items-center gap-3 rounded-none ${HOME_BRAND_THEME.inputBg} border ${HOME_BRAND_THEME.inputBorder} px-4 py-3`}>
              <Search size={18} className="text-white/60" />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Buscar por evento, venue, ciudad…"
                className="w-full bg-transparent outline-none text-white placeholder:text-white/55 font-black text-[12px]"
              />
              {(filterCity !== "all" || filterType !== "all" || (searchQuery || "").trim()) && (
                <button
                  onClick={() => {
                    setFilterCity("all");
                    setFilterType("all");
                    setSearchQuery("");
                  }}
                  className={`px-3 py-2 rounded-none ${HOME_BRAND_THEME.accentSoftBg} hover:bg-[#FF9AD8]/30 border ${HOME_BRAND_THEME.accentBorder} text-[9px] font-black uppercase tracking-widest`}
                >
                  Limpiar
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="mt-3 text-[10px] text-white/50 font-black uppercase tracking-widest">
          Mostrando {filteredEvents.length} de {totalEvents}
        </div>
      </div>

      <div className="md:hidden mt-8 space-y-4">
        {filteredEvents.map((ev) => (
          <button
            key={ev.id}
            onClick={() => onOpenEvent(ev.slug)}
            className={`w-full text-left bg-white/14 backdrop-blur-xl rounded-none p-3 overflow-hidden border border-white/25 shadow-[0_16px_35px_rgba(15,23,42,0.32)] ${
              isEventSoldOut(ev) ? "border border-rose-400/70 shadow-[0_0_0_1px_rgba(251,113,133,0.35),0_0_24px_rgba(244,63,94,0.55)]" : ""
            }`}
          >
            <div className="relative h-80 rounded-none overflow-hidden bg-black">
              <img
                src={flyerSrc(ev)}
                alt={ev.title}
                onError={(e) => { e.currentTarget.onerror = null; e.currentTarget.src = FALLBACK_FLYER; }}
                className="w-full h-full object-contain object-top"
              />
              {isEventSoldOut(ev) && <SoldOutRibbon />}
              <div className="absolute inset-0 bg-gradient-to-t from-black via-black/65 to-transparent" />
              <div className="absolute inset-x-0 bottom-0 p-5 min-w-0 space-y-2">
                <div className="text-[10px] text-neutral-200 flex items-center gap-2"><Calendar size={14} /> {ev.date_text}</div>
                <div className="text-[10px] font-black uppercase tracking-widest text-white/70 flex items-center gap-2 flex-wrap"><MapPin size={13} /> {ev.city} · {ev.venue}</div>
                <div className="text-2xl font-black uppercase italic leading-tight break-words">{ev.title}</div>
                <div className="text-xl font-black text-[#FF4FB7] italic">{priceLabelForEvent(ev, formatMoney)}</div>
              </div>
            </div>
          </button>
        ))}
      </div>

      <div className="hidden md:grid grid-cols-2 xl:grid-cols-3 gap-8">
        {filteredEvents.map((ev) => (
          <button
            key={ev.id}
            onClick={() => onOpenEvent(ev.slug)}
            className={`text-left overflow-hidden rounded-none bg-white/14 backdrop-blur-xl border border-white/25 hover:border-[#FF9AD8]/65 hover:-translate-y-1 transition-all duration-300 shadow-[0_16px_35px_rgba(15,23,42,0.32)] ${
              isEventSoldOut(ev) ? "border border-rose-400/70 shadow-[0_0_0_1px_rgba(251,113,133,0.35),0_0_34px_rgba(244,63,94,0.5)]" : ""
            }`}
          >
            <div className="relative h-[23rem] bg-black">
              <img
                src={flyerSrc(ev)}
                alt={ev.title}
                onError={(e) => { e.currentTarget.onerror = null; e.currentTarget.src = FALLBACK_FLYER; }}
                className="w-full h-full object-contain object-top opacity-95"
              />
              {isEventSoldOut(ev) && <SoldOutRibbon />}
              <div className="absolute inset-0 bg-gradient-to-t from-black via-black/65 to-transparent" />
              <div className="absolute bottom-0 left-0 p-6 space-y-2 w-full">
                <div className="text-[11px] text-neutral-200 flex items-center gap-2"><Calendar size={14} /> {ev.date_text}</div>
                <div className="text-[10px] font-black uppercase tracking-widest text-white/70 flex items-center gap-2 flex-wrap"><MapPin size={13} /> {ev.city} · {ev.venue}</div>
                <div className="text-3xl font-black uppercase italic leading-tight line-clamp-2">{ev.title}</div>
                <div className="text-2xl font-black text-[#FF4FB7] italic">{priceLabelForEvent(ev, formatMoney)}</div>
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
