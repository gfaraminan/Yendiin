ALTER TABLE public.events
  ADD COLUMN IF NOT EXISTS service_charge_pct NUMERIC(6,5);

UPDATE public.events
SET service_charge_pct = 0.15
WHERE service_charge_pct IS NULL OR service_charge_pct < 0 OR service_charge_pct > 1;

ALTER TABLE public.events
  ALTER COLUMN service_charge_pct SET DEFAULT 0.15;
