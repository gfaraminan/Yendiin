BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

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
  campaign_id UUID NOT NULL REFERENCES public.producer_campaigns(id) ON DELETE CASCADE,
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

COMMIT;
