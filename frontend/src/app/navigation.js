export const parseAppLocation = (locationLike = window.location) => {
  const pathname = locationLike?.pathname || "/";
  const search = locationLike?.search || "";

  const eventMatch = pathname.match(/^\/evento\/([^\/?#]+)$/);
  if (eventMatch?.[1]) {
    return {
      type: "event",
      slug: decodeURIComponent(eventMatch[1]),
    };
  }

  const staffMatch = pathname.match(/^\/staff\/evento\/([^\/?#]+)$/);
  if (staffMatch?.[1]) {
    const slug = decodeURIComponent(staffMatch[1]);
    const qs = new URLSearchParams(search);
    const mode = String(qs.get("mode") || "validate").trim().toLowerCase();
    const token = String(qs.get("token") || "").trim();
    return {
      type: "staff",
      slug,
      token,
      mode: mode === "pos" ? "pos" : "validate",
    };
  }

  return { type: "default" };
};
