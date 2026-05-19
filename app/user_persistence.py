from __future__ import annotations

from typing import Any


def upsert_user_with_legacy_fallback(cur, tenant_id: str, user: dict[str, Any]) -> None:
    """Upsert user supporting both tenant-aware and legacy users schemas."""
    try:
        cur.execute(
            """
            INSERT INTO users (
                tenant_id, auth_provider, auth_subject,
                email, name, picture_url,
                last_login_at, last_seen_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, now(), now(), now())
            ON CONFLICT (auth_provider, auth_subject)
            DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                email = EXCLUDED.email,
                name = EXCLUDED.name,
                picture_url = EXCLUDED.picture_url,
                last_login_at = now(),
                last_seen_at = now(),
                updated_at = now()
            """,
            (
                tenant_id,
                user.get("provider"),
                user.get("sub"),
                user.get("email"),
                user.get("name"),
                user.get("picture"),
            ),
        )
        return
    except Exception as e:
        # Legacy DBs from white-label copies may not have users.tenant_id
        if "tenant_id" not in str(e).lower() or "users" not in str(e).lower():
            raise

    cur.execute(
        """
        INSERT INTO users (
            auth_provider, auth_subject,
            email, name, picture_url,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT (auth_provider, auth_subject)
        DO UPDATE SET
            email = EXCLUDED.email,
            name = EXCLUDED.name,
            picture_url = EXCLUDED.picture_url,
            updated_at = now()
        """,
        (
            user.get("provider"),
            user.get("sub"),
            user.get("email"),
            user.get("name"),
            user.get("picture"),
        ),
    )
