export const buildStaffPosPayload = ({ publicTenant, staffPosDraft, saleItemId, quantity }) => ({
  tenant_id: publicTenant,
  sale_item_id: saleItemId,
  quantity,
  payment_method: String(staffPosDraft.payment_method || "cash").trim().toLowerCase(),
  seller_code: String(staffPosDraft.seller_code || "").trim() || null,
  buyer_name: String(staffPosDraft.buyer_name || "").trim() || null,
  buyer_email: String(staffPosDraft.buyer_email || "").trim() || null,
  buyer_phone: String(staffPosDraft.buyer_phone || "").trim() || null,
  buyer_dni: String(staffPosDraft.buyer_dni || "").trim() || null,
  note: String(staffPosDraft.note || "").trim() || null,
});

export const normalizeStaffPosResult = ({ response, quantity, paymentMethod }) => ({
  order_id: String(response?.order_id || ""),
  quantity: Number(response?.quantity || quantity),
  payment_method: String(response?.payment_method || paymentMethod || "cash"),
  total_cents: Number(response?.total_cents || 0),
  tickets: Array.isArray(response?.tickets) ? response.tickets : [],
});

export const buildValidateQrPayload = ({ qrToken, validatorEvent, staffToken }) => ({
  qr_token: qrToken,
  event_slug: validatorEvent?.slug || "",
  ...(staffToken ? { staff_token: staffToken } : {}),
});
