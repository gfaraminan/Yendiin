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
  whatsapp: trimOr(env.VITE_BRAND_WHATSAPP, "5492615260461"),
  instagramUrl: trimOr(env.VITE_BRAND_INSTAGRAM_URL, "https://www.instagram.com/yendiin.tickets?igsh=ZG0zdTJqYnN2N2hj"),
  tiktokUrl: trimOr(env.VITE_BRAND_TIKTOK_URL, "#tiktok"),
  xUrl: trimOr(env.VITE_BRAND_X_URL, "#x"),
  footerLegalName: trimOr(env.VITE_BRAND_FOOTER_LEGAL_NAME, "Event InDaHouse SAS"),
  footerCopyright: trimOr(env.VITE_BRAND_COPYRIGHT, "Todos los derechos reservados"),
  producerPanelLabel: trimOr(env.VITE_BRAND_PRODUCER_PANEL_LABEL, "PRODUCTOR"),
  adminPanelLabel: trimOr(env.VITE_BRAND_ADMIN_PANEL_LABEL, "ADMINISTRADOR"),
};

const readWindowConfig = () => {
  if (typeof window === "undefined") return {};
  const cfg = window.__APP_CONFIG__;
  return cfg && typeof cfg === "object" ? cfg : {};
};

const normalizeBrandOverrides = (config = {}) => ({
  ...config,
  supportEmail: config.supportEmail ?? config.support_email,
  salesEmail: config.salesEmail ?? config.sales_email,
  infoEmail: config.infoEmail ?? config.info_email,
  instagramUrl: config.instagramUrl ?? config.instagram_url,
  tiktokUrl: config.tiktokUrl ?? config.tiktok_url,
  xUrl: config.xUrl ?? config.x_url,
  footerLegalName: config.footerLegalName ?? config.legal_name ?? config.footer_legal_name,
  footerCopyright: config.footerCopyright ?? config.footer_copyright,
  producerPanelLabel: config.producerPanelLabel ?? config.producer_panel_label,
  adminPanelLabel: config.adminPanelLabel ?? config.admin_panel_label,
});

export const resolveBrandConfig = (runtimeConfig = null) => {
  const windowCfg = readWindowConfig();
  const fromRuntime = normalizeBrandOverrides(runtimeConfig?.branding || runtimeConfig?.brand || {});
  const fromWindow = normalizeBrandOverrides(windowCfg.branding || windowCfg.brand || {});

  return {
    ...envBrandConfig,
    ...fromWindow,
    ...fromRuntime,
    name: trimOr(fromRuntime.name ?? fromWindow.name ?? runtimeConfig?.brand_name, envBrandConfig.name),
    shortName: trimOr(fromRuntime.shortName ?? fromWindow.shortName, envBrandConfig.shortName),
    headerLabel: trimOr(fromRuntime.headerLabel ?? fromWindow.headerLabel, envBrandConfig.headerLabel),
    supportEmail: trimOr(fromRuntime.supportEmail ?? fromWindow.supportEmail, envBrandConfig.supportEmail),
    salesEmail: trimOr(fromRuntime.salesEmail ?? fromWindow.salesEmail, envBrandConfig.salesEmail),
    infoEmail: trimOr(fromRuntime.infoEmail ?? fromWindow.infoEmail, envBrandConfig.infoEmail),
    whatsapp: trimOr(fromRuntime.whatsapp ?? fromWindow.whatsapp, envBrandConfig.whatsapp),
    instagramUrl: trimOr(fromRuntime.instagramUrl ?? fromWindow.instagramUrl, envBrandConfig.instagramUrl),
    footerLegalName: trimOr(fromRuntime.footerLegalName ?? fromWindow.footerLegalName, envBrandConfig.footerLegalName),
    producerPanelLabel: trimOr(fromRuntime.producerPanelLabel ?? fromWindow.producerPanelLabel, envBrandConfig.producerPanelLabel),
    adminPanelLabel: trimOr(fromRuntime.adminPanelLabel ?? fromWindow.adminPanelLabel, envBrandConfig.adminPanelLabel),
  };
};

export const brandConfig = resolveBrandConfig();

export const makeBrandPageTitle = (page = "", runtimeConfig = null) => {
  const resolved = resolveBrandConfig(runtimeConfig);
  const suffix = resolved.shortName || resolved.name;
  const prefix = String(page || "").trim();
  return prefix ? `${prefix} · ${suffix}` : suffix;
};
