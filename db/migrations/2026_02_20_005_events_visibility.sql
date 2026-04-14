-- MVP: eventos privados por link (unlisted)
-- Agrega visibilidad a events con default public y constraint de valores permitidos.

ALTER TABLE events
ADD COLUMN IF NOT EXISTS visibility TEXT;

ALTER TABLE events
ALTER COLUMN visibility SET DEFAULT 'public';

UPDATE events
SET visibility = 'public'
WHERE visibility IS NULL;

ALTER TABLE events
ALTER COLUMN visibility SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'events_visibility_check'
  ) THEN
    ALTER TABLE events
    ADD CONSTRAINT events_visibility_check
    CHECK (visibility IN ('public', 'unlisted'));
  END IF;
END $$;

