import os
import glob
import psycopg

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")

def main():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("Missing DATABASE_URL env var")

    files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
    if not files:
        print("No migrations found.")
        return

    print(f"Found {len(files)} migration(s).")

    with psycopg.connect(dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            for path in files:
                name = os.path.basename(path)
                print(f"Applying: {name}")
                sql = open(path, "r", encoding="utf-8").read()
                cur.execute(sql)

    print("All migrations applied.")

if __name__ == "__main__":
    main()
