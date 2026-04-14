const env = import.meta.env;

const trimOr = (value, fallback) => {
  const normalized = typeof value === "string" ? value.trim() : "";
  return normalized || fallback;
};

const envBrandConfig = {
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

const readWindowConfig = () => {
  if (typeof window === "undefined") return {};
  const cfg = window.__APP_CONFIG__;
  return cfg && typeof cfg === "object" ? cfg : {};
};

export const resolveBrandConfig = (runtimeConfig = null) => {
  const windowCfg = readWindowConfig();
  const fromRuntime = runtimeConfig?.branding || runtimeConfig?.brand || {};
  const fromWindow = windowCfg.branding || windowCfg.brand || {};

  return {
    ...envBrandConfig,
    ...fromWindow,
    ...fromRuntime,
    name: trimOr(fromRuntime.name ?? fromWindow.name ?? runtimeConfig?.brand_name, envBrandConfig.name),
    shortName: trimOr(fromRuntime.shortName ?? fromWindow.shortName, envBrandConfig.shortName),
    headerLabel: trimOr(fromRuntime.headerLabel ?? fromWindow.headerLabel, envBrandConfig.headerLabel),
  };
};

export const brandConfig = resolveBrandConfig();

export const makeBrandPageTitle = (page = "", runtimeConfig = null) => {
  const resolved = resolveBrandConfig(runtimeConfig);
  const suffix = resolved.shortName || resolved.name;
  const prefix = String(page || "").trim();
  return prefix ? `${prefix} · ${suffix}` : suffix;
};
