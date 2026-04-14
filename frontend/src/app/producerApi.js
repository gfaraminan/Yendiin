export const fetchProducerJson = async (url, options = {}) => {
  const response = await fetch(url, { credentials: "include", ...options });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`HTTP ${response.status} ${response.statusText}${text ? ` — ${text}` : ""}`);
  }
  return response.json();
};

export const listProducerEvents = ({ tenantId }) => fetchProducerJson(`/api/producer/events?tenant_id=${encodeURIComponent(tenantId)}`);

export const getProducerDashboard = ({ tenantId, eventSlug }) =>
  fetchProducerJson(`/api/producer/dashboard?tenant_id=${encodeURIComponent(tenantId)}&event_slug=${encodeURIComponent(eventSlug)}`);

export const getOwnerSummary = async ({ slug, owner }) => {
  const base = `/api/owner/summary?event=${encodeURIComponent(slug)}`;
  const withOwner = owner ? `${base}&owner=${encodeURIComponent(owner)}` : base;
  let response = await fetch(withOwner, { credentials: "include" });
  if (!response.ok && owner) {
    response = await fetch(base, { credentials: "include" });
  }
  if (!response.ok) return null;
  const data = await response.json().catch(() => null);
  if (!data || typeof data !== "object") return null;
  return {
    gross: Number(data?.gross || data?.gross_amount || 0),
    paid_count: Number(data?.paid_count || data?.paid || 0),
  };
};
