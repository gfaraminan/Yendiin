# Prompt exacto — Front TicketPro + Conexión completa al Backend

## Inventario exhaustivo de endpoints usados por el frontend

> Convención:
> - Si `fetch` no define método, se asume `GET`.
> - En muchos endpoints el frontend envía `credentials: "include"`.
> - `tenant`/`tenant_id` se envía según endpoint (ambos existen por compatibilidad).

### 1) Auth / sesión
- `POST /api/auth/google`
- `GET /api/auth/me`
- `POST /api/auth/email/start`
- `POST /api/auth/logout`

### 2) Config pública + cartelera
- `GET /api/public/config`
- `GET /api/public/events?tenant=default`
- `GET /api/public/events/{slug}?tenant=default`
- `GET /api/public/sale-items?tenant=default&event_slug={slug}`

### 3) Órdenes cliente / Mis Tickets
- `POST /api/orders/create`
- `GET /api/orders/my-assets?tenant=default`
- `POST /api/orders/cancel-request?tenant=default`
- `POST /api/orders/transfer-order?tenant=default`
- `POST /api/orders/validate`
- `GET /api/orders/tickets.pdf?tenant={tenant}&ids={id1,id2,...}`
- `GET /api/orders/tickets.pdf?tenant={tenant}&ids={id1,id2,...}&deliver=1`
- `GET /api/tickets/orders/{order_id}/pdf`

### 4) Pagos Mercado Pago
- `GET /api/payments/mp/oauth/start?tenant={tenant}`
- `POST /api/payments/mp/create-preference?tenant=default`

### 5) Productor — eventos
- `GET /api/producer/events?tenant_id={tenant_id}`
- `POST /api/producer/events`
- `PUT /api/producer/events/{slug}`
- `POST /api/producer/events/toggle`
- `POST /api/producer/events/sold-out`
- `POST /api/producer/events/delete-request`
- `POST /api/producer/events/{slug}/flyer?tenant_id={tenant_id}`
- `GET /api/producer/dashboard?tenant_id={tenant_id}&event_slug={slug}`
- `GET /api/owner/summary?event={slug}`

### 6) Productor — ticketing operativo
- `GET /api/producer/events/{slug}/sold-tickets?tenant_id={tenant_id}&format=json`
- `POST /api/producer/events/{slug}/tickets/{ticket_id}/cancel?tenant_id={tenant_id}`
- `GET /api/producer/events/{slug}/bar-orders?tenant_id={tenant_id}`
- `GET /api/producer/events/{slug}/seller-sales?tenant_id={tenant_id}`
- `POST /api/producer/events/{slug}/courtesy-issue?tenant_id={tenant_id}`
- `POST /api/producer/events/{slug}/pos-sale?tenant_id={tenant_id}`
- `POST /api/producer/events/{slug}/orders/{order_id}/send-pdf?tenant_id={tenant_id}`
- `POST /api/producer/events/{slug}/staff-link?tenant_id={tenant_id}&mode={qr|pos}`

### 7) Productor/Admin — sale items
- `GET /api/producer/sale-items?tenant_id={tenant_id}&event_slug={slug}`
- `POST /api/producer/sale-items/create?tenant_id={tenant_id}&event_slug={slug}`
- `PUT /api/producer/sale-items/{id}?tenant_id={tenant_id}&event_slug={slug}`
- `DELETE /api/producer/sale-items/{id}?tenant_id={tenant_id}&event_slug={slug}`
- `POST /api/producer/sale-items/toggle`

#### Variante admin staff de sale-items
- `GET /api/support/ai/admin/sale-items?tenant_id={tenant_id}&event_slug={slug}`
- `POST /api/support/ai/admin/sale-items/create?tenant_id={tenant_id}&event_slug={slug}`
- `PUT /api/support/ai/admin/sale-items/{id}?tenant_id={tenant_id}&event_slug={slug}`
- `DELETE /api/support/ai/admin/sale-items/{id}?tenant_id={tenant_id}&event_slug={slug}`
- `POST /api/support/ai/admin/sale-items/toggle`

