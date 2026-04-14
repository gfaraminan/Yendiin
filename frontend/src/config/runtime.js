const env = import.meta.env;

const trimOrEmpty = (value) => (typeof value === "string" ? value.trim() : "");

const envTenant = trimOrEmpty(env.VITE_DEFAULT_PUBLIC_TENANT) || "default";

const readWindowConfig = () => {
  if (typeof window === "undefined") return {};
  const cfg = window.__APP_CONFIG__;
  return cfg && typeof cfg === "object" ? cfg : {};
};

export const defaultRuntimeConfig = {
  publicTenant: envTenant,
};

const safeObject = (value) => (value && typeof value === "object" ? value : null);

export const normalizePublicConfigPayload = (payload, previousConfig = {}) => {
  const cfg = safeObject(payload) || {};
  const prev = safeObject(previousConfig) || {};
  const resolvedPublicTenant = trimOrEmpty(cfg.public_tenant) || trimOrEmpty(cfg.default_public_tenant) || trimOrEmpty(prev.public_tenant);
  const resolvedDefaultTenant = trimOrEmpty(cfg.default_public_tenant) || trimOrEmpty(prev.default_public_tenant);
  const resolvedBranding = safeObject(cfg.branding) || safeObject(cfg.brand) || prev.branding || prev.brand || null;
  const resolvedLegal = safeObject(cfg.legal) || prev.legal || null;
  const resolvedFeatures = safeObject(cfg.features) || safeObject(cfg.feature_flags) || prev.features || prev.feature_flags || null;

  return {
    ...prev,
    public_tenant: resolvedPublicTenant,
    default_public_tenant: resolvedDefaultTenant,
    brand_name: trimOrEmpty(cfg.brand_name) || trimOrEmpty(prev.brand_name),
    branding: resolvedBranding || prev.branding,
    legal: resolvedLegal || prev.legal,
    features: resolvedFeatures || prev.features,
    feature_flags: resolvedFeatures || prev.feature_flags,
  };
};

export const resolvePublicTenant = (runtimeConfig = null) => {
  const windowCfg = readWindowConfig();
  const candidates = [
    windowCfg.public_tenant,
    windowCfg.default_public_tenant,
    runtimeConfig?.public_tenant,
    runtimeConfig?.default_public_tenant,
    envTenant,
    "default",
  ];

  for (const candidate of candidates) {
    const normalized = trimOrEmpty(candidate);
    if (normalized) return normalized;
  }

  return "default";
};
