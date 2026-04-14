const env = import.meta.env;

const trimOr = (value, fallback) => {
  const normalized = typeof value === "string" ? value.trim() : "";
  return normalized || fallback;
};

const envLegalConfig = {
  termsUrl: trimOr(env.VITE_LEGAL_TERMS_URL, "/static/legal/terminos-y-condiciones.pdf"),
  privacyUrl: trimOr(env.VITE_LEGAL_PRIVACY_URL, "/static/legal/politica-de-privacidad.pdf"),
  refundsUrl: trimOr(env.VITE_LEGAL_REFUNDS_URL, "/static/legal/politica-de-reembolsos.pdf"),
  faqUrl: trimOr(env.VITE_FAQ_URL, "/legal/faqs-ticketpro.html"),
  producerFaqUrl: trimOr(env.VITE_FAQ_PRODUCER_URL, "/legal/faqs-productor-ticketpro.html"),
  producerTermsUrl: trimOr(env.VITE_LEGAL_PRODUCER_TERMS_URL, "/static/legal/terminos-y-condiciones-productor.pdf"),
};

const readWindowConfig = () => {
  if (typeof window === "undefined") return {};
  const cfg = window.__APP_CONFIG__;
  return cfg && typeof cfg === "object" ? cfg : {};
};

export const resolveLegalConfig = (runtimeConfig = null) => {
  const windowCfg = readWindowConfig();
  const fromRuntime = runtimeConfig?.legal || {};
  const fromWindow = windowCfg.legal || {};
  return { ...envLegalConfig, ...fromWindow, ...fromRuntime };
};

export const legalConfig = resolveLegalConfig();
