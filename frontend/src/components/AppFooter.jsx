const LEGAL_LINKS = {
  terms: (import.meta.env.VITE_LEGAL_TERMS_URL || '/static/legal/terminos-y-condiciones.pdf').trim(),
  privacy: (import.meta.env.VITE_LEGAL_PRIVACY_URL || '/static/legal/politica-de-privacidad.pdf').trim(),
  refunds: (import.meta.env.VITE_LEGAL_REFUNDS_URL || '/static/legal/politica-de-reembolsos.pdf').trim(),
  faqCustomers: (import.meta.env.VITE_FAQ_URL || '/legal/faqs-ticketpro.html').trim(),
  faqProducer: (import.meta.env.VITE_FAQ_PRODUCER_URL || '/legal/faqs-productor-ticketpro.html').trim(),
};

export default function AppFooter({ me, openLoginModal, setView, loadProducerEvents }) {
  return (
    <footer className="border-t border-white/5 bg-black/40 backdrop-blur-xl overflow-x-hidden">
      <div className="max-w-7xl mx-auto px-6 py-10">
        <div className="flex flex-col md:flex-row gap-10 md:items-start md:justify-between">
          <div className="min-w-0">
            <div className="text-white font-black uppercase italic tracking-tight text-xl">
              Ticket<span className="text-indigo-400">Pro</span>
            </div>
            <div className="text-[11px] text-white/50 mt-2 max-w-md">
              Plataforma de tickets con QR antifraude. Cartelera pública + panel Producer en un solo lugar.
            </div>
            <div className="mt-4">
              <button
                onClick={() => {
                  if (!me) {
                    openLoginModal({ goto: "producer" });
                    return;
                  }
                  setView("producer");
                  setTimeout(() => {
                    try {
                      loadProducerEvents();
                    } catch {
                      // noop
                    }
                  }, 0);
                }}
                className="px-5 py-3 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] font-black uppercase tracking-widest transition-all"
              >
                Productor
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-8 text-[11px] font-black uppercase tracking-widest">
            <div className="space-y-3">
              <div className="text-neutral-500">Legal</div>
              <a className="block text-white/80 hover:text-white transition-colors" href={LEGAL_LINKS.terms} target="_blank" rel="noopener noreferrer">
                Términos
              </a>
              <a className="block text-white/80 hover:text-white transition-colors" href={LEGAL_LINKS.privacy} target="_blank" rel="noopener noreferrer">
                Privacidad
              </a>
              <a className="block text-white/80 hover:text-white transition-colors" href={LEGAL_LINKS.refunds} target="_blank" rel="noopener noreferrer">
                Reembolsos
              </a>
              <a className="block text-white/80 hover:text-white transition-colors" href={LEGAL_LINKS.faqCustomers} target="_blank" rel="noopener noreferrer">
                FAQ clientes
              </a>
              <a className="block text-white/80 hover:text-white transition-colors" href={LEGAL_LINKS.faqProducer} target="_blank" rel="noopener noreferrer">
                FAQ productor
              </a>
            </div>

            <div className="space-y-3">
              <div className="text-neutral-500">Contacto</div>
              <a className="block text-white/80 hover:text-white transition-colors" href="mailto:soporte@ticketpro.com.ar">
                soporte@ticketpro.com.ar
              </a>
              <a className="block text-white/80 hover:text-white transition-colors" href="mailto:ventas@ticketpro.com.ar">
                ventas@ticketpro.com.ar
              </a>
              <a className="block text-white/80 hover:text-white transition-colors" href="mailto:info@ticketpro.com.ar">
                info@ticketpro.com.ar
              </a>
              <a
                className="inline-flex items-center gap-2 text-white/80 hover:text-white transition-colors"
                href="https://wa.me/5492614167597"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Contactar por WhatsApp"
              >
                <svg viewBox="0 0 32 32" aria-hidden="true" className="h-4 w-4 fill-current">
                  <path d="M19.11 17.2c-.26-.14-1.5-.73-1.74-.8-.23-.08-.4-.13-.57.13-.17.26-.65.8-.8.95-.15.16-.3.18-.56.05-.26-.13-1.08-.4-2.07-1.27-.76-.68-1.28-1.52-1.43-1.78-.15-.26-.02-.4.11-.53.12-.12.26-.3.4-.44.13-.14.17-.25.26-.42.09-.17.04-.32-.02-.45-.06-.13-.57-1.37-.77-1.88-.2-.49-.4-.43-.57-.44h-.49c-.17 0-.45.06-.69.32-.24.26-.9.88-.9 2.14s.93 2.48 1.06 2.65c.13.17 1.82 2.77 4.4 3.89.62.27 1.11.43 1.49.55.63.2 1.2.17 1.66.1.5-.08 1.5-.61 1.71-1.2.21-.59.21-1.1.14-1.2-.08-.1-.24-.16-.5-.3z" />
                  <path d="M16 3C8.82 3 3 8.82 3 16c0 2.28.6 4.52 1.75 6.48L3 29l6.72-1.7A12.93 12.93 0 0 0 16 29c7.18 0 13-5.82 13-13S23.18 3 16 3zm0 23.9c-2.05 0-4.07-.55-5.84-1.6l-.42-.25-3.99 1.01 1.07-3.89-.28-.45a10.9 10.9 0 1 1 9.46 5.18z" />
                </svg>
                WhatsApp
              </a>
            </div>

            <div className="space-y-3 col-span-2 sm:col-span-1">
              <div className="text-neutral-500">Redes</div>
              <div className="flex items-center gap-2">
                <a
                  className="px-4 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 transition-all"
                  href="#instagram"
                >
                  Instagram
                </a>
                <a
                  className="px-4 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 transition-all"
                  href="#tiktok"
                >
                  TikTok
                </a>
                <a
                  className="px-4 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 transition-all"
                  href="#x"
                >
                  X
                </a>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-10 flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between text-[10px] font-black uppercase tracking-widest text-white/40">
          <div>© {new Date().getFullYear()} TicketPro</div>
          <div className="flex items-center gap-4">
            <span>TicketPro © es una marca registrada de The Brain Lab SAS</span>
            <span className="hidden sm:inline">·</span>
            <span>Todos los derechos reservados</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
