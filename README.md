# Ticketera Entradas


## Documentación para cliente y soporte IA

- Manual completo para cliente (funcionalidades, manuales y FAQ): `docs/CLIENTE_MANUAL_COMPLETO.md`.
- Playbook para agente de IA de soporte: `docs/AI_SUPPORT_PLAYBOOK.md`.

---

Documentación integral del repositorio: arquitectura, funcionamiento, módulos, relaciones de datos, operación, despliegue y mantenimiento.

## 1) Qué es este proyecto

Ticketera Entradas es una plataforma para:

- Publicar eventos y administrar su catálogo de venta (entradas y otros ítems) desde un panel de productor.
- Vender entradas al público desde un frontend SPA en React.
- Cobrar mediante Mercado Pago.
- Emitir activos post-compra (tickets/QR/PDF) y permitir consulta de compras.
- Operar en una base PostgreSQL compartida con otros módulos (ej. barra), usando un modelo común en `orders` + `order_items`.

El backend está implementado con FastAPI y la capa web en React + Vite.

---

## 2) Arquitectura general

### Backend

- Punto de entrada: `app/main.py`.
- Framework: FastAPI.
- Middleware:
  - Session cookie (`SessionMiddleware`),
  - fallback SPA para deep links (`/evento/<slug>`), evitando 404 cuando se atiende con frontend estático.
- Montajes estáticos:
  - `/static/uploads` (assets subidos, especialmente flyers y PDFs generados),
  - `/uploads` por compatibilidad,
  - `/` montado al build de la SPA (`static/` o `app/static/`).

### Frontend

- App React en `frontend/` (Vite).
- Entrada principal en `frontend/src/main.jsx`.
- App principal en `frontend/src/App.jsx`.
- Consume APIs bajo `/api/*` (auth, catálogo, órdenes, productor, pagos).

### Base de datos

- PostgreSQL (psycopg3 en runtime).
- Conexión centralizada en `app/db.py`.
- Migraciones SQL idempotentes en `db/migrations/`.

---

## 3) Mapa funcional por módulos

### 3.1 Autenticación y sesión

Router: `app/routers/auth.py` (prefijo `/api/auth`).

Flujos implementados:

- Login Google (`POST /api/auth/google`) validando `id_token` contra Google tokeninfo.
- Magic link por email:
  - inicia (`POST /api/auth/email/start`),
  - verifica (`GET /api/auth/email/verify?token=...`).
- Logout (`POST /api/auth/logout`).
- Compatibilidad de sesión (`GET /api/auth/me`) expuesta en `app/main.py`.

Persistencia de sesión: cookie firmada por `SESSION_SECRET`.

### 3.2 Portal público

Router: `app/routers/public.py` (prefijo `/api/public`).

Responsabilidades:

- Config pública (`/config`) para frontend (ej. Google client id).
- Listado de eventos y categorías (`/events`, `/categories`).
- Detalle de evento (`/events/{slug}`).
- Listado de ítems de venta (`/sale-items`).
- Endpoints de sesión pública heredados (`/me`, `/logout`, `/login/google`).

Contrato runtime recomendado de `GET /api/public/config` (mantiene compatibilidad legacy):

- `google_client_id`: client id para Google Identity.
- `default_public_tenant` y `public_tenant`: tenant público default.
- `branding`: objeto de marca runtime (por ejemplo `name`, `support_email`, `legal_name`).
- `legal`: links legales runtime (`termsUrl`, `privacyUrl`, `refundsUrl`, etc.).
- `features` y `feature_flags`: flags de frontend (mismo contenido para compatibilidad).
- Campos legacy conservados: `brand_name` y `brand`.

### 3.3 Backoffice de productor

Router: `app/routers/producer.py` (prefijo `/api/producer`).

Responsabilidades:

- Gestión de eventos:
  - listar, crear, editar, activar/desactivar,
  - endpoints legacy y nuevos (`/events`, `/events/mine`, `/events/update`, `/events/toggle`).
- Gestión de catálogo por evento:
  - sale-items/sales-items (nomenclatura dual por compatibilidad),
  - CRUD de ítems y stock.
- Gestión de vendedores:
  - sellers/vendors (también dual por compatibilidad),
  - CRUD de vendedores/códigos.
- Punto de venta (taquilla):
  - emisión manual de venta presencial (`POST /api/producer/events/{slug}/pos-sale`),
  - crea orden pagada + emite tickets al instante con trazabilidad de operador y medio de pago.
