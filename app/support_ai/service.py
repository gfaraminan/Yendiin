from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests

from app.support_ai.prompts import build_system_prompt, build_user_message
from app.support_ai.schemas import SupportAIChatRequest, SupportAIChatResponse
from app.support_ai.tools import SupportAITools


OPENAI_API_URL = "https://api.openai.com/v1/responses"


@dataclass
class ServiceResult:
    answer: str
    trace_id: str
    used_tools: list[str]
    citations: list[Any]


class SupportAIService:
    def __init__(self, *, http_client: Any | None = None, tools: SupportAITools | None = None) -> None:
        self.model = os.getenv("SUPPORT_AI_MODEL", "gpt-5-mini")
        self.vector_store_id = (os.getenv("OPENAI_VECTOR_STORE_ID") or "").strip()
        self.api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        self.http_client = http_client or requests
        self.timeout_s = int(os.getenv("SUPPORT_AI_TIMEOUT_S", "45"))
        self.tools = tools or SupportAITools()

    def chat(self, payload: SupportAIChatRequest) -> SupportAIChatResponse:
        runtime_tools = self.tools.with_request_context(payload.context, payload.message)
        result = self._run_response_loop(payload, runtime_tools=runtime_tools)
        return SupportAIChatResponse(
            answer=result.answer,
            trace_id=result.trace_id,
            used_tools=result.used_tools,
            citations=result.citations or None,
        )

    def _run_response_loop(self, payload: SupportAIChatRequest, *, runtime_tools: SupportAITools) -> ServiceResult:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY no configurada")

        used_tools: list[str] = []
        citations: list[Any] = []
        previous_response_id: str | None = None
        pending_input: Any = [
            {"role": "system", "content": build_system_prompt(payload.user_role_hint)},
            {"role": "user", "content": build_user_message(payload.message, payload.tenant_id, payload.context)},
        ]

        for _ in range(6):
            response_json = self._create_response(
                previous_response_id=previous_response_id,
                input_payload=pending_input,
                runtime_tools=runtime_tools,
            )
            previous_response_id = response_json.get("id")

            function_calls = self._extract_function_calls(response_json)
            citations.extend(self._extract_citations(response_json))

            if not function_calls:
                return ServiceResult(
                    answer=self._extract_text(response_json),
                    trace_id=previous_response_id or "",
                    used_tools=list(dict.fromkeys(used_tools)),
                    citations=self._dedupe_citations(citations),
                )

            outputs = []
            for call in function_calls:
                tool_name = call.get("name", "")
                if tool_name:
                    used_tools.append(tool_name)
                try:
                    tool_result = runtime_tools.run(tool_name, call.get("arguments", "{}"))
                    out_payload = {"ok": True, "data": tool_result.payload}
                except Exception as exc:  # controlled tool errors are returned to model
                    out_payload = {"ok": False, "error": str(exc)}

                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.get("call_id"),
                        "output": json.dumps(out_payload, ensure_ascii=False),
                    }
                )

            pending_input = outputs

        raise RuntimeError("Límite de iteraciones de tool-calling alcanzado")

    def _create_response(
        self,
        *,
        previous_response_id: str | None,
        input_payload: Any,
        runtime_tools: SupportAITools,
    ) -> dict[str, Any]:
        tools: list[dict[str, Any]] = list(runtime_tools.specs)
        if self.vector_store_id:
            tools.append(
                {
                    "type": "file_search",
                    "vector_store_ids": [self.vector_store_id],
                    "max_num_results": 5,
                }
            )

        body: dict[str, Any] = {
            "model": self.model,
            "input": input_payload,
            "tools": tools,
        }
        if previous_response_id:
            body["previous_response_id"] = previous_response_id

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = self.http_client.post(OPENAI_API_URL, headers=headers, json=body, timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _extract_function_calls(response_json: dict[str, Any]) -> list[dict[str, Any]]:
        output = response_json.get("output") or []
        calls: list[dict[str, Any]] = []
        for item in output:
            if item.get("type") == "function_call":
                calls.append(
                    {
                        "call_id": item.get("call_id"),
                        "name": item.get("name"),
                        "arguments": item.get("arguments") or "{}",
                    }
                )
        return calls

    @staticmethod
    def _extract_text(response_json: dict[str, Any]) -> str:
        if response_json.get("output_text"):
            return str(response_json.get("output_text"))

        chunks: list[str] = []
        for item in response_json.get("output") or []:
            if item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if content.get("type") in {"output_text", "text"}:
                    chunks.append(content.get("text", ""))
        return "\n".join([c for c in chunks if c]).strip() or "No se obtuvo respuesta."


    @staticmethod
    def _dedupe_citations(citations: list[Any]) -> list[Any]:
        deduped: list[Any] = []
        seen: set[str] = set()
        for cit in citations:
            key = json.dumps(cit, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(cit)
        return deduped

    @staticmethod
    def _extract_citations(response_json: dict[str, Any]) -> list[Any]:
        found: list[Any] = []
        for item in response_json.get("output") or []:
            for content in item.get("content") or []:
                for ann in content.get("annotations") or []:
                    found.append(ann)
        return found
