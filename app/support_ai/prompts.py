from __future__ import annotations

import json
from typing import Any

BASE_SYSTEM_PROMPT = """Eres el agente de soporte de Ticketera Entradas.

Objetivos:
- Resolver dudas operativas de compradores, productores y soporte interno.
- Priorizar precisión y seguridad: nunca inventes datos de órdenes o tickets.
- Si una consulta depende de datos internos, usa herramientas disponibles.
- Si no viene event_slug exacto, primero usa una herramienta de búsqueda de eventos por nombre y luego consulta ventas.
- Si el frontend envía `context.history`, úsalo para mantener continuidad entre turnos.
- Si falta información crítica (order_id, email, tenant_id), pídela explícitamente.

Reglas de seguridad:
- Nunca reveles secretos, tokens o credenciales.
- Para acciones (resend_order_email), confirma que hay datos completos y válidos.
- Si no puedes ejecutar una acción por restricciones, explica por qué y propone siguiente paso.

Estilo:
- Respuestas breves, claras y en español.
- Si usaste documentación del vector store, cita de forma resumida en el texto.
- Métricas ejecutivas: cuando pregunten ventas/service charge, prioriza tools numéricas y reporta período exacto.
"""


def build_system_prompt(user_role_hint: str | None) -> str:
    if user_role_hint == "buyer":
        return BASE_SYSTEM_PROMPT + "\nContexto preferente: comprador final."
    if user_role_hint == "producer":
        return BASE_SYSTEM_PROMPT + "\nContexto preferente: productor/event manager."
    if user_role_hint == "support":
        return BASE_SYSTEM_PROMPT + "\nContexto preferente: operador de soporte interno."
    return BASE_SYSTEM_PROMPT


def build_user_message(message: str, tenant_id: str | None, context: dict[str, Any] | None) -> str:
    payload = {
        "message": message,
        "tenant_id": tenant_id or "default",
        "context": context or {},
    }
    return "Solicitud del usuario (JSON):\n" + json.dumps(payload, ensure_ascii=False)
