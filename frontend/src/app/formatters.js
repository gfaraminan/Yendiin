export const formatMoneyAr = (n) => {
  const value = Number(n || 0);
  try {
    return `$${new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(value)}`;
  } catch {
    return `$${value}`;
  }
};

export const parseCoordinate = (value) => {
  if (value == null) return null;
  const raw = String(value).trim();
  if (!raw) return null;
  const normalized = raw.replace(",", ".");
  const num = Number(normalized);
  return Number.isFinite(num) ? num : null;
};

export const getEventCoordinates = (ev) => {
  const lat = parseCoordinate(ev?.lat ?? ev?.latitude);
  const lng = parseCoordinate(ev?.lng ?? ev?.longitude);
  if (lat == null || lng == null) return null;
  return { lat, lng };
};

export const buildUberLink = (ev) => {
  if (!ev) return null;
  const coords = getEventCoordinates(ev);
  if (!coords) return null;

  const params = new URLSearchParams({ action: "setPickup" });
  params.set("dropoff[latitude]", String(coords.lat));
  params.set("dropoff[longitude]", String(coords.lng));
  params.set("dropoff[nickname]", ev.title || "Evento");

  return `https://m.uber.com/ul/?${params.toString()}`;
};

export const buildEventGoogleMapsLink = (ev) => {
  const coords = getEventCoordinates(ev);
  if (!coords) return null;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${coords.lat},${coords.lng}`)}`;
};

export const normalizeErrorDetail = (data, response, fallbackMessage) => {
  const detail = String(data?.detail || data?.message || "").trim();

  if (detail) {
    if (/<!doctype html|<html/i.test(detail)) {
      const status = response?.status ? ` (HTTP ${response.status})` : "";
      return `Servicio temporalmente no disponible${status}. Intentá nuevamente en unos minutos.`;
    }
    return detail.length > 280 ? `${detail.slice(0, 280)}…` : detail;
  }

  if (response?.status && response.status >= 500) {
    return `Servicio temporalmente no disponible (HTTP ${response.status}). Intentá nuevamente en unos minutos.`;
  }

  return fallbackMessage;
};