- Upload de flyers/imágenes (`/upload/flyer`, `/events/{slug}/flyer`).

### 3.4 Órdenes y activos del comprador

Router: `app/routers/orders.py` (prefijo `/api/orders`).

Responsabilidades:

- Crear orden (`/create`).
- Consultar tickets del usuario (`/my-tickets`).
- Consultar assets (`/my-assets`).
- Descargar PDF de tickets (`/tickets.pdf`).
- Transferir orden (`/transfer-order`).
- Validar operación (`/validate`).

### 3.5 Pagos Mercado Pago

Router: `app/routers/payments_mp.py` (prefijo `/api/payments`).

Responsabilidades:

- Crear preferencia (`POST /api/payments/mp/create-preference`).
- Sincronizar orden post-pago (`GET /api/payments/mp/sync-order`).
- Webhook (`POST /api/payments/mp/webhook`).

El módulo incluye:

- Cálculo de comisión/plataforma,
- Integración con collector IDs por entorno,
- Emisión de PDF/QR y disparo de email en eventos de pago (según configuración).

### 3.6 Tickets/PDF

Router: `app/routers/tickets.py`.

Descarga de PDF por ticket y por orden:

- `GET /api/tickets/{ticket_id}/pdf`
- `GET /api/tickets/orders/{order_id}/pdf`

### 3.7 Dashboard público de métricas por evento

Router: `app/routers/public_event_stats.py`.

- `GET /public/event?event_slug=<slug>&key=<public_stats_key>`
- Renderiza una vista HTML simple con cantidad de entradas vendidas (PAID).

---

## 4) Relación entre entidades (modelo de negocio)

Relaciones principales en el modelo actual:

- `events (slug)` 1..N `sale_items (event_slug)`
- `events (slug)` 1..N `orders (event_slug)`
- `orders (id)` 1..N `order_items (order_id)`
- `orders (id)` 1..N `tickets (order_id)`
- `events` + `public_stats_key` habilitan visualización pública de métricas.

Además, `orders` usa campos para unificar dominios:

- `source = 'tickets' | 'bar'`
- `producer_tenant` para filtrar dashboard por productor.

El detalle ER y contratos compartidos se amplía en:

- `docs/README_DB.md`
- `docs/db_diagram.md`
- PDFs de contrato en `docs/`.

---

## 5) Variables de entorno

### Núcleo aplicación

- `DATABASE_URL` (obligatoria): conexión PostgreSQL.
- `SESSION_SECRET`: firma de sesión.
- `DEFAULT_TENANT`: tenant por defecto.
- `APP_BASE_URL`: base pública para links (magic link, navegación post-email).
- `UPLOAD_DIR`: directorio físico de subidas (default `/var/data/uploads`).

### Auth

- `GOOGLE_CLIENT_ID` o `VITE_GOOGLE_CLIENT_ID`.
- `MAGICLINK_SECRET`.
- `MAGICLINK_TTL_MINUTES`.

### Email

- `EMAIL_CONFIRM_ENABLED`.
- `EMAIL_CONFIRM_MAX_ATTEMPTS`.
- `EMAIL_ATTACH_PDF`.
- `EMAIL_ATTACH_QR_PNG`.
- `EMAIL_MAX_QR_ATTACHMENTS`.
- `ORDER_EMAIL_LOG_TABLE`.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`.
- `EMAIL_FROM` o `MAIL_FROM`.

### Mercado Pago

- `MP_ACCESS_TOKEN` (token de la app marketplace, *Develop* o *Producción* según entorno).
- `MP_API_BASE` (default `https://api.mercadopago.com`).
- `MP_WEBHOOK_SECRET`.
- `SERVICE_CHARGE_PCT` (ej. `0.15` para 15%).
- `MP_OAUTH_CLIENT_ID` (de la app creada en Mercado Pago).
- `MP_OAUTH_CLIENT_SECRET` (de la app creada en Mercado Pago).
- `MP_OAUTH_REDIRECT_URI` (callback público, ej. `https://tu-dominio.com/oauth/callback`).
- `MP_OAUTH_AUTH_URL` (opcional, default oficial de MP).
- `MP_USE_SELLER_ACCESS_TOKEN` (default `true`: para split usa el access token OAuth del seller, persistido por `user_id`).
- `MP_COLLECTOR_ID_DEFAULT` + posibles variantes por tenant/evento.
- `MP_WEBHOOK_RESEND_EMAIL` (si se habilita reenvío por webhook).
- `MIS_TICKETS_PATH` (path de redirección en links al usuario).

