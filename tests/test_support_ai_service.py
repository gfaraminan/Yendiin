import unittest

from pydantic import ValidationError

from app.support_ai.prompts import build_system_prompt, build_user_message
from app.support_ai.schemas import SupportAIChatRequest


class SupportAIPromptTests(unittest.TestCase):
    def test_build_system_prompt_with_role(self):
        prompt = build_system_prompt("buyer")
        self.assertIn("comprador final", prompt)

    def test_build_user_message_includes_tenant_and_context(self):
        msg = build_user_message("hola", "tenant-x", {"order_id": "O1"})
        self.assertIn('"tenant_id": "tenant-x"', msg)
        self.assertIn('"order_id": "O1"', msg)

    def test_context_size_too_large_fails(self):
        with self.assertRaises(ValidationError):
            SupportAIChatRequest(message="hola", context={"blob": "x" * 9000})


if __name__ == "__main__":
    unittest.main()