### 8) Productor — sellers
- `GET /api/producer/sellers?tenant_id={tenant_id}&event_slug={slug}`
- `POST /api/producer/sellers/create`
- `POST /api/producer/sellers/toggle`
- `DELETE /api/producer/sellers/{id}?tenant_id={tenant_id}&event_slug={slug}`

### 9) Productor — audience y campañas
- `GET /api/producer/audience?tenant_id={tenant_id}&event_slug={slug}&date_from={yyyy-mm-dd}&date_to={yyyy-mm-dd}&sale_item_id={id}&q={text}`
- `GET /api/producer/audience/export?tenant_id={tenant_id}&event_slug={slug}&date_from={yyyy-mm-dd}&date_to={yyyy-mm-dd}&sale_item_id={id}&q={text}`
- `GET /api/producer/campaigns?tenant_id={tenant_id}&page=1&page_size=50`
- `POST /api/producer/campaigns`
- `GET /api/producer/campaigns/{campaign_id}?tenant_id={tenant_id}`
- `GET /api/producer/campaigns/{campaign_id}/deliveries?tenant_id={tenant_id}&page=1&page_size=100`
- `POST /api/producer/campaigns/{campaign_id}/send?tenant_id={tenant_id}`

### 10) Staff/Admin (support AI)
- `GET /api/support/ai/status`
- `POST /api/support/ai/chat`
- `GET /api/support/ai/admin/dashboard?tenant_id={tenant_id}&event_slug={optional}`
- `GET /api/support/ai/admin/events?tenant_id={tenant_id}`
- `POST /api/support/ai/admin/events/create`
- `POST /api/support/ai/admin/events/update`
- `POST /api/support/ai/admin/events/transfer`
- `POST /api/support/ai/admin/events/pause`
- `POST /api/support/ai/admin/events/sold-out`
- `POST /api/support/ai/admin/events/service-charge`
- `POST /api/support/ai/admin/events/delete`
- `GET /api/support/ai/admin/events/delete-requests?tenant_id={tenant_id}&status=pending`
- `POST /api/support/ai/admin/events/delete-requests/resolve`
- `GET /api/support/ai/admin/sold-tickets?tenant_id={tenant_id}&event_slug={slug}`
- `GET /api/support/ai/admin/bar-sales?tenant_id={tenant_id}&event_slug={slug}`

---

## Prompt maestro exacto (copiar/pegar)

