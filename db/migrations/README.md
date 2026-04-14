# DB Migrations (Ticketera)

- Las migraciones son **SQL puro** y se ejecutan en orden alfabético.
- Son **idempotentes**: se pueden correr más de una vez sin romper.
- Fuente de verdad: esta carpeta. Lo que esté en DB pero no acá, “no existe” (para recovery).

## Aplicación
Opción A (manual):
psql "$DATABASE_URL" -f db/migrations/<archivo>.sql

Opción B (automática):
python db/apply_migrations.py
