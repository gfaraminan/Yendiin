-- Ticketpro / Ticketera PostgreSQL schema (estructura solamente, sin datos)
-- Compatible con aplicación en base vacía (Render PostgreSQL)

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =========================
-- TABLES
-- =========================

CREATE TABLE IF NOT EXISTS public.users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  auth_provider TEXT NOT NULL,
  auth_subject TEXT NOT NULL,
  email TEXT,
  name TEXT,
  picture_url TEXT,
  marketing_opt_in BOOLEAN,
  opt_in_timestamp TIMESTAMPTZ,
  opt_in_source TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT users_auth_provider_subject_key UNIQUE (auth_provider, auth_subject)
);

CREATE TABLE IF NOT EXISTS public.events (
  slug TEXT PRIMARY KEY,
  tenant_id TEXT,
  tenant TEXT,
  title TEXT,
  name TEXT,
  starts_at TIMESTAMPTZ,
  ends_at TIMESTAMPTZ,
  active BOOLEAN,
  visibility TEXT NOT NULL DEFAULT 'public',
  settlement_mode TEXT,
  payout_alias TEXT,
  cuit TEXT,
  mp_collector_id TEXT,
  service_charge_pct NUMERIC(6,5) DEFAULT 0.15,
  sold_out BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT events_visibility_check CHECK (visibility IN ('public', 'unlisted'))
);

