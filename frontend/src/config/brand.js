const env = import.meta.env;

const trimOr = (value, fallback) => {
  const normalized = typeof value === "string" ? value.trim() : "";
  return normalized || fallback;
};

export const brandConfig = {
  name: trimOr(env.VITE_BRAND_NAME, "Yendiin"),
  shortName: trimOr(env.VITE_BRAND_SHORT_NAME, "Yendiin"),
  headerLabel: trimOr(env.VITE_BRAND_HEADER_LABEL, "Yendiin"),
  heroTitle: trimOr(env.VITE_BRAND_HERO_TITLE, "Cartelera Viva"),
  heroSubtitle: trimOr(env.VITE_BRAND_HERO_SUBTITLE, "Comprá tu ticket · QR antifraude · acceso rápido"),
  supportEmail: trimOr(env.VITE_BRAND_SUPPORT_EMAIL, "soporte@yendiin.com"),
  salesEmail: trimOr(env.VITE_BRAND_SALES_EMAIL, "ventas@yendiin.com"),
  infoEmail: trimOr(env.VITE_BRAND_INFO_EMAIL, "info@yendiin.com"),
  whatsapp: trimOr(env.VITE_BRAND_WHATSAPP, "5492614167597"),
  instagramUrl: trimOr(env.VITE_BRAND_INSTAGRAM_URL, "#instagram"),
  tiktokUrl: trimOr(env.VITE_BRAND_TIKTOK_URL, "#tiktok"),
  xUrl: trimOr(env.VITE_BRAND_X_URL, "#x"),
  footerLegalName: trimOr(env.VITE_BRAND_FOOTER_LEGAL_NAME, "The Brain Lab SAS"),
  footerCopyright: trimOr(env.VITE_BRAND_COPYRIGHT, "Todos los derechos reservados"),
  producerPanelLabel: trimOr(env.VITE_BRAND_PRODUCER_PANEL_LABEL, "Productor"),
  adminPanelLabel: trimOr(env.VITE_BRAND_ADMIN_PANEL_LABEL, "Administrador"),
};

export const makeBrandPageTitle = (page = "") => {
  const suffix = brandConfig.shortName || brandConfig.name;
  const prefix = String(page || "").trim();
  return prefix ? `${prefix} · ${suffix}` : suffix;
};
