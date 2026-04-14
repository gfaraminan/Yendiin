const env = import.meta.env;

const parseBool = (value, fallback = true) => {
  if (value == null || value === "") return fallback;
  const normalized = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "off"].includes(normalized)) return false;
  return fallback;
};

const envFeatureFlags = {
  producerPanel: parseBool(env.VITE_FEATURE_PRODUCER_PANEL, true),
  googleLogin: parseBool(env.VITE_FEATURE_GOOGLE_LOGIN, true),
  magicLinkLogin: parseBool(env.VITE_FEATURE_MAGIC_LINK_LOGIN, true),
  featuredCarousel: parseBool(env.VITE_FEATURE_FEATURED_CAROUSEL, true),
  whatsappShare: parseBool(env.VITE_FEATURE_WHATSAPP_SHARE, true),
  supportLinks: parseBool(env.VITE_FEATURE_SUPPORT_LINKS, true),
  brandedAdminLabels: parseBool(env.VITE_FEATURE_BRANDED_ADMIN_LABELS, true),
  altCheckoutUx: parseBool(env.VITE_FEATURE_ALT_CHECKOUT_UX, false),
  altProducerUi: parseBool(env.VITE_FEATURE_ALT_PRODUCER_UI, false),
  altStaffUi: parseBool(env.VITE_FEATURE_ALT_STAFF_UI, false),
};

const readWindowConfig = () => {
  if (typeof window === "undefined") return {};
  const cfg = window.__APP_CONFIG__;
  return cfg && typeof cfg === "object" ? cfg : {};
};

export const resolveFeatureFlags = (runtimeConfig = null) => {
  const windowCfg = readWindowConfig();
  const fromRuntime = runtimeConfig?.features || runtimeConfig?.feature_flags || {};
  const fromWindow = windowCfg.features || windowCfg.feature_flags || {};
  const merged = { ...envFeatureFlags, ...fromWindow, ...fromRuntime };
  return Object.fromEntries(
    Object.entries(merged).map(([k, v]) => [k, parseBool(v, envFeatureFlags[k] ?? true)])
  );
};

export const featureFlags = resolveFeatureFlags();
