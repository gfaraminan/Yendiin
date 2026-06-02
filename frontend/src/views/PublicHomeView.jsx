import { useEffect, useRef, useState } from "react";
import { Calendar, ChevronDown, MapPin, Search } from "lucide-react";
import FeaturedCarousel from "../components/FeaturedCarousel";
import { FALLBACK_FLYER } from "../app/constants";
import { flyerSrc, priceLabelForEvent } from "../app/helpers";
import { HOME_BRAND_THEME } from "../app/homeTheme";


function FilterDropdown({ label, value, onChange, allLabel, options }) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);
  const items = [{ value: "all", label: allLabel }, ...options.map((option) => ({ value: option, label: option }))];
  const selectedLabel = items.find((item) => item.value === value)?.label || allLabel;

  useEffect(() => {
    if (!isOpen) return undefined;

    const closeOnOutsideClick = (event) => {
      if (!dropdownRef.current?.contains(event.target)) setIsOpen(false);
    };

    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [isOpen]);

  return (
    <div ref={dropdownRef} className="relative text-[10px] font-black uppercase tracking-widest text-white/65">
      <div>{label}</div>
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        className={`mt-2 flex w-full items-center justify-between gap-3 rounded-xl border ${HOME_BRAND_THEME.inputBorder} bg-[#f4fff9] px-4 py-3 text-left text-[12px] font-black normal-case tracking-normal text-[#10231f] shadow-[inset_0_0_0_1px_rgba(52,211,153,0.18)] transition focus:outline-none focus:ring-4 focus:ring-emerald-300/25`}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <span className="truncate">{selectedLabel}</span>
        <ChevronDown size={16} className={`shrink-0 text-emerald-700 transition-transform ${isOpen ? "rotate-180" : ""}`} />
      </button>

      {isOpen && (
        <div className="absolute left-0 right-0 z-40 mt-2 overflow-hidden rounded-xl border border-emerald-300/80 bg-[#eafff4] text-[#10231f] shadow-[0_18px_40px_rgba(6,78,59,0.32)]" role="listbox">
          {items.map((item) => {
            const selected = item.value === value;
            return (
              <button
                key={item.value}
                type="button"
                onClick={() => {
                  onChange(item.value);
                  setIsOpen(false);
                }}
                className={`block w-full px-4 py-3 text-left text-[12px] font-black normal-case tracking-normal transition ${
                  selected ? "bg-emerald-300/70 text-[#09231c]" : "hover:bg-emerald-200/80"
                }`}
                role="option"
                aria-selected={selected}
              >
                {item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function PublicHomeView({
  featureFlags,
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
  soldOutRibbon,
  formatMoney,
}) {
  const soldOutMarker = typeof soldOutRibbon === "function" ? soldOutRibbon : null;

  return (
    <div className="pt-0 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
      {featureFlags.featuredCarousel && (
        <div className="mt-0">
          <div className="text-[10px] font-black uppercase tracking-widest text-white/65">Destacados</div>
          <div className={`text-2xl font-black uppercase mt-2 ${HOME_BRAND_THEME.accentText}`}>Eventos recomendados</div>
          <div className="mt-4">
            <FeaturedCarousel events={filteredEvents} formatMoneyFn={formatMoney} onOpen={(ev) => onOpenEvent(ev.slug)} />
          </div>
        </div>
      )}

      <div className={`mt-4 rounded-3xl border ${HOME_BRAND_THEME.inputBorder} p-4 sm:p-5 overflow-visible shadow-[0_18px_40px_rgba(148,163,184,0.28)] ${HOME_BRAND_THEME.inputBg}`}>
        <div className="flex flex-col lg:flex-row gap-3 lg:items-center">
          <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <FilterDropdown
              label="Ciudad"
              value={filterCity}
              onChange={setFilterCity}
              allLabel="Todas"
              options={cities}
            />

            <FilterDropdown
              label="Tipo"
              value={filterType}
              onChange={setFilterType}
              allLabel="Todos"
              options={types}
            />
          </div>

          <div className="flex-1">
            <div className="text-[10px] font-black uppercase tracking-widest text-white/65">Búsqueda</div>
            <div className={`mt-2 flex items-center gap-3 rounded-xl ${HOME_BRAND_THEME.inputBg} border ${HOME_BRAND_THEME.inputBorder} px-4 py-3`}>
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
                  className={`px-3 py-2 rounded-full ${HOME_BRAND_THEME.accentSoftBg} hover:bg-emerald-400/25 border ${HOME_BRAND_THEME.accentBorder} text-[9px] font-black uppercase tracking-widest`}
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

      <div className="h-10 md:h-12" aria-hidden="true" />

      <div className="md:hidden space-y-5">
        {filteredEvents.map((ev) => (
          <button
            key={ev.id}
            onClick={() => onOpenEvent(ev.slug)}
            className={`w-full text-left bg-white/14 backdrop-blur-xl rounded-3xl p-3 overflow-hidden border border-white/25 shadow-[0_16px_35px_rgba(15,23,42,0.32)] ${
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
              {isEventSoldOut(ev) && soldOutMarker ? soldOutMarker() : null}
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
            className={`text-left overflow-hidden rounded-3xl bg-white/14 backdrop-blur-xl border border-white/25 hover:border-[#FF9AD8]/65 hover:-translate-y-1 transition-all duration-300 shadow-[0_16px_35px_rgba(15,23,42,0.32)] ${
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
              {isEventSoldOut(ev) && soldOutMarker ? soldOutMarker() : null}
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
