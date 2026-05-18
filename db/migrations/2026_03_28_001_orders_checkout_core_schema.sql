BEGIN;

-- Checkout core table/columns. Earlier migrations assumed public.orders already
-- existed; this migration makes fresh or partially migrated environments safe.
CREATE TABLE IF NOT EXISTS public.orders (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  event_slug TEXT NOT NULL,
  producer_tenant TEXT,
  items_json JSONB,
  total_cents BIGINT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  payment_method TEXT,
  seller_code TEXT,
  buyer_email TEXT,
  buyer_name TEXT,
  buyer_phone TEXT,
  buyer_dni TEXT,
  buyer_address TEXT,
  buyer_province TEXT,
  buyer_postal_code TEXT,
  buyer_birth_date TEXT,
  auth_provider TEXT,
  auth_subject TEXT,
  customer_id TEXT,
  customer_label TEXT,
  external_id TEXT,
  paid_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.orders
  ADD COLUMN IF NOT EXISTS tenant_id TEXT DEFAULT 'default',
  ADD COLUMN IF NOT EXISTS producer_tenant TEXT,
  ADD COLUMN IF NOT EXISTS items_json JSONB,
  ADD COLUMN IF NOT EXISTS total_cents BIGINT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS payment_method TEXT,
  ADD COLUMN IF NOT EXISTS seller_code TEXT,
  ADD COLUMN IF NOT EXISTS buyer_email TEXT,
  ADD COLUMN IF NOT EXISTS buyer_name TEXT,
  ADD COLUMN IF NOT EXISTS buyer_phone TEXT,
  ADD COLUMN IF NOT EXISTS buyer_dni TEXT,
  ADD COLUMN IF NOT EXISTS buyer_address TEXT,
  ADD COLUMN IF NOT EXISTS buyer_province TEXT,
  ADD COLUMN IF NOT EXISTS buyer_postal_code TEXT,
  ADD COLUMN IF NOT EXISTS buyer_birth_date TEXT,
  ADD COLUMN IF NOT EXISTS auth_provider TEXT,
  ADD COLUMN IF NOT EXISTS auth_subject TEXT,
  ADD COLUMN IF NOT EXISTS customer_id TEXT,
  ADD COLUMN IF NOT EXISTS customer_label TEXT,
  ADD COLUMN IF NOT EXISTS external_id TEXT,
  ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_orders_tenant_id_id
  ON public.orders (tenant_id, id);

CREATE INDEX IF NOT EXISTS idx_orders_event_status_created
  ON public.orders (event_slug, status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_external_id
  ON public.orders (external_id)
  WHERE external_id IS NOT NULL AND external_id <> '';

COMMIT;
