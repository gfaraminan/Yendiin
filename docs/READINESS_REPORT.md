# Readiness Report — Rebranding / Frontend Evolution

## Ready (green)
- Runtime public config contract exposes `branding`, `legal`, `features`, `feature_flags` with backward compatibility aliases.
- High-risk UX flags added (checkout/producer/staff) with safe defaults.
- `App.jsx` critical helpers extracted incrementally (runtime bootstrap, navigation parsing, shared format/error helpers).
- Checkout and MP preference payload logic isolated in dedicated modules.
- Producer and staff critical payload/response shaping extracted to utilities.
- Tenant normalization bug in public login path fixed (`tenant` query normalization helper).

## Caution (yellow)
- Some flows still orchestrated from `App.jsx`; prepared for phased extraction but not fully modularized.
- Smoke tests are minimal and focus on regression sentinels, not full end-to-end execution.

## Pending manual validation
- Google login and magic-link full browser flow.
- Full checkout path including external MP redirect and return confirmation.
- Producer/staff operations with real tenant/event data.

## Residual risks
- Large legacy `App.jsx` surface still central to many views.
- Environment parity (Render/prod) must include new flags and legal/runtime env values.


## Smoke checks ejecutables
- `scripts/smoke_readiness.sh`
- `node frontend/scripts/smoke_flag_views.mjs`

- `tests/test_public_google_login_tenant_normalization.py` valida normalización de tenant en login Google.