```txt
Quiero que implementes el frontend completo de TicketPro con paridad funcional total y conexión real al backend existente.
No puedes omitir ninguna funcionalidad actual.

## Objetivo
Reconstruir el front de TicketPro manteniendo:
1) Todos los flujos de negocio actuales.
2) Todos los endpoints actuales.
3) Todas las validaciones de formularios y edge cases.
4) Compatibilidad con payloads legacy.
5) Roles y permisos (público, usuario autenticado, productor, staff/admin).

## Reglas estrictas
- No elimines funcionalidades.
- No rompas contratos API.
- Si detectas inconsistencias entre endpoints, agrega adaptadores de cliente (normalizadores), no rompas UX.
- Mantén soporte mobile y desktop.
- Mantén estados loading/empty/error/success en cada vista.
- Todas las requests autenticadas deben usar credentials: include.

## Vistas y módulos obligatorios
A) Header global
- Branding TicketPro
- Tabs: Cartelera, Mis Tickets, Administrador (solo staff)
- Login/logout

B) Home / Cartelera pública
- Cargar eventos públicos
- Filtros por ciudad/categoría/búsqueda
- Carrusel destacados
- Cards con flyer, fecha, ciudad, venue, precio desde, estado sold out

C) Detalle de evento
- Cargar evento por slug y sale-items del evento
- Mostrar descripción completa, ubicación/mapa, compartir
- Selección de ticket y cantidad

D) Checkout
- Validaciones estrictas:
  - fullName, dni, address, province, postalCode, birthDate, phone, acceptTerms
- Crear orden
- Si pago es Mercado Pago, crear preferencia y redirigir
- Manejar retorno success y refresco de activos

E) Mis Tickets
- Listar activos de usuario (tickets + barra)
- Ver QR
- Descargar QR
- Descargar PDF
- Reenviar PDF por mail
- Solicitar cancelación
- Transferir orden

F) Productor
- Listado de eventos propios
- Dashboard por evento
- Crear/editar evento con:
  - title, slug, start_date, start_time, city, venue, address, lat, lng, description
  - payout_alias, cuit, settlement_mode (manual_transfer/mp_split), mp_collector_id
  - accept_terms
  - upload flyer con preview
- Gestión completa de sale-items (CRUD + toggle)
- Gestión completa de sellers (CRUD + toggle)
- POS ventas en puerta
- Emisión de cortesías
- Reportes: sold tickets, bar orders, seller sales
- Export CSV
- Audience + campañas (listar/crear/enviar/ver entregas)
- Staff links por evento para modo QR o POS

G) Staff / Admin
- Estado support AI y permisos staff
- Dashboard admin global
- Gestión de eventos multi-owner
- Crear/actualizar/transferir/pausar/sold-out/service-charge/delete
- Resolver solicitudes de borrado
- Ver sold tickets y bar sales desde admin
- Chat interno support AI

H) QR Validator / Staff POS
- Input manual y scanner
- Validación de tokens QR
- POS staff con token de acceso

I) Footer y legales
- Términos, privacidad, reembolsos, FAQs
- contacto y redes

## Endpoints que debes usar (sin inventar otros)
### Auth
- POST /api/auth/google
- GET /api/auth/me
- POST /api/auth/email/start
- POST /api/auth/logout

### Público
- GET /api/public/config
- GET /api/public/events?tenant=default
- GET /api/public/events/{slug}?tenant=default
- GET /api/public/sale-items?tenant=default&event_slug={slug}

### Órdenes / Tickets
- POST /api/orders/create
- GET /api/orders/my-assets?tenant=default
- POST /api/orders/cancel-request?tenant=default
- POST /api/orders/transfer-order?tenant=default
- POST /api/orders/validate
- GET /api/orders/tickets.pdf?tenant={tenant}&ids={id1,id2,...}
- GET /api/orders/tickets.pdf?tenant={tenant}&ids={id1,id2,...}&deliver=1
- GET /api/tickets/orders/{order_id}/pdf

### Pagos
- GET /api/payments/mp/oauth/start?tenant={tenant}
- POST /api/payments/mp/create-preference?tenant=default

### Producer eventos
- GET /api/producer/events?tenant_id={tenant_id}
- POST /api/producer/events
- PUT /api/producer/events/{slug}
- POST /api/producer/events/toggle
- POST /api/producer/events/sold-out
- POST /api/producer/events/delete-request
- POST /api/producer/events/{slug}/flyer?tenant_id={tenant_id}
- GET /api/producer/dashboard?tenant_id={tenant_id}&event_slug={slug}
- GET /api/owner/summary?event={slug}

### Producer operaciones
- GET /api/producer/events/{slug}/sold-tickets?tenant_id={tenant_id}&format=json
- POST /api/producer/events/{slug}/tickets/{ticket_id}/cancel?tenant_id={tenant_id}
- GET /api/producer/events/{slug}/bar-orders?tenant_id={tenant_id}
- GET /api/producer/events/{slug}/seller-sales?tenant_id={tenant_id}
- POST /api/producer/events/{slug}/courtesy-issue?tenant_id={tenant_id}
- POST /api/producer/events/{slug}/pos-sale?tenant_id={tenant_id}
- POST /api/producer/events/{slug}/orders/{order_id}/send-pdf?tenant_id={tenant_id}
- POST /api/producer/events/{slug}/staff-link?tenant_id={tenant_id}&mode={qr|pos}

### Sale-items
- GET /api/producer/sale-items?tenant_id={tenant_id}&event_slug={slug}
- POST /api/producer/sale-items/create?tenant_id={tenant_id}&event_slug={slug}
- PUT /api/producer/sale-items/{id}?tenant_id={tenant_id}&event_slug={slug}
- DELETE /api/producer/sale-items/{id}?tenant_id={tenant_id}&event_slug={slug}
- POST /api/producer/sale-items/toggle

### Sellers
- GET /api/producer/sellers?tenant_id={tenant_id}&event_slug={slug}
- POST /api/producer/sellers/create
- POST /api/producer/sellers/toggle
- DELETE /api/producer/sellers/{id}?tenant_id={tenant_id}&event_slug={slug}

### Marketing
- GET /api/producer/audience?tenant_id={tenant_id}&event_slug={slug}&date_from={yyyy-mm-dd}&date_to={yyyy-mm-dd}&sale_item_id={id}&q={text}
- GET /api/producer/audience/export?tenant_id={tenant_id}&event_slug={slug}&date_from={yyyy-mm-dd}&date_to={yyyy-mm-dd}&sale_item_id={id}&q={text}
- GET /api/producer/campaigns?tenant_id={tenant_id}&page=1&page_size=50
- POST /api/producer/campaigns
- GET /api/producer/campaigns/{campaign_id}?tenant_id={tenant_id}
- GET /api/producer/campaigns/{campaign_id}/deliveries?tenant_id={tenant_id}&page=1&page_size=100
- POST /api/producer/campaigns/{campaign_id}/send?tenant_id={tenant_id}

### Support AI / Admin
- GET /api/support/ai/status
- POST /api/support/ai/chat
- GET /api/support/ai/admin/dashboard?tenant_id={tenant_id}&event_slug={optional}
- GET /api/support/ai/admin/events?tenant_id={tenant_id}
- POST /api/support/ai/admin/events/create
- POST /api/support/ai/admin/events/update
- POST /api/support/ai/admin/events/transfer
- POST /api/support/ai/admin/events/pause
- POST /api/support/ai/admin/events/sold-out
- POST /api/support/ai/admin/events/service-charge
- POST /api/support/ai/admin/events/delete
- GET /api/support/ai/admin/events/delete-requests?tenant_id={tenant_id}&status=pending
- POST /api/support/ai/admin/events/delete-requests/resolve
- GET /api/support/ai/admin/sale-items?tenant_id={tenant_id}&event_slug={slug}
- POST /api/support/ai/admin/sale-items/create?tenant_id={tenant_id}&event_slug={slug}
- PUT /api/support/ai/admin/sale-items/{id}?tenant_id={tenant_id}&event_slug={slug}
- DELETE /api/support/ai/admin/sale-items/{id}?tenant_id={tenant_id}&event_slug={slug}
- POST /api/support/ai/admin/sale-items/toggle
- GET /api/support/ai/admin/sold-tickets?tenant_id={tenant_id}&event_slug={slug}
- GET /api/support/ai/admin/bar-sales?tenant_id={tenant_id}&event_slug={slug}

## Contratos de datos mínimos (frontend)
- Event:
  - slug, title, category, city, venue, description
  - start_date, start_time, date_text
  - flyer_url, visibility, active, sold_out
  - settlement_mode, mp_collector_id, payout_alias, cuit, service_charge_pct
- SaleItem:
  - id, event_slug, name, kind, price/price_cents, stock_total, sold, active
- Seller:
  - id, event_slug, code, name, email, active
- Order:
  - id/order_id, status, total_cents, payment_method, created_at
- TicketAsset:
  - ticket_id, order_id, event_slug, sale_item_name, qr_token/qr_payload, status

## Requisitos técnicos de implementación
- Crear API client central con:
  - manejo de errors normalizado
  - parse JSON/text robusto
  - soporte query params consistente
- Agregar normalizadores para payloads legacy.
- Mantener fallback de imágenes.
- Implementar estados resilientes y mensajes accionables.
- Evitar doble envío en acciones críticas (botones disabled + busy).

## Entregables esperados
1) Arquitectura modular por dominio (public, checkout, myTickets, producer, admin, staff).
2) UI Kit reutilizable.
3) Integración backend endpoint por endpoint.
4) Checklist de paridad funcional total.
5) Guía de despliegue y variables de entorno.

Empieza ahora por:
- mapa de vistas/roles,
- mapa de endpoints consumidos por cada vista,
- y plan de implementación por fases para llegar a paridad total sin regresiones.
```