CREATE TABLE IF NOT EXISTS public.orders (
  id UUID PRIMARY KEY,
  tenant_id TEXT,
  event_slug TEXT NOT NULL,
  status TEXT NOT NULL,
  source TEXT,
  producer_tenant TEXT,
  bar_slug TEXT,
  customer_label TEXT,
  customer_id TEXT,
  seller_code TEXT,
  buyer_phone TEXT,
  buyer_address TEXT,
  buyer_province TEXT,
  buyer_postal_code TEXT,
  buyer_birth_date TEXT,
  total_cents BIGINT,
  total_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'ARS',
  items_json JSONB,
  external_id TEXT,
  pickup_code TEXT,
  qr_token TEXT,
  auth_provider TEXT,
  auth_subject TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  paid_at TIMESTAMPTZ,
  ready_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.order_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id UUID NOT NULL,
  name TEXT,
  kind TEXT,
  qty NUMERIC,
  unit_amount NUMERIC(12,2),
  total_amount NUMERIC(12,2),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.sale_items (
  id TEXT PRIMARY KEY,
  tenant TEXT NOT NULL,
  event_slug TEXT NOT NULL,
  name TEXT,
  kind TEXT,
  item_name TEXT,
  item_type TEXT,
  price_cents INTEGER NOT NULL,
  stock_total INTEGER,
  stock_sold INTEGER NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  display_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.tickets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT,
  event_slug TEXT NOT NULL,
  sale_item_id TEXT,
  order_id UUID,
  status TEXT,
  buyer_phone TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.issued_qr (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id UUID NOT NULL,
  qr_token TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.logs (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  level TEXT,
  event_slug TEXT,
  actor_type TEXT,
  actor_slug TEXT,
  action TEXT,
  detail JSONB
);

CREATE TABLE IF NOT EXISTS public.mp_sellers (
  event TEXT NOT NULL,
  producer_id TEXT NOT NULL,
  access_token TEXT NOT NULL,
  refresh_token TEXT,
  expires_at BIGINT,
  updated_at BIGINT,
  PRIMARY KEY (event, producer_id)
);

CREATE TABLE IF NOT EXISTS public.tenant_settings (
  tenant_id TEXT PRIMARY KEY,
  display_name TEXT,
  brand_color TEXT,
  logo_url TEXT,
  cover_url TEXT,
  links JSONB,
  feature_flags JSONB,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.event_settings (
  event_slug TEXT PRIMARY KEY,
  tenant_id TEXT,
  display_name TEXT,
  brand_color TEXT,
  logo_url TEXT,
  cover_url TEXT,
  links JSONB,
  feature_flags JSONB,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.producer_campaigns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  producer_scope TEXT NOT NULL,
  created_by_user_email TEXT NOT NULL,
  name TEXT,
  subject TEXT NOT NULL,
  body_html TEXT,
  body_text TEXT,
  audience_filters JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'draft',
  recipient_count INTEGER NOT NULL DEFAULT 0,
  suppressed_count INTEGER NOT NULL DEFAULT 0,
  sent_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  sent_at TIMESTAMPTZ,
  last_error TEXT,
  CONSTRAINT producer_campaigns_subject_not_blank CHECK (length(trim(subject)) > 0),
  CONSTRAINT producer_campaigns_body_required CHECK (body_html IS NOT NULL OR body_text IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS public.producer_campaign_deliveries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id UUID NOT NULL,
  tenant_id TEXT NOT NULL,
  producer_scope TEXT NOT NULL,
  email_norm TEXT NOT NULL,
  email_original TEXT NOT NULL,
  contact_name TEXT,
  source_order_id TEXT,
  source_event_slug TEXT,
  delivery_status TEXT NOT NULL DEFAULT 'pending',
  provider_message_id TEXT,
  error_code TEXT,
  error_message TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  sent_at TIMESTAMPTZ,
  CONSTRAINT producer_campaign_deliveries_unique_email UNIQUE (campaign_id, email_norm)
);

CREATE TABLE IF NOT EXISTS public.producer_contact_unsubscribes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope TEXT NOT NULL DEFAULT 'producer',
  tenant_id TEXT,
  producer_scope TEXT NOT NULL DEFAULT '',
  email_norm TEXT NOT NULL,
  email_original TEXT,
  reason TEXT,
  source TEXT NOT NULL DEFAULT 'public_link',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT producer_contact_unsubscribes_scope_check
    CHECK ((scope = 'global' AND producer_scope = '') OR (scope = 'producer' AND producer_scope <> ''))
);

-- =========================
-- ALTER TABLE (PK/FK/constraints)
-- =========================

ALTER TABLE public.orders
  ADD CONSTRAINT orders_event_slug_fkey
  FOREIGN KEY (event_slug) REFERENCES public.events(slug);

ALTER TABLE public.order_items
  ADD CONSTRAINT order_items_order_id_fkey
  FOREIGN KEY (order_id) REFERENCES public.orders(id) ON DELETE CASCADE;

ALTER TABLE public.sale_items
  ADD CONSTRAINT sale_items_event_slug_fkey
  FOREIGN KEY (event_slug) REFERENCES public.events(slug) ON DELETE CASCADE;

ALTER TABLE public.tickets
  ADD CONSTRAINT tickets_event_slug_fkey
  FOREIGN KEY (event_slug) REFERENCES public.events(slug) ON DELETE CASCADE;

ALTER TABLE public.tickets
  ADD CONSTRAINT tickets_sale_item_id_fkey
  FOREIGN KEY (sale_item_id) REFERENCES public.sale_items(id) ON DELETE SET NULL;

ALTER TABLE public.tickets
  ADD CONSTRAINT tickets_order_id_fkey
  FOREIGN KEY (order_id) REFERENCES public.orders(id) ON DELETE SET NULL;

ALTER TABLE public.issued_qr
  ADD CONSTRAINT issued_qr_order_id_fkey
  FOREIGN KEY (order_id) REFERENCES public.orders(id) ON DELETE CASCADE;

ALTER TABLE public.event_settings
  ADD CONSTRAINT event_settings_event_slug_fkey
  FOREIGN KEY (event_slug) REFERENCES public.events(slug) ON DELETE CASCADE;

ALTER TABLE public.event_settings
  ADD CONSTRAINT event_settings_tenant_id_fkey
  FOREIGN KEY (tenant_id) REFERENCES public.tenant_settings(tenant_id);

ALTER TABLE public.producer_campaign_deliveries
  ADD CONSTRAINT producer_campaign_deliveries_campaign_id_fkey
  FOREIGN KEY (campaign_id) REFERENCES public.producer_campaigns(id) ON DELETE CASCADE;

-- =========================
-- INDEXES
-- =========================

CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);

CREATE INDEX IF NOT EXISTS idx_orders_event_status_created
  ON public.orders(event_slug, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_orders_event_auth_created
  ON public.orders(event_slug, auth_provider, auth_subject, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_orders_bar_status_created
  ON public.orders(event_slug, bar_slug, status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_external_id
  ON public.orders (external_id)
  WHERE external_id IS NOT NULL AND external_id <> '';

CREATE INDEX IF NOT EXISTS idx_logs_event_ts ON public.logs(event_slug, ts DESC);

CREATE INDEX IF NOT EXISTS idx_producer_campaigns_scope_created
  ON public.producer_campaigns (producer_scope, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_producer_campaigns_status
  ON public.producer_campaigns (producer_scope, status);

CREATE INDEX IF NOT EXISTS idx_producer_campaign_deliveries_campaign
  ON public.producer_campaign_deliveries (campaign_id);

CREATE INDEX IF NOT EXISTS idx_producer_campaign_deliveries_scope_email
  ON public.producer_campaign_deliveries (producer_scope, email_norm);

CREATE INDEX IF NOT EXISTS idx_producer_contact_unsubs_email
  ON public.producer_contact_unsubscribes (email_norm);

CREATE UNIQUE INDEX IF NOT EXISTS uq_producer_contact_unsubs_scope
  ON public.producer_contact_unsubscribes (scope, producer_scope, email_norm);

-- =========================
-- TRIGGERS / FUNCTIONS
-- =========================

CREATE OR REPLACE FUNCTION public.orders_autofill_bar_fields()
RETURNS trigger AS $$
DECLARE
  ev_tenant TEXT;
BEGIN
  IF NEW.bar_slug IS NOT NULL THEN
    IF NEW.source IS NULL OR NEW.source = '' THEN
      NEW.source := 'bar';
    END IF;

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
