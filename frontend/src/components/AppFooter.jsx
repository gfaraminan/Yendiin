import { brandConfig } from "../config/brand";
import { featureFlags } from "../config/features";
import { legalConfig } from "../config/legal";

export default function AppFooter({ me, openLoginModal, setView, loadProducerEvents }) {
  const showProducerCta = featureFlags.producerPanel;
  const whatsappUrl = brandConfig.whatsapp ? `https://wa.me/${String(brandConfig.whatsapp).replace(/[^\d]/g, "")}` : "";

  return (
    <footer className="border-t border-white/5 bg-black/40 backdrop-blur-xl overflow-x-hidden">
      <div className="max-w-7xl mx-auto px-6 py-10">
        <div className="flex flex-col md:flex-row gap-10 md:items-start md:justify-between">
          <div className="min-w-0">
            <div className="text-white font-black uppercase italic tracking-tight text-xl">{brandConfig.headerLabel}</div>
            <div className="text-[11px] text-white/50 mt-2 max-w-md">Plataforma de tickets con QR antifraude. Cartelera pública + panel Producer en un solo lugar.</div>
            {showProducerCta && (
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
                  {brandConfig.producerPanelLabel}
                </button>
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-8 text-[11px] font-black uppercase tracking-widest">
            <div className="space-y-3">
              <div className="text-neutral-500">Legal</div>
              <a className="block text-white/80 hover:text-white transition-colors" href={legalConfig.termsUrl} target="_blank" rel="noopener noreferrer">Términos</a>
              <a className="block text-white/80 hover:text-white transition-colors" href={legalConfig.privacyUrl} target="_blank" rel="noopener noreferrer">Privacidad</a>
              <a className="block text-white/80 hover:text-white transition-colors" href={legalConfig.refundsUrl} target="_blank" rel="noopener noreferrer">Reembolsos</a>
              <a className="block text-white/80 hover:text-white transition-colors" href={legalConfig.faqUrl} target="_blank" rel="noopener noreferrer">FAQ clientes</a>
              <a className="block text-white/80 hover:text-white transition-colors" href={legalConfig.producerFaqUrl} target="_blank" rel="noopener noreferrer">FAQ productor</a>
            </div>

            {featureFlags.supportLinks && (
              <div className="space-y-3">
                <div className="text-neutral-500">Contacto</div>
                <a className="block text-white/80 hover:text-white transition-colors" href={`mailto:${brandConfig.supportEmail}`}>{brandConfig.supportEmail}</a>
                <a className="block text-white/80 hover:text-white transition-colors" href={`mailto:${brandConfig.salesEmail}`}>{brandConfig.salesEmail}</a>
                <a className="block text-white/80 hover:text-white transition-colors" href={`mailto:${brandConfig.infoEmail}`}>{brandConfig.infoEmail}</a>
                {whatsappUrl && (
                  <a className="inline-flex items-center gap-2 text-white/80 hover:text-white transition-colors" href={whatsappUrl} target="_blank" rel="noopener noreferrer" aria-label="Contactar por WhatsApp">
                    WhatsApp
                  </a>
                )}
              </div>
            )}

            <div className="space-y-3 col-span-2 sm:col-span-1">
              <div className="text-neutral-500">Redes</div>
              <div className="flex items-center gap-2">
                <a className="px-4 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 transition-all" href={brandConfig.instagramUrl} target="_blank" rel="noopener noreferrer">Instagram</a>
                <a className="px-4 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 transition-all" href={brandConfig.tiktokUrl} target="_blank" rel="noopener noreferrer">TikTok</a>
                <a className="px-4 py-2 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 transition-all" href={brandConfig.xUrl} target="_blank" rel="noopener noreferrer">X</a>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-10 flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between text-[10px] font-black uppercase tracking-widest text-white/40">
          <div>© {new Date().getFullYear()} {brandConfig.shortName}</div>
          <div className="flex items-center gap-4">
            <span>{brandConfig.name} © es una marca registrada de {brandConfig.footerLegalName}</span>
            <span className="hidden sm:inline">·</span>
            <span>{brandConfig.footerCopyright}</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
