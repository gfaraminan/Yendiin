BEGIN;

ALTER TABLE public.orders
  ADD COLUMN IF NOT EXISTS external_id TEXT;

-- Índice único para evitar duplicados entre servicios
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_external_id
ON public.orders (external_id)
WHERE external_id IS NOT NULL AND external_id <> '';

COMMIT;
