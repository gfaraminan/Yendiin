# Safety Flags (UX high-risk surfaces)

These flags are **guard rails** for future UI changes. Defaults preserve current production behavior.

- `VITE_FEATURE_ALT_CHECKOUT_UX=false`: enables alternate checkout UI surface.
- `VITE_FEATURE_ALT_PRODUCER_UI=false`: enables alternate producer panel UI.
- `VITE_FEATURE_ALT_STAFF_UI=false`: enables alternate validator/staff POS UI.

Runtime source order:
1. backend `/api/public/config` (`features` / `feature_flags`)
2. `window.__APP_CONFIG__`
3. Vite env fallback

All three flags are wired with default `false`, so current behavior remains active unless explicitly enabled.
