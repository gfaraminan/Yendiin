# Arquitectura Técnica — Ticketera Entradas

## Vista de capas

1. **Presentación**
   - React SPA (`frontend/`) construida con Vite.
   - Build servido por FastAPI como estático.

2. **API / BFF**
   - FastAPI (`app/main.py`, `app/routers/*`).
   - Maneja autenticación, catálogo, órdenes, pagos, activos y panel productor.

3. **Integraciones externas**
   - Google Identity Services (login).
   - SMTP (envío de magic link y confirmaciones).
   - Mercado Pago (preferencias y webhook).

4. **Persistencia**
   - PostgreSQL único (dominio de entradas + contratos compartidos con barra).
   - Migraciones SQL versionadas en `db/migrations/`.

## Flujo end-to-end de compra

1. Cliente consulta catálogo (`/api/public/events`, `/api/public/events/{slug}`).
2. Cliente selecciona ítems (`sale_items`) y crea orden (`/api/orders/create`).
3. Front solicita preferencia MP (`/api/payments/mp/create-preference`).
4. Usuario paga en MP.
5. MP notifica webhook (`/api/payments/mp/webhook`).
6. Backend sincroniza estado (`PAID`), emite activos (QR/PDF) y opcionalmente envía email.
7. Cliente consulta sus tickets (`/api/orders/my-tickets`) o descarga PDF (`/api/tickets/orders/{order_id}/pdf`).

## Multi-tenant y ownership

- `tenant_id`: separa contexto/ambiente (ej. `default`).
- `producer_tenant`: identifica productor dueño de datos para panel.
- `event_slug`: pivote funcional para catálogo, ventas, tickets y métricas.

## Integridad de datos (idea central)

- `orders` y `order_items` consolidan operaciones para entradas y barra.
- Trigger de autofill (documentado en `docs/README_DB.md`) completa campos de barra cuando aplica.
- El panel de productor filtra por `event_slug + producer_tenant`, no por email del comprador.

## Storage y assets

- Uploads físicos en `UPLOAD_DIR` (default `/var/data/uploads`).
- Exposición pública en backend:
  - `/static/uploads/*` (principal),
  - `/uploads/*` (compatibilidad).
- PDFs de tickets se guardan en `UPLOAD_DIR/tickets`.

## Consideraciones operativas

- Si falta `static/index.html`, backend mantiene API activa pero devuelve error útil en `/`.
- En Render, la cookie de sesión se setea `https_only` automáticamente.
- Recomendación: persistir `UPLOAD_DIR` en disco montado para no perder activos.
