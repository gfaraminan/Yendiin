import React, { useEffect, useState } from "react";
import { Calendar } from "lucide-react";
import { FALLBACK_FLYER, UI } from "../app/constants";
import { flyerSrc, priceLabelForEvent } from "../app/helpers";

export default function FeaturedCarousel({ events = [], onOpen, formatMoneyFn }) {
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

  const [wrapW, setWrapW] = useState(0);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWrapW(el.clientWidth || 0));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);


  useEffect(() => {
    if (items.length <= 1) return;
    const timer = setInterval(() => {
      const scroller = scrollerRef.current;
      if (!scroller) return;
      const first = scroller.querySelector("[data-card='1']");
      const cardW = first ? first.getBoundingClientRect().width : 0;
      const style = window.getComputedStyle(scroller);
      const gap = parseFloat(style.columnGap || style.gap || "0") || 0;
      const next = (active + 1) % items.length;
      scroller.scrollTo({ left: next * (cardW + gap), behavior: "smooth" });
    }, 4500);
    return () => clearInterval(timer);
  }, [active, items.length]);

  const side = 16;
  const cardWidth = wrapW ? Math.max(260, wrapW - side * 2) : 320;

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
            <div className="p-4">
              <div className="text-base font-black text-indigo-300 italic">
                {priceLabelForEvent(ev, formatMoneyFn)}
              </div>
            </div>
          </button>
        ))}
      </div>

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
