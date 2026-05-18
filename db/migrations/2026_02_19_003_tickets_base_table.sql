BEGIN;

-- Bootstrap tickets table for older migration sequence.
-- Some early migrations ALTER public.tickets before later core schema files run.
CREATE TABLE IF NOT EXISTS public.tickets (
  id TEXT PRIMARY KEY,
  order_id TEXT,
  tenant_id TEXT,
  event_slug TEXT,
  sale_item_id BIGINT,
  qr_token TEXT,
  status TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMIT;
