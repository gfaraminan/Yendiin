-- Elimina sale_item incorrecto de $12 para wine-tasting-2 (tenant inesvidelacorti).
-- Idempotente: si no existe, no hace nada.
-- Mantiene el item válido (precio 36000) sin tocarlo.

DO $$
DECLARE
  v_where TEXT := 'tenant = ''inesvidelacorti'' AND event_slug = ''wine-tasting-2''';
  v_delete_sql TEXT;
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name = 'sale_items'
  ) THEN
    RETURN;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema='public' AND table_name='sale_items' AND column_name='price_cents'
  ) THEN
    v_where := v_where || ' AND COALESCE(price_cents,0) <> 36000 AND (price_cents = 12 OR price_cents = 1200';
  ELSE
    -- Si por alguna razón no existe price_cents, evitamos borrar masivamente.
    RETURN;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema='public' AND table_name='sale_items' AND column_name='name'
  ) THEN
    v_where := v_where || ' OR LOWER(COALESCE(name, '''')) = ''ger''';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema='public' AND table_name='sale_items' AND column_name='item_name'
  ) THEN
    v_where := v_where || ' OR LOWER(COALESCE(item_name, '''')) = ''ger''';
  END IF;

  v_where := v_where || ')';

  v_delete_sql := 'DELETE FROM public.sale_items WHERE ' || v_where;
  EXECUTE v_delete_sql;
END $$;
