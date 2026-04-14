from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from app.db import get_conn
from app.mailer import send_email


@dataclass
class ToolResult:
    name: str
    payload: dict[str, Any]


class SupportAITools:
    def __init__(self, *, request_context: dict[str, Any] | None = None, user_message: str = "") -> None:
        self.request_context = request_context or {}
        self.user_message = user_message or ""
        self._tool_map: dict[str, Callable[..., dict[str, Any]]] = {
            "get_order": self.get_order,
            "list_issued_tickets": self.list_issued_tickets,
            "get_public_event": self.get_public_event,
            "list_sale_items": self.list_sale_items,
            "resend_order_email": self.resend_order_email,
            "get_event_ticket_sales_today": self.get_event_ticket_sales_today,
            "get_total_ticket_sales_today": self.get_total_ticket_sales_today,
            "get_service_charge_last_days": self.get_service_charge_last_days,
            "find_events_by_query": self.find_events_by_query,
            "get_event_ticket_sales_today_by_name": self.get_event_ticket_sales_today_by_name,
        }

    def with_request_context(self, context: dict[str, Any] | None, user_message: str) -> "SupportAITools":
        return self.__class__(request_context=context or {}, user_message=user_message)

    @property
    def specs(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "get_order",
                "description": "Obtiene una orden por tenant y order_id",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"},
                        "order_id": {"type": "string"},
                    },
                    "required": ["tenant_id", "order_id"],
                },
            },
            {
                "type": "function",
                "name": "list_issued_tickets",
                "description": "Lista tickets emitidos de una orden",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"},
                        "order_id": {"type": "string"},
                    },
                    "required": ["tenant_id", "order_id"],
                },
            },
            {
                "type": "function",
                "name": "get_public_event",
                "description": "Obtiene un evento público por slug",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"},
                        "event_slug": {"type": "string"},
                    },
                    "required": ["tenant_id", "event_slug"],
                },
            },
            {
                "type": "function",
                "name": "list_sale_items",
                "description": "Lista items de venta visibles de un evento",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"},
                        "event_slug": {"type": "string"},
                    },
                    "required": ["tenant_id", "event_slug"],
                },
            },
            {
                "type": "function",
                "name": "resend_order_email",
                "description": "Reenvía email de orden pagada (requiere order_id y to_email)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"},
                        "order_id": {"type": "string"},
                        "to_email": {"type": "string"},
                    },
                    "required": ["tenant_id", "order_id", "to_email"],
                },
            },
            {
                "type": "function",
                "name": "get_event_ticket_sales_today",
                "description": "Cantidad de tickets vendidos hoy para un evento",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"},
                        "event_slug": {"type": "string"}
                    },
                    "required": ["tenant_id", "event_slug"]
                }
            },
            {
                "type": "function",
                "name": "get_total_ticket_sales_today",
                "description": "Cantidad total de tickets vendidos hoy entre todos los eventos",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"}
                    },
                    "required": ["tenant_id"]
                }
            },
            {
                "type": "function",
                "name": "get_service_charge_last_days",
                "description": "Total de service charge cobrado en los últimos N días",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"},
                        "days": {"type": "integer", "minimum": 1, "maximum": 60}
                    },
                    "required": ["tenant_id"]
                }
            },
            {
                "type": "function",
                "name": "find_events_by_query",
                "description": "Busca eventos por nombre o slug para no depender del event_slug exacto",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"},
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10}
                    },
                    "required": ["tenant_id", "query"]
                }
            },
            {
                "type": "function",
                "name": "get_event_ticket_sales_today_by_name",
                "description": "Devuelve ventas de tickets de hoy encontrando el evento por nombre (sin slug exacto)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string"},
                        "event_query": {"type": "string"}
                    },
                    "required": ["tenant_id", "event_query"]
                }
            },
        ]

    def run(self, name: str, arguments_json: str) -> ToolResult:
        if name not in self._tool_map:
            raise ValueError(f"Tool no soportada: {name}")
        try:
            args = json.loads(arguments_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"Argumentos JSON inválidos para tool {name}") from exc
        payload = self._tool_map[name](**args)
        return ToolResult(name=name, payload=payload)

    def get_order(self, tenant_id: str, order_id: str) -> dict[str, Any]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, tenant_id, event_slug, status, buyer_email, buyer_name, total_cents, created_at
                FROM orders
                WHERE tenant_id=%s AND id=%s
                LIMIT 1
                """,
                (tenant_id, order_id),
            )
            row = cur.fetchone()
            return {"order": row}

    def list_issued_tickets(self, tenant_id: str, order_id: str) -> dict[str, Any]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, order_id, code, status, created_at
                FROM tickets
                WHERE tenant_id=%s AND order_id=%s
                ORDER BY created_at ASC
                """,
                (tenant_id, order_id),
            )
            rows = cur.fetchall() or []
            return {"tickets": rows}

    def get_public_event(self, tenant_id: str, event_slug: str) -> dict[str, Any]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT slug, title, date_text, venue, city, active, category
                FROM events
                WHERE tenant_id=%s AND slug=%s AND active=TRUE
                LIMIT 1
                """,
                (tenant_id, event_slug),
            )
            row = cur.fetchone()
            return {"event": row}

    def list_sale_items(self, tenant_id: str, event_slug: str) -> dict[str, Any]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT si.id, si.name, si.price_cents, si.active, si.stock_total, si.stock_sold
                FROM events e
                JOIN sale_items si ON si.event_slug = e.slug AND si.tenant = e.tenant
                WHERE e.tenant_id=%s AND e.slug=%s
                ORDER BY si.id ASC
                """,
                (tenant_id, event_slug),
            )
            rows = cur.fetchall() or []
            return {"sale_items": rows}


    @staticmethod
    def _normalize_order_id(value: str) -> str:
        v = str(value or "").strip()
        if not v:
            return ""
        v = v.replace("Orden", "").replace("Order", "").replace("#", " ")
        v = " ".join(v.split())
        if " " in v:
            # keep most uuid-like token if present
            parts = [p.strip(" ,.;") for p in v.split(" ") if p.strip(" ,.;")]
            for part in parts:
                if len(part) >= 8 and "-" in part:
                    return part
            return parts[-1] if parts else ""
        return v.strip(" ,.;")

    def find_events_by_query(self, tenant_id: str, query: str, limit: int = 5) -> dict[str, Any]:
        q = (query or "").strip()
        limit = max(1, min(int(limit or 5), 10))
        if not q:
            return {"events": []}

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT slug, title, date_text, venue, city
                FROM events
                WHERE tenant_id=%s
                  AND active=TRUE
                  AND (
                    slug ILIKE %s
                    OR title ILIKE %s
                  )
                ORDER BY
                  CASE WHEN slug ILIKE %s THEN 0 ELSE 1 END,
                  CASE WHEN title ILIKE %s THEN 0 ELSE 1 END,
                  title ASC
                LIMIT %s
                """,
                (tenant_id, f"%{q}%", f"%{q}%", f"{q}%", f"{q}%", limit),
            )
            rows = cur.fetchall() or []
            return {"events": rows}

    def get_event_ticket_sales_today_by_name(self, tenant_id: str, event_query: str) -> dict[str, Any]:
        matches = self.find_events_by_query(tenant_id=tenant_id, query=event_query, limit=3).get("events", [])
        if not matches:
            return {
                "tenant_id": tenant_id,
                "event_query": event_query,
                "matched": False,
                "tickets_sold_today": 0,
                "message": "No se encontró evento para ese nombre",
            }

        best = matches[0]
        slug = str(best.get("slug") or "")
        sales = self.get_event_ticket_sales_today(tenant_id=tenant_id, event_slug=slug)
        return {
            "tenant_id": tenant_id,
            "event_query": event_query,
            "matched": True,
            "event": best,
            "tickets_sold_today": int(sales.get("tickets_sold_today") or 0),
            "alternatives": matches[1:],
        }

    def _orders_table_columns(self) -> set[str]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name='orders'
                """
            )
            return {str((r or {}).get("column_name") or "") for r in (cur.fetchall() or []) if (r or {}).get("column_name")}

    def get_event_ticket_sales_today(self, tenant_id: str, event_slug: str) -> dict[str, Any]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*)::bigint AS tickets_sold_today
                FROM tickets
                WHERE tenant_id=%s
                  AND event_slug=%s
                  AND COALESCE(status,'') NOT ILIKE 'revoked'
                  AND created_at::date = CURRENT_DATE
                """,
                (tenant_id, event_slug),
            )
            row = cur.fetchone() or {}
            return {
                "tenant_id": tenant_id,
                "event_slug": event_slug,
                "tickets_sold_today": int(row.get("tickets_sold_today") or 0),
            }

    def get_total_ticket_sales_today(self, tenant_id: str) -> dict[str, Any]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*)::bigint AS tickets_sold_today
                FROM tickets
                WHERE tenant_id=%s
                  AND COALESCE(status,'') NOT ILIKE 'revoked'
                  AND created_at::date = CURRENT_DATE
                """,
                (tenant_id,),
            )
            row = cur.fetchone() or {}
            return {
                "tenant_id": tenant_id,
                "tickets_sold_today": int(row.get("tickets_sold_today") or 0),
            }

    def get_service_charge_last_days(self, tenant_id: str, days: int = 15) -> dict[str, Any]:
        days = max(1, min(int(days or 15), 60))
        cols = self._orders_table_columns()

        with get_conn() as conn:
            cur = conn.cursor()
            if "fee_amount" in cols:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(ROUND(COALESCE(fee_amount,0) * 100)),0)::bigint AS fee_cents
                    FROM orders
                    WHERE tenant_id=%s
                      AND status ILIKE 'PAID'
                      AND created_at >= now() - (%s * interval '1 day')
                    """,
                    (tenant_id, days),
                )
                row = cur.fetchone() or {}
                return {
                    "tenant_id": tenant_id,
                    "days": days,
                    "service_charge_cents": int(row.get("fee_cents") or 0),
                    "source": "orders.fee_amount",
                }

            if "total_amount" in cols and "base_amount" in cols:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(ROUND((COALESCE(total_amount,0)-COALESCE(base_amount,0)) * 100)),0)::bigint AS fee_cents
                    FROM orders
                    WHERE tenant_id=%s
                      AND status ILIKE 'PAID'
                      AND created_at >= now() - (%s * interval '1 day')
                    """,
                    (tenant_id, days),
                )
                row = cur.fetchone() or {}
                return {
                    "tenant_id": tenant_id,
                    "days": days,
                    "service_charge_cents": int(row.get("fee_cents") or 0),
                    "source": "orders.total_amount-base_amount",
                }

        return {
            "tenant_id": tenant_id,
            "days": days,
            "service_charge_cents": None,
            "source": "unavailable",
            "warning": "No hay columnas fee_amount o total_amount/base_amount en orders",
        }

    def resend_order_email(self, tenant_id: str, order_id: str, to_email: str) -> dict[str, Any]:
        order_id = self._normalize_order_id(order_id)
        to_email = str(to_email or "").strip().lower()
        if not order_id or not to_email:
            return {"ok": False, "error": "order_id y to_email son requeridos"}

        msg_lower = self.user_message.lower()
        is_confirmed = bool(self.request_context.get("confirm_resend_order_email")) or ("confirm" in msg_lower and "reenvi" in msg_lower)
        if not is_confirmed:
            return {
                "ok": False,
                "error": "Falta confirmación explícita (escribe 'confirmo reenviar' o usa context.confirm_resend_order_email=true)",
            }

        order = self.get_order(tenant_id=tenant_id, order_id=order_id).get("order")
        if not order:
            return {"ok": False, "error": "Orden no encontrada"}

        status = str(order.get("status") or "").lower()
        if status != "paid":
            return {"ok": False, "error": "Solo se permite reenvío para órdenes paid"}

        subject = f"Ticketera - Reenvío de orden {order_id}"
        text = (
            "Hola,\n\n"
            f"Te reenviamos la confirmación de tu orden {order_id}. "
            "Si necesitás tus tickets, ingresá a Mis Tickets.\n\n"
            "Equipo Ticketera"
        )
        send_email(to_email=to_email, subject=subject, text=text)
        return {"ok": True, "message": "Email reenviado"}
