import { QrCode, Search } from "lucide-react";

export default function MyTicketsView({
  myAssetsLoading,
  myAssetsError,
  myAssets,
  myFilters,
  setMyFilters,
  loadMyAssets,
  normalizeAssetUrl,
  qrImgUrl,
  transferOrder,
  requestCancel,
}) {
  return (
    <div className="pt-0 pb-20 px-6 max-w-7xl mx-auto animate-in fade-in text-white">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 mb-10">
        <div>
          <h1 className="text-5xl font-black uppercase italic tracking-tight">
            Mis <span className="text-indigo-600">Tickets</span>
          </h1>
          <p className="text-[11px] text-white/60 mt-2 max-w-2xl leading-relaxed">
            Acá ves tus compras de <span className="text-white font-black">Entradas</span> y <span className="text-white font-black">Barra</span>.
            Los QR se muestran listos para validar. Para <span className="text-white font-black">arrepentimiento</span> se genera una solicitud y el productor se contactará.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => loadMyAssets()} className="px-4 sm:px-5 py-2.5 sm:py-3 rounded-2xl text-[9px] sm:text-[10px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 text-white">
            Actualizar
          </button>
        </div>
      </div>

      <div className="p-5 rounded-3xl bg-white/5 border border-white/10 mb-10">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div>
            <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Tipo</div>
            <select value={myFilters.kind} onChange={(e) => setMyFilters((s) => ({ ...s, kind: e.target.value }))} className="w-full bg-black/40 border border-white/10 rounded-2xl px-4 py-3 text-[11px] text-white outline-none">
              <option value="all">Todos</option>
              <option value="entradas">Entradas</option>
              <option value="barra">Barra</option>
            </select>
          </div>
          <div>
            <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Estado</div>
            <select value={myFilters.status} onChange={(e) => setMyFilters((s) => ({ ...s, status: e.target.value }))} className="w-full bg-black/40 border border-white/10 rounded-2xl px-4 py-3 text-[11px] text-white outline-none">
              <option value="all">Todos</option>
              <option value="valid">Por usar</option>
              <option value="used">Usados</option>
              <option value="cancel_requested">Arrepentimiento solicitado</option>
              <option value="cancelled">Cancelados</option>
            </select>
          </div>
          <div className="md:col-span-2">
            <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Búsqueda</div>
            <div className="flex items-center gap-2 bg-black/40 border border-white/10 rounded-2xl px-4 py-3">
              <Search size={16} className="text-white/50" />
              <input value={myFilters.q} onChange={(e) => setMyFilters((s) => ({ ...s, q: e.target.value }))} placeholder="Buscar por evento, venue, ciudad…" className="w-full bg-transparent outline-none text-[11px] text-white placeholder:text-white/30" />
            </div>
          </div>
        </div>
      </div>

      {myAssetsLoading ? (
        <div className="text-white/60 text-[11px]">Cargando…</div>
      ) : myAssetsError ? (
        <div className="p-5 rounded-3xl bg-red-500/10 border border-red-500/20 text-[11px] text-red-200">{myAssetsError}</div>
      ) : (
        (() => {
          const q = (myFilters.q || "").trim().toLowerCase();
          const filtered = (Array.isArray(myAssets) ? myAssets : [])
            .filter((a) => (myFilters.kind === "all" ? true : String(a.kind || "") === myFilters.kind))
            .filter((a) => (myFilters.status === "all" ? true : String(a.status || "").toLowerCase() === myFilters.status))
            .filter((a) => {
              if (!q) return true;
              const hay = `${a.title || ""} ${a.venue || ""} ${a.city || ""} ${a.event_slug || ""}`.toLowerCase();
              return hay.includes(q);
            });

          if (!filtered.length) {
            return <div className="p-6 rounded-3xl bg-white/5 border border-white/10 text-[11px] text-white/60">No hay tickets para mostrar con esos filtros.</div>;
          }

          return (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {filtered.map((a) => {
                const kind = String(a.kind || "entradas");
                const st = String(a.status || "valid").toLowerCase();
                const isUsed = st === "used";
                const isCancelReq = st === "cancel_requested";
                const isCancelled = st === "cancelled";
                const badgeKind = kind === "barra" ? "Barra" : "Entradas";
                const badgeStatus = isCancelled ? "Cancelado" : isCancelReq ? "Arrepentimiento" : isUsed ? "Usado" : "Por usar";
                const qrPayload = a.qr_payload || "";
                const eventTitle = (a.title || a.event_title || a.event_slug || (kind === "barra" ? "Compra de Barra" : "Entrada")).trim();

                return (
                  <div key={`${kind}-${a.id}`} className="rounded-3xl bg-white/5 border border-white/10 overflow-hidden">
                    <div className="flex gap-5 p-5">
                      <div className="w-28 h-28 rounded-3xl overflow-hidden bg-white/10 border border-white/10 flex-shrink-0 flex items-center justify-center">
                        {normalizeAssetUrl(a.flyer_url) ? <img src={normalizeAssetUrl(a.flyer_url)} alt="" className="w-full h-full object-cover" /> : <QrCode size={34} className="text-indigo-300" />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <div className="px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-widest bg-white/10 border border-white/10">{badgeKind}</div>
                          <div className={`px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-widest border ${
                            isCancelled ? "bg-red-500/10 border-red-500/20 text-red-200" :
                            isCancelReq ? "bg-amber-500/10 border-amber-500/20 text-amber-200" :
                            isUsed ? "bg-white/10 border-white/10 text-white/70" :
                            "bg-emerald-500/10 border-emerald-500/20 text-emerald-200"
                          }`}>{badgeStatus}</div>
                        </div>
                        <div className="mt-3 text-xl font-black leading-tight truncate">{eventTitle}</div>
                        <div className="mt-2 text-[11px] text-white/60">{(a.date_text || "Fecha a confirmar")} · {(a.venue || "Venue")} · {(a.city || "Ciudad")}</div>
                        <div className="mt-2 text-[10px] text-white/40 font-black uppercase tracking-widest">Orden #{a.order_id}</div>
                      </div>
                    </div>

                    <div className="px-5 pb-5">
                      <div className="flex flex-col md:flex-row gap-5 items-start md:items-center justify-between">
                        <div className="flex items-center gap-4">
                          <div className="w-40 h-40 rounded-3xl bg-white p-2 flex items-center justify-center">
                            {qrPayload ? <img src={qrImgUrl(qrPayload, 220)} alt="QR" className="w-full h-full object-contain" /> : <div className="text-[10px] text-black/60 font-black uppercase tracking-widest">Sin QR</div>}
                          </div>
                          <div className="space-y-2">
                            <button onClick={() => a.order_id && window.open(`/api/tickets/orders/${encodeURIComponent(a.order_id)}/pdf`, "_blank", "noopener,noreferrer")} disabled={!a.order_id} className="px-4 py-2 rounded-2xl text-[9px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 text-white disabled:opacity-40">Descargar PDF</button>
                            <button onClick={async () => { try { const to = prompt("Transferir compra a este email:", ""); if (!to) return; await transferOrder({ order_id: a.order_id, ticket_id: a.id, to_email: to }); alert("Transferencia solicitada. El nuevo titular verá la compra en Mis Tickets."); await loadMyAssets(); } catch (e) { alert(e?.message || "No se pudo transferir."); } }} className="px-4 py-2 rounded-2xl text-[9px] font-black uppercase tracking-widest bg-white/5 hover:bg-white/10 transition-all border border-white/10 text-white">Transferir compra</button>
                            <button onClick={async () => { try { const ok = confirm("Arrepentimiento: enviaremos tu solicitud a soporte para revisión manual. ¿Continuar?"); if (!ok) return; const reason = prompt("Motivo (opcional):", ""); await requestCancel({ kind, id: a.id, order_id: a.order_id, reason: reason || "" }); alert("Listo. Tu solicitud fue enviada a soporte para evaluación y posible devolución."); await loadMyAssets(); } catch (e) { alert(e?.message || "No se pudo solicitar arrepentimiento."); } }} className="px-4 py-2 rounded-2xl text-[9px] font-black uppercase tracking-widest bg-amber-500/10 hover:bg-amber-500/15 transition-all border border-amber-500/20 text-amber-200">Arrepentimiento</button>
                          </div>
                        </div>
                        <div className="w-full md:w-auto">
                          <div className="p-4 rounded-3xl bg-black/30 border border-white/10 text-[11px] text-white/60 leading-relaxed">
                            <div className="text-[9px] font-black uppercase tracking-widest text-neutral-500 mb-2">Detalle</div>
                            <div>• ID: <span className="text-white/80 font-black">{a.id}</span></div>
                            <div>• Tipo: <span className="text-white/80 font-black">{badgeKind}</span></div>
                            <div>• Estado: <span className="text-white/80 font-black">{badgeStatus}</span></div>
                            {a.used_at ? <div>• Usado: <span className="text-white/80 font-black">{String(a.used_at)}</span></div> : null}
                            {a.created_at ? <div>• Creado: <span className="text-white/80 font-black">{String(a.created_at)}</span></div> : null}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })()
      )}
    </div>
  );
}
