# Ticketera – Base de Datos (PostgreSQL)

Este documento describe la estructura lógica, funciones, triggers y contratos compartidos
entre los módulos:

- 🎟️ Ticketera Entradas
- 🍺 Ticketera Barra

Ambos servicios comparten **la misma base PostgreSQL**.

---

## 1. Principios de diseño

- Una **orden (orders)** puede provenir de:
  - `source = 'tickets'` → venta de entradas
  - `source = 'bar'` → venta de barra
- El **dashboard de productor** se basa SIEMPRE en:
  - `event_slug`
  - `producer_tenant`
- El comprador (mail / cuenta) **NO define** la visibilidad del productor.

---

## 2. Tablas principales

### events
Define el evento y su productor.

Campos clave:
- `slug` (PK lógico)
- `tenant` → **productor dueño del evento**
- `tenant_id` → entorno (default, prod, etc)

---

### orders
Órdenes unificadas (entradas + barra).

Campos relevantes:
- `id` (UUID)
- `event_slug`
- `producer_tenant`
- `source` → `tickets | bar`
- `bar_slug` (solo barra)
- `status` → `PENDING | PAID | CANCELLED`
- `total_cents`
- `total_amount`
- `created_at`

---

### order_items
Detalle de productos vendidos (barra o entradas).

Campos:
- `order_id`
- `name`
- `kind` → `ticket | drink | food`
- `qty`
- `total_amount`

---

### tickets
Tickets individuales emitidos.

Campos:
- `event_slug`
- `sale_item_id`
- `status`

---

### sale_items
Catálogo de entradas o productos.

Campos:
- `tenant`
- `event_slug`
- `name`
- `kind`
- `price_cents`

---

## 3. Triggers y funciones

### Trigger: `trg_orders_autofill_bar_fields`

📍 Tabla: `public.orders`  
⏱️ Evento: `BEFORE INSERT OR UPDATE`

#### Objetivo
Asegurar que **todas las ventas de barra**:
- tengan `source = 'bar'`
- tengan `producer_tenant` correctamente asignado

#### Función asociada
```sql
CREATE OR REPLACE FUNCTION public.orders_autofill_bar_fields()
RETURNS trigger AS $$
DECLARE
  ev_tenant text;
BEGIN
  IF NEW.bar_slug IS NOT NULL THEN
    IF NEW.source IS NULL OR NEW.source = '' THEN
      NEW.source := 'bar';
    END IF;

    IF NEW.producer_tenant IS NULL OR NEW.producer_tenant = '' THEN
      SELECT tenant INTO ev_tenant
      FROM public.events
      WHERE slug = NEW.event_slug
      LIMIT 1;

      IF ev_tenant IS NOT NULL THEN
        NEW.producer_tenant := ev_tenant;
      END IF;
    END IF;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

---

## 4. Cómo hacer que el panel de productor de Ticketpro vea ventas de barra

Si el panel del productor muestra solo entradas y no barra, el problema casi siempre es de **scoping de órdenes** (owner/evento) y no de UI.

Checklist mínimo para cada orden de barra (`orders`):

1. `event_slug` debe apuntar a un evento real en `events.slug`.
2. `producer_tenant` debe ser el tenant dueño del evento (`events.tenant`).
3. `source` debe ser `bar` (o equivalente detectado por backend).
4. `status` debe quedar en estado pagado (`paid` / `approved`, según contrato vigente).
5. Si usan `bar_slug`, debe persistirse (el trigger lo usa para autocompletar campos).

### SQL de diagnóstico rápido

```sql
-- 1) ¿Hay órdenes de barra sin producer_tenant?
SELECT id, event_slug, source, bar_slug, producer_tenant, tenant_id, status
FROM orders
WHERE (source ILIKE 'bar%' OR bar_slug IS NOT NULL)
  AND COALESCE(NULLIF(TRIM(producer_tenant), ''), '') = ''
ORDER BY created_at DESC
LIMIT 100;

-- 2) ¿producer_tenant coincide con el owner del evento?
SELECT o.id,
       o.event_slug,
       o.producer_tenant AS order_owner,
       e.tenant          AS event_owner,
       o.source,
       o.status,
       o.created_at
FROM orders o
JOIN events e ON e.slug = o.event_slug
WHERE (o.source ILIKE 'bar%' OR o.bar_slug IS NOT NULL)
  AND COALESCE(o.producer_tenant, '') <> COALESCE(e.tenant, '')
ORDER BY o.created_at DESC
LIMIT 100;

-- 3) ¿Hay ventas de barra aprobadas para un evento puntual?
SELECT o.event_slug,
       COUNT(*)                                           AS bar_orders,
       COALESCE(SUM(o.total_cents), 0)                    AS bar_cents
FROM orders o
WHERE (o.source ILIKE 'bar%' OR o.bar_slug IS NOT NULL)
  AND lower(COALESCE(o.status, '')) IN ('paid', 'approved')
  AND o.event_slug = :event_slug
GROUP BY o.event_slug;
```

### Si el servicio de barra no setea owner

Asegurar que esté aplicada la migración del trigger `trg_orders_autofill_bar_fields` (`db/migrations/2026_02_07_003_orders_autofill_bar_trigger.sql`). Ese trigger completa `source='bar'` y `producer_tenant` desde `events.tenant` cuando la orden llega con `bar_slug`.

### Regla de integración recomendada (entre servicios)

Al crear orden de barra en el servicio de barra:

- resolver primero el evento por `event_slug`;
- tomar `owner = events.tenant`;
- insertar `orders.producer_tenant = owner` y `orders.source = 'bar'`;
- luego confirmar pago y actualizar `orders.status` a estado pagado.

Con esto, el dashboard del productor en Ticketpro puede consolidar entradas + barra sobre la misma base compartida.
