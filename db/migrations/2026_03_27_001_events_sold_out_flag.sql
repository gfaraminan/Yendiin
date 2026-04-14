-- Permite marcar eventos como SOLD OUT sin ocultarlos del catálogo.
ALTER TABLE events
  ADD COLUMN IF NOT EXISTS sold_out BOOLEAN NOT NULL DEFAULT FALSE;