Checklist rápido de validación de Split MP:

1. Configurar variables de entorno del entorno (`develop` o `production`).
2. Ingresar como productor y conectar cuenta vendedora con `GET /api/payments/mp/oauth/start?tenant=default`.
3. Guardar evento con `settlement_mode = mp_split` y `mp_collector_id` conectado.
4. Verificar salud con `GET /api/payments/mp/split-health` (requiere sesión o header `x-producer` en dev; debe devolver `ok: true`).
5. Crear preferencia en modo prueba: `POST /api/payments/mp/create-preference?tenant=default&dry_run=true`.
6. Confirmar en la respuesta que `split_applied = true`, `split_collector_id` presente y `marketplace_fee` en `preference`.

Notas para revisar el split en la `preference`:

- Si `MP_USE_SELLER_ACCESS_TOKEN=true` (default), el split se envía autenticando con token OAuth del seller: la `preference` incluye `marketplace_fee` (si corresponde) y puede omitir `collector_id` explícito.
- Si `MP_USE_SELLER_ACCESS_TOKEN=false`, la `preference` debe incluir `collector_id` y, si corresponde, `marketplace_fee`.
- En ambos casos, el endpoint devuelve `split_auth_mode` (`seller_access_token` o `platform_token`) para verificar qué camino se aplicó.

---

## 6) Puesta en marcha local

## Requisitos

- Python 3.11+
- Node 20+
- PostgreSQL 14+

### Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configurar variables mínimas:

```bash
export DATABASE_URL='postgresql://user:pass@localhost:5432/ticketera'
export SESSION_SECRET='cambiar-esto'
export APP_BASE_URL='http://localhost:8000'
```

Aplicar migraciones:

```bash
python db/apply_migrations.py
```

