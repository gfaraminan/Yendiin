import { normalizePublicConfigPayload } from "../config/runtime";

export const fetchPublicRuntimeConfig = async () => {
  const response = await fetch("/api/public/config", { credentials: "include" });
  if (!response.ok) throw new Error(`public_config_http_${response.status}`);
  return response.json();
};

export const resolveRuntimeConfigState = (cfg, previousConfig) => ({
  googleClientId: cfg?.google_client_id || "",
  runtimeConfig: normalizePublicConfigPayload(cfg, previousConfig),
});

export const resolveCheckoutSuccessState = ({ hash, previousPurchaseData, selectedEvent, selectedTicket, quantity, checkoutForm }) => {
  const value = String(hash || "");
  const match = value.match(/^#\/checkout\/success(?:\?(.*))?$/i);
  if (!match) return null;

  const params = new URLSearchParams(match[1] || "");
  const orderId = (params.get("order_id") || "").trim();

  return {
    event: previousPurchaseData?.event || selectedEvent || { title: "Tu evento" },
    ticket: previousPurchaseData?.ticket || selectedTicket || null,
    quantity: previousPurchaseData?.quantity || quantity || 1,
    user: previousPurchaseData?.user || checkoutForm || {},
    method: previousPurchaseData?.method || "mp",
    order_id: orderId || previousPurchaseData?.order_id || null,
    tickets: Array.isArray(previousPurchaseData?.tickets) ? previousPurchaseData.tickets : [],
  };
};
