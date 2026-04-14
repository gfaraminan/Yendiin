import { Download, QrCode, Share2 } from "lucide-react";

export default function PurchaseSuccessView({
  purchaseData,
  UI,
  successProcessing,
  successTries,
  me,
  selectedEvent,
  onOpenMyTickets,
  onBackToPublic,
}) {
  if (!purchaseData) return null;

  return (
    <div className="pt-0 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
      <div className="max-w-3xl mx-auto">
        <div className={`p-10 rounded-[2.5rem] ${UI.card} text-center`}>
          <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500">Compra confirmada</div>
          <div className="text-3xl font-black uppercase italic mt-2 mb-4">
            {purchaseData?.tickets?.length ? "LISTO... TUS TICKETS ESTÁN CONFIRMADOS" : "ESTAMOS PROCESANDO TU COMPRA"}
          </div>
          <div className="text-[12px] text-neutral-400 leading-relaxed mb-8">
            {purchaseData?.tickets?.length
              ? "Tus tickets ya están listos: podés descargarlos, compartirlos y además te los enviamos por mail."
              : "Mercado Pago confirmó la operación. Estamos esperando la emisión final de tus tickets."}
          </div>
          <div className="text-[12px] text-neutral-300 leading-relaxed mb-8">
            {successProcessing ? `Procesando tu compra... intento ${successTries}/12` : ""}
          </div>

          <div className="p-6 rounded-3xl bg-white/5 border border-white/10 flex flex-col md:flex-row items-center gap-6 mb-8">
            <div className="w-24 h-24 rounded-3xl bg-white/5 border border-white/10 flex items-center justify-center">
              <QrCode size={42} className="text-indigo-300" />
            </div>

            <div className="flex-1 space-y-4 text-center md:text-left">
              <div>
                <div className="text-[9px] font-black text-neutral-500 uppercase tracking-widest">Titular de Entrada</div>
                <div className="text-xl font-black uppercase">{purchaseData?.user?.fullName || purchaseData?.tickets?.[0]?.buyer_name || me?.fullName || "Titular"}</div>
              </div>
              <div>
                <div className="text-[9px] font-black text-neutral-500 uppercase tracking-widest">Tickets x{purchaseData?.quantity || purchaseData?.tickets?.length || 1}</div>
                <div className="text-xl font-black text-indigo-400 italic uppercase leading-none">
                  {(() => {
                    const candidates = [
                      purchaseData?.event?.title,
                      purchaseData?.event?.name,
                      purchaseData?.ticket?.event_title,
                      purchaseData?.ticket?.event_slug,
                      purchaseData?.tickets?.[0]?.event_title,
                      purchaseData?.tickets?.[0]?.event_slug,
                      selectedEvent?.title,
                      selectedEvent?.name,
                    ];
                    const eventName = candidates.find((v) => String(v || "").trim().length > 0);
                    return eventName || "Evento";
                  })()}
                </div>
              </div>
            </div>
          </div>

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
                    <div className="text-[10px] font-black uppercase tracking-widest text-neutral-400">Ticket #{idx + 1}</div>
                    <div className="text-[12px] font-mono text-white truncate">{t.ticket_id}</div>
                    <div className="text-[10px] text-neutral-500 truncate">{t.qr_payload || t.ticket_id}</div>
                  </div>
                  <button onClick={() => navigator.clipboard?.writeText(t.qr_payload || t.ticket_id || "")} className="px-3 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest">
                    Copiar
                  </button>
                </div>
              ))}
            </div>
            {!purchaseData?.tickets?.length && <div className="text-[11px] text-neutral-500 mt-3">Procesando tu compra... estamos esperando la emisión de tickets.</div>}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <button
              onClick={() => {
                const orderId = String(purchaseData?.order_id || "").trim();
                if (!orderId) return alert("No hay orden para descargar todavía.");
                window.open(`/api/tickets/orders/${encodeURIComponent(orderId)}/pdf`, "_blank", "noopener,noreferrer");
              }}
              className="flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 p-5 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all"
            >
              <Download size={16} /> Descargar PDF
            </button>
            <button
              onClick={async () => {
                const orderId = String(purchaseData?.order_id || "").trim();
                if (!orderId) return alert("No hay orden para compartir todavía.");
                const url = `${window.location.origin}/api/tickets/orders/${encodeURIComponent(orderId)}/pdf`;
                try {
                  if (navigator.share) await navigator.share({ title: "Mis tickets", text: "Te comparto mis tickets (PDF).", url });
                  else {
                    await navigator.clipboard?.writeText(url);
                    alert("Link copiado al portapapeles.");
                  }
                } catch (_) {}
              }}
              className="flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 p-5 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all"
            >
              <Share2 size={16} /> Compartir
            </button>
          </div>

          <div className="mt-4">
            <button onClick={onOpenMyTickets} className="w-full flex items-center justify-center gap-2 bg-white/5 hover:bg-white/10 p-4 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all">
              Ver también en Mis Tickets
            </button>
          </div>

          <button onClick={onBackToPublic} className="w-full text-[10px] font-black text-indigo-400 uppercase tracking-[0.2em] hover:text-white transition-colors mt-8">
            Volver a la cartelera
          </button>
        </div>
      </div>
    </div>
  );
}
