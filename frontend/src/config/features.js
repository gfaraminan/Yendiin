const env = import.meta.env;

const parseBool = (value, fallback = true) => {
  if (value == null || value === "") return fallback;
  const normalized = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "off"].includes(normalized)) return false;
  return fallback;
};

export const featureFlags = {
  producerPanel: parseBool(env.VITE_FEATURE_PRODUCER_PANEL, true),
  googleLogin: parseBool(env.VITE_FEATURE_GOOGLE_LOGIN, true),
  magicLinkLogin: parseBool(env.VITE_FEATURE_MAGIC_LINK_LOGIN, true),
  featuredCarousel: parseBool(env.VITE_FEATURE_FEATURED_CAROUSEL, true),
  whatsappShare: parseBool(env.VITE_FEATURE_WHATSAPP_SHARE, true),
  supportLinks: parseBool(env.VITE_FEATURE_SUPPORT_LINKS, true),
  brandedAdminLabels: parseBool(env.VITE_FEATURE_BRANDED_ADMIN_LABELS, true),
};