Levantar API:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm ci
npm run build
```

El build queda en `frontend/dist`. Este repo usa normalmente la carpeta `static/` para servir SPA desde FastAPI.

---

## 7) Despliegue (Render)

Existe un `docs/render.yaml` como referencia.

Puntos críticos:

- Persistencia de uploads: montar disk y apuntar `UPLOAD_DIR`.
- HTTPS y cookie segura: el backend activa `https_only` cuando detecta entorno Render.
- Build frontend: asegurar que `static/index.html` exista al iniciar backend.

---

## 8) Estructura del repositorio

- `app/`: backend principal.
- `app/routers/`: módulos de API.
- `db/migrations/`: migraciones SQL fuente de verdad.
- `frontend/`: SPA React.
- `static/`: build frontend servido por FastAPI.
- `uploads/`: archivos estáticos de ejemplo/locales.
- `docs/`: contratos, diagrama, notas de base y despliegue.
- `trash/` y `*/trash/`: histórico técnico (no productivo).

---

## 9) Convenciones y notas operativas

- Evitar usar archivos en `trash/` como fuente funcional.
- Tomar `app/main.py` y `app/routers/*.py` (no trash) como implementación vigente.
- Mantener migraciones nuevas en `db/migrations/` como SQL idempotente.
- Mantener compatibilidad de rutas legacy cuando haya frontend histórico en producción.

---

## 10) Roadmap de documentación sugerido

Para alcanzar una documentación “audit-ready”, próximos entregables recomendados:

1. OpenAPI exportado y versionado en `docs/openapi.json`.
2. Diccionario de datos por tabla/campo con tipos y ownership.
3. Diagramas de secuencia por flujo:
   - compra,
   - webhook,
   - emisión de tickets,
   - login magic link.
4. Runbook operativo:
   - incidentes MP,
   - incidentes SMTP,
   - recuperación por migraciones.
5. Política de versionado de contrato compartido con Ticketera Barra.


---

## Support AI

Se agregó un agente de soporte IA en backend con endpoint protegido por feature flag.

### Variables de entorno

- `SUPPORT_AI_ENABLED` (default `false`): habilita `POST /api/support/ai/chat`.
- `SUPPORT_AI_MODEL` (default `gpt-5-mini`): modelo para Responses API.
- `OPENAI_API_KEY`: credencial OpenAI (no se loguea).
- `OPENAI_VECTOR_STORE_ID` (opcional): vector store para `file_search`.
- `SUPPORT_AI_TIMEOUT_S` (default `45`): timeout en segundos para Responses API.
- `SUPPORT_AI_STAFF_EMAILS` (obligatoria en staging/prod): lista separada por comas de emails staff autorizados (ej: `ceo@ticketpro.com,owner@ticketpro.com,ops@ticketpro.com`).

### Indexación de documentación (RAG)

Script:

```bash
python scripts/ai/create_or_update_vector_store.py
```

El script detecta automáticamente la carpeta de documentación desde enlaces del `README.md` (fallback: `docs/`), crea vector store si hace falta, evita re-subir archivos cuando ya existe el mismo nombre+tamaño, y muestra el `vector_store_id` final.

### Pantalla interna (staff)

- Se agregó una pantalla interna **Administrador** en frontend (tab en header), visible solo para usuarios staff habilitados.
- El backend exige usuario staff por email (`SUPPORT_AI_STAFF_EMAILS`) y responde `403` si no está autorizado.
- En Administrador tenés: Soporte IA + dashboard TicketPro (tickets, barra, usuarios, filtros por evento) + operaciones de crear/transferir eventos.
- También incluye operaciones admin en la misma pestaña:
  - `GET /api/support/ai/admin/dashboard` (eventos activos/totales, órdenes pagas, revenue total)
  - `GET /api/support/ai/admin/events` (listado rápido para operar)
  - `POST /api/support/ai/admin/events/create` (crear evento para un cliente, incluso si aún no tiene cuenta)
  - `POST /api/support/ai/admin/events/transfer` (transferir evento a otro owner)
  - `POST /api/support/ai/admin/events/pause` (pausar/reactivar evento)
  - `POST /api/support/ai/admin/events/delete` (eliminar evento con confirmación `ELIMINAR`)
  - `GET/POST /api/support/ai/admin/events/delete-requests*` (revisar solicitudes de productores y aprobar/rechazar eliminación)
  - `GET/POST /api/support/ai/admin/sale-items*` (cargar y gestionar sale items desde el modal de creación en Admin)
  - `GET /api/support/ai/admin/bar-sales` (detalle de pedidos de barra por evento)

### Diagnóstico rápido (antes de probar)

- Endpoint de estado: `GET /api/support/ai/status`
- Te confirma si está habilitado, si tu sesión es staff y si están configuradas `OPENAI_API_KEY`/`OPENAI_VECTOR_STORE_ID`.

### Endpoint

`POST /api/support/ai/chat`

Body:

```json
{
  "message": "Necesito ayuda con mi orden ORD-123",
  "tenant_id": "default",
  "user_role_hint": "buyer",
  "context": {"channel": "web", "confirm_resend_order_email": false}
}
```

Ejemplo curl:

```bash
curl -X POST http://localhost:8000/api/support/ai/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Necesito reenviar el email de mi orden ORD-123 a comprador@mail.com",
    "tenant_id": "default",
    "user_role_hint": "support",
    "context": {"confirm_resend_order_email": true}
  }'
```

Ejemplos de consultas reales:

- "¿Cuántas entradas vendimos hoy para el evento river-vs-boca?" (también funciona por nombre, sin conocer el slug exacto)
- "¿Cuántos tickets vendimos hoy entre todos los eventos?"
- "¿Cuánto cobramos de service charge en los últimos 15 días?"

Response (el `trace_id` coincide con el id de Responses API para trazabilidad):

> Nota: para ejecutar `resend_order_email`, además de `order_id` + `to_email`, debe haber confirmación explícita (por `context.confirm_resend_order_email=true` o texto como "confirmo reenviar").

```json
{
  "answer": "...",
  "trace_id": "resp_...",
  "used_tools": ["get_order"],
  "citations": []
}
```


### Checklist express para probar hoy

1. Configurar env vars: `SUPPORT_AI_ENABLED=true`, `SUPPORT_AI_STAFF_EMAILS=<tu email>`, `OPENAI_API_KEY`, `OPENAI_VECTOR_STORE_ID` (opcional).
2. Loguearte con ese email en la app.
3. Abrir tab **Administrador** en el header.
4. En “Crear evento”, podés abrir el mismo modal completo del módulo Productor y asignarlo a un email (aunque aún no tenga cuenta).
5. Verificar en "Estado de Soporte IA" que `enabled=true` y `staff=true`.
6. Probar preguntas:
   - "¿Cuántas entradas vendimos hoy para el evento <slug>?"
   - "¿Cuántos tickets vendimos hoy entre todos los eventos?"
   - "¿Cuánto cobramos de service charge en los últimos 15 días?"
