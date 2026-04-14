BEGIN;

ALTER TABLE public.orders
  ADD COLUMN IF NOT EXISTS buyer_phone TEXT;

ALTER TABLE public.tickets
  ADD COLUMN IF NOT EXISTS buyer_phone TEXT;

COMMIT;
