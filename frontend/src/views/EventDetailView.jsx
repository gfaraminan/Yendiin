import { Calendar, ChevronLeft, CreditCard, Loader2, MapPin, ShoppingCart, Ticket, Wallet } from "lucide-react";
import { FALLBACK_FLYER } from "../app/constants";
import { normalizeAssetUrl } from "../app/helpers";

export default function EventDetailView({
  selectedEvent,
  UI,
  isEventSoldOut,
  SoldOutRibbon,
  buildUberLink,
  buildEventGoogleMapsLink,
  linkifyPlainText,
  selectedTicket,
  setSelectedTicket,
  formatMoney,
  checkoutForm,
  setCheckoutForm,
  checkoutTouched,
  setCheckoutTouched,
  checkoutError,
  selectedSellerCode,
  quantity,
  setQuantity,
  checkoutServicePct,
  checkoutServicePctLabel,
  loading,
  checkoutBlockReason,
  handleCheckout,
  legalConfig,
  onBack,
}) {
  const Ribbon = SoldOutRibbon || (({ className = "" }) => (
    <div className={`pointer-events-none absolute inset-x-0 top-4 z-20 ${className}`}>
      <div className="w-full py-2.5 bg-gradient-to-r from-rose-600/95 via-red-500/95 to-rose-600/95 border-y border-rose-200/70">
        <div className="text-center">
          <span className="text-[12px] font-black uppercase tracking-[0.32em] text-white">SOLD OUT</span>
        </div>
      </div>
    </div>
  ));

  if (!selectedEvent) {
    return (
      <div className="pt-0 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
        <button onClick={onBack} className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all mb-8">
          <ChevronLeft size={16} /> Volver
        </button>
        <div className={`rounded-[2.5rem] ${UI.card} p-10 text-center`}>
          <div className="inline-flex items-center gap-3 justify-center text-neutral-300">
            <Loader2 className="animate-spin" size={18} />
            <span className="text-[11px] font-black uppercase tracking-widest">Cargando evento…</span>
          </div>
          <div className="text-[12px] text-neutral-400 mt-4">Si esto tarda demasiado, volvé a la cartelera y reintentá.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="pt-0 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
      <button onClick={onBack} className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/15 text-[10px] font-black uppercase tracking-widest transition-all mb-8">
        <ChevronLeft size={16} /> Volver
      </button>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-10">
        <div className={`overflow-hidden rounded-[2.5rem] ${UI.card} border border-white/10 lg:col-span-2`}>
          <div className="relative h-[30rem] md:h-[38rem] bg-black">
            <img src={normalizeAssetUrl(selectedEvent.flyer_url) || FALLBACK_FLYER} alt={selectedEvent.title} className="w-full h-full object-contain object-top opacity-95" />
            {isEventSoldOut(selectedEvent) && <Ribbon className="top-5" />}
            <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/25 to-transparent" />
            <div className="absolute bottom-0 left-0 p-8 space-y-1">
              <div className="text-[11px] text-neutral-200 flex items-center gap-2"><Calendar size={14} /> {selectedEvent.date_text}</div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {(() => {
                  const uberLink = buildUberLink(selectedEvent);
                  const mapsLink = buildEventGoogleMapsLink(selectedEvent);
                  return (
                    <>
                      {uberLink && (
                        <a href={uberLink} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-4 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest">
                          <MapPin size={14} /> Cotizar en Uber
                        </a>
                      )}
                      {mapsLink && (
                        <a href={mapsLink} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-4 py-2 rounded-2xl bg-indigo-500/15 hover:bg-indigo-500/25 border border-indigo-400/40 text-[10px] font-black uppercase tracking-widest text-indigo-100">
                          <MapPin size={14} /> Abrir en Google Maps
                        </a>
                      )}
                    </>
                  );
                })()}
              </div>
            </div>
          </div>

          <div className="p-8">
            <div className="mb-8">
              <div className="text-[10px] font-black uppercase tracking-widest text-neutral-400 flex items-center gap-2">
                <MapPin size={13} /> {selectedEvent.city} · {selectedEvent.venue}
                {isEventSoldOut(selectedEvent) && <span className="px-2 py-0.5 rounded-full bg-rose-500/20 border border-rose-500/40 text-rose-200">SOLD OUT</span>}
              </div>
              <div className="text-4xl font-black uppercase italic mt-2 leading-tight">{selectedEvent.title}</div>
            </div>

            {(selectedEvent.description || selectedEvent.address) && (
              <div className="mb-8">
                {selectedEvent.description && <div className="text-[12px] text-neutral-300 leading-relaxed whitespace-pre-wrap break-words">{linkifyPlainText(selectedEvent.description)}</div>}
                {selectedEvent.address && <div className="text-[11px] text-neutral-500 mt-3 flex items-center gap-2"><MapPin size={14} /> {selectedEvent.address}</div>}
              </div>
            )}
            <div className="flex items-center gap-3 mb-6">
              <div className="p-3 rounded-2xl bg-indigo-600/20 border border-indigo-600/30"><Ticket className="text-indigo-300" size={18} /></div>
              <div>
                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Elegí tu ticket</div>
                <div className="text-xl font-black uppercase italic">Tipos disponibles</div>
              </div>
            </div>

            <div className="space-y-3">
              {(selectedEvent.items || []).map((it) => (
                <button
                  key={it.id}
                  onClick={() => setSelectedTicket(it)}
                  className={`w-full p-5 rounded-3xl flex items-center justify-between gap-4 transition-all border ${selectedTicket?.id === it.id ? "bg-indigo-600/10 border-indigo-600/30" : "bg-white/5 border-white/10 hover:bg-white/10"}`}
                >
                  <div className="text-left">
                    <div className="text-[10px] font-black uppercase tracking-widest text-neutral-500">Ticket</div>
                    <div className="text-lg font-black uppercase">{it.name}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Precio</div>
                    <div className="text-xl font-black text-indigo-400 italic">{formatMoney(it.price)}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className={`p-8 rounded-[2.5rem] ${UI.card} border border-white/10 h-fit sticky top-36`}>
          <div className="flex items-center gap-3 mb-6">
            <div className="p-3 rounded-2xl bg-indigo-600/20 border border-indigo-600/30"><CreditCard className="text-indigo-300" size={18} /></div>
            <div>
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Checkout</div>
              <div className="text-xl font-black uppercase italic">Datos del titular</div>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Nombre y Apellido</div>
              <input value={checkoutForm.fullName} onChange={(e) => setCheckoutForm({ ...checkoutForm, fullName: e.target.value })} placeholder="Nombre y Apellido" autoComplete="name" onBlur={() => setCheckoutTouched({ ...checkoutTouched, fullName: true })} className={`w-full px-4 py-3 rounded-2xl bg-white/5 border text-[12px] font-bold ${checkoutError("fullName") ? "border-red-500/70" : "border-white/10"}`} />
              {checkoutError("fullName") && <div className="mt-1 text-[10px] font-bold text-red-400">{checkoutError("fullName")}</div>}
            </div>
            <div>
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">DNI</div>
              <input value={checkoutForm.dni} onChange={(e) => setCheckoutForm({ ...checkoutForm, dni: String(e.target.value || "").replace(/\D/g, "").slice(0, 8) })} onBlur={() => setCheckoutTouched({ ...checkoutTouched, dni: true })} placeholder="DNI" inputMode="numeric" minLength={7} maxLength={8} autoComplete="off" className={`w-full px-4 py-3 rounded-2xl bg-white/5 border text-[12px] font-bold ${checkoutError("dni") ? "border-red-500/70" : "border-white/10"}`} />
              {checkoutError("dni") && <div className="mt-1 text-[10px] font-bold text-red-400">{checkoutError("dni")}</div>}
            </div>
            <div>
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Celular de contacto</div>
              <input value={checkoutForm.phone} onChange={(e) => setCheckoutForm({ ...checkoutForm, phone: String(e.target.value || "").replace(/\D/g, "").slice(0, 15) })} onBlur={() => setCheckoutTouched({ ...checkoutTouched, phone: true })} placeholder="Ej: 2615551234" inputMode="numeric" autoComplete="tel" className={`w-full px-4 py-3 rounded-2xl bg-white/5 border text-[12px] font-bold ${checkoutError("phone") ? "border-red-500/70" : "border-white/10"}`} />
              {checkoutError("phone") && <div className="mt-1 text-[10px] font-bold text-red-400">{checkoutError("phone")}</div>}
            </div>
            <div>
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Domicilio completo</div>
              <input value={checkoutForm.address} onChange={(e) => setCheckoutForm({ ...checkoutForm, address: e.target.value })} placeholder="Ej: San Martín 1234, Depto B" autoComplete="street-address" onBlur={() => setCheckoutTouched({ ...checkoutTouched, address: true })} className={`w-full px-4 py-3 rounded-2xl bg-white/5 border text-[12px] font-bold ${checkoutError("address") ? "border-red-500/70" : "border-white/10"}`} />
              {checkoutError("address") && <div className="mt-1 text-[10px] font-bold text-red-400">{checkoutError("address")}</div>}
            </div>
            <div>
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Provincia</div>
              <input value={checkoutForm.province} onChange={(e) => setCheckoutForm({ ...checkoutForm, province: e.target.value })} placeholder="Ej: Mendoza" autoComplete="address-level1" onBlur={() => setCheckoutTouched({ ...checkoutTouched, province: true })} className={`w-full px-4 py-3 rounded-2xl bg-white/5 border text-[12px] font-bold ${checkoutError("province") ? "border-red-500/70" : "border-white/10"}`} />
              {checkoutError("province") && <div className="mt-1 text-[10px] font-bold text-red-400">{checkoutError("province")}</div>}
            </div>
            <div>
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Código postal</div>
              <input value={checkoutForm.postalCode} onChange={(e) => setCheckoutForm({ ...checkoutForm, postalCode: e.target.value })} placeholder="Ej: 5500" autoComplete="postal-code" onBlur={() => setCheckoutTouched({ ...checkoutTouched, postalCode: true })} className={`w-full px-4 py-3 rounded-2xl bg-white/5 border text-[12px] font-bold ${checkoutError("postalCode") ? "border-red-500/70" : "border-white/10"}`} />
              {checkoutError("postalCode") && <div className="mt-1 text-[10px] font-bold text-red-400">{checkoutError("postalCode")}</div>}
            </div>
            <div>
              <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Fecha de nacimiento</div>
              <input type="text" value={checkoutForm.birthDate} onChange={(e) => setCheckoutForm({ ...checkoutForm, birthDate: e.target.value })} placeholder="dd/mm/aaaa" inputMode="numeric" onBlur={() => setCheckoutTouched({ ...checkoutTouched, birthDate: true })} className={`w-full px-4 py-3 rounded-2xl bg-white/5 border text-[12px] font-bold ${checkoutError("birthDate") ? "border-red-500/70" : "border-white/10"}`} />
              {checkoutError("birthDate") && <div className="mt-1 text-[10px] font-bold text-red-400">{checkoutError("birthDate")}</div>}
            </div>

            {selectedSellerCode && <div className="rounded-2xl border border-indigo-500/30 bg-indigo-500/10 px-4 py-3 text-[11px] text-indigo-200">Compra atribuida a vendedor: <span className="font-black">{selectedSellerCode}</span></div>}

            <div className="flex items-center justify-between gap-4 pt-2">
              <div>
                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Cantidad</div>
                <div className="flex items-center gap-2 mt-2">
                  <button onClick={() => setQuantity((q) => Math.max(1, q - 1))} disabled={quantity <= 1} className="w-10 h-10 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 flex items-center justify-center text-white disabled:opacity-40 disabled:cursor-not-allowed" aria-label="Restar"><span className="text-lg font-black leading-none">−</span></button>
                  <div className="w-10 text-center text-lg font-black">{quantity}</div>
                  <button onClick={() => setQuantity((q) => q + 1)} className="w-10 h-10 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 flex items-center justify-center text-white" aria-label="Sumar"><span className="text-lg font-black leading-none">+</span></button>
                </div>
              </div>
              <div className="text-right">
                <div className="text-[11px] text-neutral-400 space-y-1">
                  <div className="flex items-center justify-between gap-6"><span className="font-bold">Subtotal</span><span className="font-black">{formatMoney((selectedTicket?.price || 0) * quantity)}</span></div>
                  <div className="flex items-center justify-between gap-6"><span className="font-bold">Service charge ({checkoutServicePctLabel})</span><span className="font-black">{formatMoney(((selectedTicket?.price || 0) * quantity) * checkoutServicePct)}</span></div>
                </div>
                <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mt-3">Total a pagar</div>
                <div className="text-3xl font-black text-indigo-400 italic mt-1">{formatMoney(((selectedTicket?.price || 0) * quantity) * (1 + checkoutServicePct))}</div>
              </div>
            </div>

            <div className="mt-6 p-4 rounded-2xl bg-white/5 border border-white/10">
              <label className="flex items-start gap-3 cursor-pointer">
                <input type="checkbox" className="mt-1" checked={checkoutForm.acceptTerms} onChange={(e) => { setCheckoutTouched({ ...checkoutTouched, acceptTerms: true }); setCheckoutForm({ ...checkoutForm, acceptTerms: e.target.checked }); }} />
                <div className="text-[11px] text-neutral-300 leading-relaxed">
                  Acepto los{" "}
                  <a href={legalConfig.termsUrl} target="_blank" rel="noreferrer" className="text-white font-bold underline" onClick={(e) => e.stopPropagation()}>Términos y Condiciones</a>{" "}
                  y la{" "}
                  <a href={legalConfig.privacyUrl} target="_blank" rel="noreferrer" className="underline" onClick={(e) => e.stopPropagation()}>política de privacidad</a>.
                </div>
              </label>
            </div>
            {checkoutError("acceptTerms") && <div className="mt-2 text-[10px] font-bold text-red-400">{checkoutError("acceptTerms")}</div>}

            <div className="grid grid-cols-1 gap-3 mt-6">
              <button onClick={() => handleCheckout("mp")} disabled={loading || !!checkoutBlockReason} className={`w-full py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest text-white transition-all flex items-center justify-center gap-2 ${UI.button} disabled:opacity-40 disabled:cursor-not-allowed`}>
                {loading ? <Loader2 className="animate-spin" size={16} /> : <Wallet size={16} />}
                Pagar con Mercado Pago
              </button>
              {!!checkoutBlockReason && <div className="px-4 py-2 rounded-xl bg-amber-500/20 border border-amber-400/50 text-[12px] font-black text-amber-100 text-center leading-snug shadow-[0_10px_20px_rgba(245,158,11,0.22)]">{checkoutBlockReason}</div>}

              <button disabled title="Próximamente" className="w-full py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest bg-white/5 border border-white/10 flex items-center justify-center gap-2 opacity-40 cursor-not-allowed"><CreditCard size={16} /> Pagar con tarjeta (próximamente)</button>
              <button disabled className="w-full py-4 rounded-2xl font-black uppercase text-[10px] tracking-widest bg-white/5 border border-white/10 flex items-center justify-center gap-2 opacity-40 cursor-not-allowed" title="Próximamente"><ShoppingCart size={16} /> Reservar (próximamente)</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
