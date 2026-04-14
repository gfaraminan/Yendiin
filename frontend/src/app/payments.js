export const createMpPreference = async ({ publicTenant, orderId, readJsonOrText }) => {
  const response = await fetch(`/api/payments/mp/create-preference?tenant=${encodeURIComponent(publicTenant)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ order_id: orderId }),
  });
  const payload = await readJsonOrText(response);
  if (!response.ok || !payload?.ok || !payload?.checkout_url) {
    throw new Error(payload?.detail || "No se pudo iniciar Mercado Pago");
  }
  return payload;
};
