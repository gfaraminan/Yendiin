BEGIN;

CREATE OR REPLACE FUNCTION public.orders_autofill_bar_fields()
RETURNS trigger AS $$
DECLARE
  ev_tenant text;
BEGIN
  -- Si es barra (bar_slug presente), marcamos source
  IF NEW.bar_slug IS NOT NULL THEN
    IF NEW.source IS NULL OR NEW.source = '' THEN
      NEW.source := 'bar';
    END IF;

    -- Autocompletar producer_tenant desde events si falta
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

DROP TRIGGER IF EXISTS trg_orders_autofill_bar_fields ON public.orders;

CREATE TRIGGER trg_orders_autofill_bar_fields
BEFORE INSERT OR UPDATE ON public.orders
FOR EACH ROW
EXECUTE FUNCTION public.orders_autofill_bar_fields();

COMMIT;
