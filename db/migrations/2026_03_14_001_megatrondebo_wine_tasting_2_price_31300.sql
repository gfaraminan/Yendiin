-- Ajuste de precio solicitado para tenant/evento puntual.
-- Nuevo precio: 31300 (price_cents).

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name = 'sale_items'
  ) THEN
    UPDATE public.sale_items
       SET price_cents = 31300,
           updated_at = NOW()
     WHERE tenant = 'megatrondebo'
       AND event_slug = 'wine-tasting-2';
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name = 'ticket_types'
  ) THEN
    UPDATE public.ticket_types
       SET price_cents = 31300
     WHERE tenant = 'megatrondebo'
       AND event_slug = 'wine-tasting-2';
  END IF;
END $$;
