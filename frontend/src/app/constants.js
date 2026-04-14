import { brandConfig } from "../config/brand";

export const EVENT_DRAFT_KEY = "ticketera.newEventDraft.v1";

export const UI = {
  bg: "bg-[#05070f]",
  card: "bg-[#0b1020]/70 border border-white/8 backdrop-blur-md",
  input:
    "bg-neutral-100 text-neutral-900 border border-neutral-300 placeholder:text-neutral-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 dark:bg-white/5 dark:text-white dark:border-white/10 dark:placeholder:text-neutral-500",
  button:
    "bg-indigo-600 hover:bg-indigo-500 transition-all duration-300 shadow-[0_10px_28px_rgba(79,70,229,0.35)]",
  buttonGhost:
    "bg-white/5 hover:bg-white/10 transition-all duration-300 border border-white/10",
};

export const FALLBACK_FLYER =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(`
  <svg xmlns='http://www.w3.org/2000/svg' width='1200' height='800'>
    <defs>
      <linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>
        <stop offset='0' stop-color='#0b0b12'/>
        <stop offset='0.55' stop-color='#141429'/>
        <stop offset='1' stop-color='#4f46e5'/>
      </linearGradient>
    </defs>
    <rect width='1200' height='800' fill='url(#g)'/>
    <circle cx='980' cy='260' r='160' fill='rgba(255,255,255,0.10)'/>
    <circle cx='820' cy='480' r='220' fill='rgba(255,255,255,0.06)'/>
    <text x='80' y='160' fill='rgba(255,255,255,0.78)' font-size='54' font-family='Inter,Arial' font-weight='900'>${String(brandConfig.shortName || "").toUpperCase()}</text>
    <text x='80' y='225' fill='rgba(255,255,255,0.90)' font-size='86' font-family='Inter,Arial' font-weight='900'>${brandConfig.name}</text>
    <text x='80' y='315' fill='rgba(255,255,255,0.55)' font-size='22' font-family='Inter,Arial' font-weight='700'>EVENTO · IMAGEN NO DISPONIBLE</text>
  </svg>
`);
