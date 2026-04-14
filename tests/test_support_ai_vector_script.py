import importlib.util
import tempfile
import unittest
from pathlib import Path


_SCRIPT_PATH = Path("scripts/ai/create_or_update_vector_store.py")
_SPEC = importlib.util.spec_from_file_location("vector_script", _SCRIPT_PATH)
vector_script = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(vector_script)


class VectorStoreScriptTests(unittest.TestCase):
    def test_vector_store_item_file_id_prefers_file_id(self):
        self.assertEqual(
            vector_script._vector_store_item_file_id({"id": "vsf_1", "file_id": "file_123"}),
            "file_123",
        )

    def test_vector_store_item_file_id_falls_back_to_id(self):
        self.assertEqual(vector_script._vector_store_item_file_id({"id": "file_abc"}), "file_abc")

    def test_should_skip_upload_true_when_name_and_size_match(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "doc.md"
            p.write_text("hola", encoding="utf-8")
            existing = {"doc.md": {p.stat().st_size}}
            self.assertTrue(vector_script._should_skip_upload(p, existing))

    def test_should_skip_upload_false_when_size_differs(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "doc.md"
            p.write_text("hola", encoding="utf-8")
            existing = {"doc.md": {99999}}
            self.assertFalse(vector_script._should_skip_upload(p, existing))


if __name__ == "__main__":
    unittest.main()
