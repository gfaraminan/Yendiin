BEGIN;

-- Core tickets table used by MP webhook finalization and /api/orders/my-assets.
-- Idempotent: safe to run multiple times.
CREATE TABLE IF NOT EXISTS public.tickets (
  id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  producer_tenant TEXT,
  event_slug TEXT,
  sale_item_id BIGINT,
  ticket_type TEXT,
  qr_token TEXT NOT NULL,
  qr_payload TEXT,
  status TEXT NOT NULL DEFAULT 'valid',
  buyer_phone TEXT,
  buyer_dni TEXT,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.tickets
  ADD COLUMN IF NOT EXISTS order_id TEXT,
  ADD COLUMN IF NOT EXISTS tenant_id TEXT DEFAULT 'default',
  ADD COLUMN IF NOT EXISTS producer_tenant TEXT,
  ADD COLUMN IF NOT EXISTS event_slug TEXT,
  ADD COLUMN IF NOT EXISTS sale_item_id BIGINT,
  ADD COLUMN IF NOT EXISTS ticket_type TEXT,
  ADD COLUMN IF NOT EXISTS qr_token TEXT,
  ADD COLUMN IF NOT EXISTS qr_payload TEXT,
  ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'valid',
  ADD COLUMN IF NOT EXISTS buyer_phone TEXT,
  ADD COLUMN IF NOT EXISTS buyer_dni TEXT,
  ADD COLUMN IF NOT EXISTS used_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

UPDATE public.tickets
SET
  tenant_id = COALESCE(NULLIF(tenant_id, ''), 'default'),
  qr_token = COALESCE(NULLIF(qr_token, ''), md5(random()::text || clock_timestamp()::text || COALESCE(id, ''))),
  status = COALESCE(NULLIF(status, ''), 'valid'),
  created_at = COALESCE(created_at, NOW())
WHERE
  tenant_id IS NULL OR tenant_id = ''
  OR qr_token IS NULL OR qr_token = ''
  OR status IS NULL OR status = ''
  OR created_at IS NULL;

ALTER TABLE public.tickets
  ALTER COLUMN order_id SET NOT NULL,
  ALTER COLUMN tenant_id SET NOT NULL,
  ALTER COLUMN qr_token SET NOT NULL,
  ALTER COLUMN status SET NOT NULL,
  ALTER COLUMN created_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tickets_order_id
  ON public.tickets (order_id);

CREATE INDEX IF NOT EXISTS idx_tickets_tenant_order
  ON public.tickets (tenant_id, order_id);

CREATE INDEX IF NOT EXISTS idx_tickets_event_created
  ON public.tickets (event_slug, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tickets_status_created
  ON public.tickets (status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_qr_token
  ON public.tickets (qr_token);

CREATE INDEX IF NOT EXISTS idx_tickets_qr_payload
  ON public.tickets (qr_payload)
  WHERE qr_payload IS NOT NULL AND qr_payload <> '';

COMMIT;
