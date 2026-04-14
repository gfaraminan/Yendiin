# Frontend Ticketera Entradas (React + Vite)

SPA principal del proyecto Ticketera Entradas.

## Scripts

- `npm run dev`: desarrollo local (Vite).
- `npm run build`: build producción.
- `npm run preview`: previsualización de build.
- `npm run lint`: lint del frontend.

## Estructura mínima

- `src/main.jsx`: bootstrap React.
- `src/App.jsx`: aplicación principal y orquestación de vistas/estados.
- `src/components/`: componentes reutilizables (carousel, footer, modales).
- `src/app/constants.js`: constantes visuales y defaults.
- `src/app/helpers.js`: helpers de consumo API y utilidades de UI.

## Integración con backend

La app asume backend disponible bajo mismo host con rutas `/api/*`:

- `/api/public/*` para catálogo.
- `/api/auth/*` para autenticación.
- `/api/orders/*` para flujo de compra/tickets.
- `/api/producer/*` para panel productor.
- `/api/payments/*` para checkout Mercado Pago.

## Variables de entorno (frontend)

- `VITE_GOOGLE_CLIENT_ID`: Client ID de Google Identity Services.

## Build y publicación

El backend FastAPI sirve la SPA desde `static/` (o `app/static/`).
Por lo tanto, en despliegue debe existir un `index.html` de build en esa ubicación.
