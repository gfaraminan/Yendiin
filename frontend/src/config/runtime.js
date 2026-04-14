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
