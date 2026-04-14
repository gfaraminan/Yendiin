erDiagram
  EVENTS {
    text tenant_id
    text slug
    text tenant
    text title
    boolean active
    timestamptz created_at
  }

  ORDERS {
    uuid id
    text tenant_id
    text event_slug
    text status
    text source
    text producer_tenant
    text bar_slug
    bigint total_cents
    numeric total_amount
    text currency
    jsonb items_json
    text external_id
    timestamptz created_at
    timestamptz paid_at
  }

  ORDER_ITEMS {
    uuid id
    uuid order_id
    text name
    text kind
    numeric qty
    numeric unit_amount
    numeric total_amount
  }

  SALE_ITEMS {
    text tenant
    text event_slug
    text id
    text name
    text kind
    int price_cents
    int stock_total
    int stock_sold
    boolean active
  }

  TICKETS {
    uuid id
    text event_slug
    text tenant_id
    text status
    text sale_item_id
    timestamptz created_at
  }

  ISSUED_QR {
    uuid id
    uuid order_id
    text qr_token
    timestamptz created_at
  }

  EVENTS ||--o{ ORDERS : "slug = event_slug"
  ORDERS ||--o{ ORDER_ITEMS : "order_id"
  EVENTS ||--o{ SALE_ITEMS : "event_slug"
  EVENTS ||--o{ TICKETS : "event_slug"
  ORDERS ||--o{ ISSUED_QR : "order_id"
