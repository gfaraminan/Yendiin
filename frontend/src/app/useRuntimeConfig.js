import { useEffect, useMemo, useState } from "react";
import { resolveBrandConfig } from "../config/brand";
import { resolveFeatureFlags } from "../config/features";
import { resolveLegalConfig } from "../config/legal";
import { defaultRuntimeConfig, resolvePublicTenant } from "../config/runtime";

export function useRuntimeConfig() {
  const [googleClientId, setGoogleClientId] = useState("");
  const [runtimeConfig, setRuntimeConfig] = useState(defaultRuntimeConfig);

  const brandConfig = useMemo(() => resolveBrandConfig(runtimeConfig), [runtimeConfig]);
  const featureFlags = useMemo(() => resolveFeatureFlags(runtimeConfig), [runtimeConfig]);
  const legalConfig = useMemo(() => resolveLegalConfig(runtimeConfig), [runtimeConfig]);
  const publicTenant = useMemo(() => resolvePublicTenant(runtimeConfig), [runtimeConfig]);

  useEffect(() => {
    fetch("/api/public/config")
      .then((r) => r.json())
      .then((cfg) => {
        setGoogleClientId(cfg?.google_client_id || "");
        setRuntimeConfig((prev) => ({
          ...prev,
          public_tenant: cfg?.public_tenant || cfg?.default_public_tenant || prev.public_tenant || "",
          default_public_tenant: cfg?.default_public_tenant || prev.default_public_tenant || "",
          brand_name: cfg?.brand_name || prev.brand_name || "",
          branding: typeof cfg?.branding === "object" && cfg?.branding ? cfg.branding : prev.branding,
          legal: typeof cfg?.legal === "object" && cfg?.legal ? cfg.legal : prev.legal,
          features: typeof cfg?.features === "object" && cfg?.features ? cfg.features : prev.features,
          feature_flags: typeof cfg?.feature_flags === "object" && cfg?.feature_flags ? cfg.feature_flags : prev.feature_flags,
        }));
      })
      .catch(() => {
        setGoogleClientId("");
      });
  }, []);

  return {
    brandConfig,
    featureFlags,
    googleClientId,
    legalConfig,
    publicTenant,
    runtimeConfig,
  };
}
