CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- USERS (identidad unificada / CRM base)
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  auth_provider TEXT NOT NULL,
  auth_subject TEXT NOT NULL,
  email TEXT,
  name TEXT,
  picture_url TEXT,
  marketing_opt_in BOOLEAN,
  opt_in_timestamp TIMESTAMPTZ,
  opt_in_source TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (auth_provider, auth_subject)
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- EVENTS
CREATE TABLE IF NOT EXISTS events (
  slug TEXT PRIMARY KEY,
  name TEXT,
  starts_at TIMESTAMPTZ,
  ends_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ORDERS (ticketera + barra)
CREATE TABLE IF NOT EXISTS orders (
  id UUID PRIMARY KEY,
  event_slug TEXT NOT NULL REFERENCES events(slug),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL,
  bar_slug TEXT,
  customer_label TEXT,
  total_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'ARS',
  items_json JSONB,
  pickup_code TEXT,
  qr_token TEXT,

  auth_provider TEXT,
  auth_subject TEXT,

  paid_at TIMESTAMPTZ,
  ready_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_orders_event_status_created
  ON orders(event_slug, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_orders_event_auth_created
  ON orders(event_slug, auth_provider, auth_subject, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_orders_bar_status_created
  ON orders(event_slug, bar_slug, status, created_at DESC);

-- LOGS (opcional, pero muy útil)
CREATE TABLE IF NOT EXISTS logs (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  level TEXT,
  event_slug TEXT,
  actor_type TEXT,
  actor_slug TEXT,
  action TEXT,
  detail JSONB
);

CREATE INDEX IF NOT EXISTS idx_logs_event_ts ON logs(event_slug, ts DESC);

-- MP SELLERS
CREATE TABLE IF NOT EXISTS mp_sellers (
  event TEXT NOT NULL,
  producer_id TEXT NOT NULL,
  access_token TEXT NOT NULL,
  refresh_token TEXT,
  expires_at BIGINT,
  updated_at BIGINT,
  PRIMARY KEY (event, producer_id)
);

-- WHITE LABEL / BRANDING
CREATE TABLE IF NOT EXISTS tenant_settings (
  tenant_id TEXT PRIMARY KEY,
  display_name TEXT,
  brand_color TEXT,
  logo_url TEXT,
  cover_url TEXT,
  links JSONB,
  feature_flags JSONB,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event_settings (
  event_slug TEXT PRIMARY KEY REFERENCES events(slug) ON DELETE CASCADE,
  tenant_id TEXT REFERENCES tenant_settings(tenant_id),
  display_name TEXT,
  brand_color TEXT,
  logo_url TEXT,
  cover_url TEXT,
  links JSONB,
  feature_flags JSONB,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
