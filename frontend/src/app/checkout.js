import { isEventSoldOut } from "./eventSales";

export const validateCheckoutForm = (checkoutForm = {}) => {
  const errors = {};
  const name = (checkoutForm.fullName || "").trim();
  const address = (checkoutForm.address || "").trim();
  const province = (checkoutForm.province || "").trim();
  const postalCode = (checkoutForm.postalCode || "").trim();
  const birthDate = (checkoutForm.birthDate || "").trim();
  const dni = String(checkoutForm.dni || "").replace(/\D/g, "");
  const phone = String(checkoutForm.phone || "").replace(/\D/g, "");

  if (!name) errors.fullName = "Ingresá tu nombre y apellido.";
  if (!dni) errors.dni = "Ingresá tu DNI.";
  else if (dni.length < 7) errors.dni = "DNI.";
  if (!phone) errors.phone = "Ingresá tu celular de contacto.";
  else if (phone.length < 8) errors.phone = "El celular debe tener al menos 8 dígitos.";
  if (!address) errors.address = "Ingresá tu domicilio completo.";
  if (!province) errors.province = "Ingresá tu provincia.";
  if (!postalCode) errors.postalCode = "Ingresá tu código postal.";
  if (!birthDate) errors.birthDate = "Ingresá tu fecha de nacimiento.";
  if (!checkoutForm.acceptTerms) errors.acceptTerms = "Aceptá Términos y Condiciones para continuar.";

  return errors;
};

export const resolveCheckoutServicePct = (selectedEvent) => {
  const raw = Number(selectedEvent?.service_charge_pct);
  if (!Number.isFinite(raw) || raw < 0) return 0.15;
  const normalized = raw > 1 ? raw / 100 : raw;
  if (normalized < 0 || normalized > 1) return 0.15;
  return normalized;
};

export const buildCheckoutBlockReason = ({ selectedTicket, selectedEvent, hasCheckoutErrors }) => {
  if (!selectedTicket) {
    return (selectedEvent?.items || []).length === 0
      ? "Este evento todavía no tiene tickets habilitados para la venta."
      : "Seleccioná un ticket para continuar.";
  }
  if (isEventSoldOut(selectedEvent)) return "Este evento está SOLD OUT. No se pueden comprar más entradas.";
  if (hasCheckoutErrors) return "Completá correctamente los datos del titular para continuar.";
  return "";
};

export const buildOrderPayload = ({ publicTenant, selectedEvent, selectedTicket, quantity, method, selectedSellerCode, checkoutForm, userNow }) => ({
  tenant_id: publicTenant,
  event_slug: selectedEvent.slug,
  sale_item_id: selectedTicket.id,
  quantity,
  payment_method: method || "cash",
  seller_code: selectedSellerCode || undefined,
  buyer: {
    full_name: String(checkoutForm.fullName || "").trim(),
    dni: String(checkoutForm.dni || "").trim(),
    address: String(checkoutForm.address || "").trim(),
    province: String(checkoutForm.province || "").trim(),
    postal_code: String(checkoutForm.postalCode || "").trim(),
    birth_date: String(checkoutForm.birthDate || "").trim(),
    email: userNow?.email || checkoutForm.email,
    phone: String(checkoutForm.phone || "").replace(/\D/g, ""),
  },
});
