-- Fuerza carga base de sale_item para wine-tasting-2 (tenant inesvidelacorti).
-- Objetivo explícito: ENTRADA GENERAL, stock 30, precio 36000.
-- Idempotente: actualiza si existe; si no existe, inserta.

DO $$
DECLARE
  v_cols TEXT[] := ARRAY[]::TEXT[];
  v_vals TEXT[] := ARRAY[]::TEXT[];
  v_sets TEXT[] := ARRAY[]::TEXT[];
  v_created_type TEXT;
  v_updated_type TEXT;
  v_created_expr TEXT := 'EXTRACT(EPOCH FROM NOW())::BIGINT';
  v_updated_expr TEXT := 'EXTRACT(EPOCH FROM NOW())::BIGINT';
  v_insert_sql TEXT;
  v_update_sql TEXT;
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name = 'sale_items'
  ) THEN
    RETURN;
  END IF;

  -- Detectar tipo de created_at/updated_at (timestamp vs epoch bigint).
  SELECT data_type INTO v_created_type
  FROM information_schema.columns
  WHERE table_schema='public' AND table_name='sale_items' AND column_name='created_at'
  LIMIT 1;

  IF COALESCE(v_created_type, '') ILIKE 'timestamp%' THEN
    v_created_expr := 'NOW()';
  END IF;

  SELECT data_type INTO v_updated_type
  FROM information_schema.columns
  WHERE table_schema='public' AND table_name='sale_items' AND column_name='updated_at'
  LIMIT 1;

  IF COALESCE(v_updated_type, '') ILIKE 'timestamp%' THEN
    v_updated_expr := 'NOW()';
  END IF;

  -- UPDATE para forzar datos del item si ya existe.
  v_sets := array_append(v_sets, 'price_cents = 36000');

  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='name') THEN
    v_sets := array_append(v_sets, 'name = ''ENTRADA GENERAL''');
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='kind') THEN
    v_sets := array_append(v_sets, 'kind = ''ticket''');
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='stock_total') THEN
    v_sets := array_append(v_sets, 'stock_total = 30');
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='active') THEN
    v_sets := array_append(v_sets, 'active = TRUE');
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='item_name') THEN
    v_sets := array_append(v_sets, 'item_name = ''ENTRADA GENERAL''');
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='item_type') THEN
    v_sets := array_append(v_sets, 'item_type = ''ticket''');
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='updated_at') THEN
    v_sets := array_append(v_sets, format('updated_at = %s', v_updated_expr));
  END IF;

  v_update_sql := format(
    'UPDATE public.sale_items SET %s WHERE tenant = %L AND event_slug = %L',
    array_to_string(v_sets, ', '),
    'inesvidelacorti',
    'wine-tasting-2'
  );

  EXECUTE v_update_sql;

  -- INSERT si aún no existe el item objetivo.
  IF NOT EXISTS (
    SELECT 1
    FROM public.sale_items
    WHERE tenant = 'inesvidelacorti'
      AND event_slug = 'wine-tasting-2'
  ) THEN
    v_cols := array_append(v_cols, 'tenant');
    v_vals := array_append(v_vals, quote_literal('inesvidelacorti'));

    v_cols := array_append(v_cols, 'event_slug');
    v_vals := array_append(v_vals, quote_literal('wine-tasting-2'));

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='name') THEN
      v_cols := array_append(v_cols, 'name');
      v_vals := array_append(v_vals, quote_literal('ENTRADA GENERAL'));
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='kind') THEN
      v_cols := array_append(v_cols, 'kind');
      v_vals := array_append(v_vals, quote_literal('ticket'));
    END IF;

    v_cols := array_append(v_cols, 'price_cents');
    v_vals := array_append(v_vals, '36000');

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='stock_total') THEN
      v_cols := array_append(v_cols, 'stock_total');
      v_vals := array_append(v_vals, '30');
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='stock_sold') THEN
      v_cols := array_append(v_cols, 'stock_sold');
      v_vals := array_append(v_vals, '0');
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='active') THEN
      v_cols := array_append(v_cols, 'active');
      v_vals := array_append(v_vals, 'TRUE');
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='display_order') THEN
      v_cols := array_append(v_cols, 'display_order');
      v_vals := array_append(v_vals, '0');
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='item_name') THEN
      v_cols := array_append(v_cols, 'item_name');
      v_vals := array_append(v_vals, quote_literal('ENTRADA GENERAL'));
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='item_type') THEN
      v_cols := array_append(v_cols, 'item_type');
      v_vals := array_append(v_vals, quote_literal('ticket'));
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='created_at') THEN
      v_cols := array_append(v_cols, 'created_at');
      v_vals := array_append(v_vals, v_created_expr);
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='sale_items' AND column_name='updated_at') THEN
      v_cols := array_append(v_cols, 'updated_at');
      v_vals := array_append(v_vals, v_updated_expr);
    END IF;

    v_insert_sql := format(
      'INSERT INTO public.sale_items (%s) VALUES (%s)',
      array_to_string(v_cols, ', '),
      array_to_string(v_vals, ', ')
    );

    EXECUTE v_insert_sql;
  END IF;
END $$;
