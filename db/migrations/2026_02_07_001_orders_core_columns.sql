BEGIN;

ALTER TABLE public.orders
  ADD COLUMN IF NOT EXISTS source TEXT;

ALTER TABLE public.orders
  ADD COLUMN IF NOT EXISTS producer_tenant TEXT;

-- total_cents ya lo tenés en tu \d, pero por si cae en otra base:
ALTER TABLE public.orders
  ADD COLUMN IF NOT EXISTS total_cents BIGINT;

-- customer_id ya lo tenés en tu \d, pero por si cae en otra base:
ALTER TABLE public.orders
  ADD COLUMN IF NOT EXISTS customer_id TEXT;

COMMIT;
