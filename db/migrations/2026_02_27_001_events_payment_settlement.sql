ALTER TABLE public.events
  ADD COLUMN IF NOT EXISTS settlement_mode TEXT;

ALTER TABLE public.events
  ADD COLUMN IF NOT EXISTS payout_alias TEXT;

ALTER TABLE public.events
  ADD COLUMN IF NOT EXISTS cuit TEXT;

ALTER TABLE public.events
  ADD COLUMN IF NOT EXISTS mp_collector_id TEXT;

UPDATE public.events
SET settlement_mode = 'manual_transfer'
WHERE settlement_mode IS NULL OR settlement_mode = '';
