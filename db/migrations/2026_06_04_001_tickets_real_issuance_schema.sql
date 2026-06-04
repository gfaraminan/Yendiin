BEGIN;

-- Bring older Yendiin tickets tables up to the persisted-ticket contract used by
-- admin sold-ticket lists, producer lists, QR validation and MP finalization.
ALTER TABLE public.tickets
  ADD COLUMN IF NOT EXISTS producer_tenant TEXT,
  ADD COLUMN IF NOT EXISTS qr_token TEXT,
  ADD COLUMN IF NOT EXISTS qr_payload TEXT,
  ADD COLUMN IF NOT EXISTS used_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS buyer_name TEXT,
  ADD COLUMN IF NOT EXISTS buyer_email TEXT,
  ADD COLUMN IF NOT EXISTS buyer_dni TEXT,
  ADD COLUMN IF NOT EXISTS buyer_address TEXT,
  ADD COLUMN IF NOT EXISTS buyer_province TEXT,
  ADD COLUMN IF NOT EXISTS buyer_postal_code TEXT,
  ADD COLUMN IF NOT EXISTS buyer_birth_date TEXT;


-- Hydrate already-issued tickets with order-level buyer identity when available.
UPDATE public.tickets t
SET
  buyer_name = COALESCE(NULLIF(t.buyer_name, ''), NULLIF(o.buyer_name, '')),
  buyer_email = COALESCE(NULLIF(t.buyer_email, ''), NULLIF(o.buyer_email, ''))
FROM public.orders o
WHERE t.order_id::text = o.id::text
  AND (
    (t.buyer_name IS NULL OR t.buyer_name = '')
    OR (t.buyer_email IS NULL OR t.buyer_email = '')
  );

CREATE INDEX IF NOT EXISTS idx_tickets_event
  ON public.tickets (tenant_id, event_slug);

CREATE INDEX IF NOT EXISTS idx_tickets_order
  ON public.tickets (order_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tickets_qr_token
  ON public.tickets (qr_token)
  WHERE qr_token IS NOT NULL AND qr_token <> '';

COMMIT;
