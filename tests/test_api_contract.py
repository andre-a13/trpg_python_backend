import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "openapi.json"
INVENTION_OPERATIONS = {
    "inventionsList", "inventionsCreate", "inventionsDelete",
    "invengineerSetEnabled", "inventionsGetState", "inventionsDraw",
}


class ApiContractTests(unittest.TestCase):
    def test_operation_ids_are_unique_and_all_success_responses_are_typed(self):
        schema = json.loads(CONTRACT.read_bytes())
        operations = [op for path in schema["paths"].values() for method, op in path.items()
                      if method in {"get", "post", "put", "patch", "delete"}]
        ids = [op["operationId"] for op in operations]
        self.assertEqual(len(ids), len(set(ids)))
        from fastapi.routing import APIRoute
        from app.main import app
        self.assertEqual(set(ids), {
            route.operation_id for route in app.routes
            if isinstance(route, APIRoute) and route.include_in_schema
        })
        for route in app.routes:
            if isinstance(route, APIRoute):
                self.assertTrue(route.operation_id, route.path)
        inventions = {op["operationId"]: op for op in operations
                      if op["operationId"] in INVENTION_OPERATIONS}
        self.assertEqual(set(inventions), INVENTION_OPERATIONS)
        for op in operations:
            for code, response in op["responses"].items():
                if code == "204":
                    self.assertNotIn("content", response)
                elif code.startswith("2"):
                    self.assertTrue(response["content"]["application/json"]["schema"], op["operationId"])

    def test_character_views_preserve_nulls_and_optional_expansions(self):
        from types import SimpleNamespace
        from app.routers.characters import serialize_character
        from app.schemas.characters import CharacterDetailResponse, CharacterSummaryResponse

        character = SimpleNamespace(
            id=1, slug="hero", name="Hero", race="Human", portrait_url=None,
            background_url=None, owner_user_id=None, owner=None,
            stats={"corps": 50, "mental": 50, "social": 50}, skills_primary=[],
            skills_secondary=[], inventory=[], gold=0, notes="legacy", current_hp=0,
            bonus_health=0, invengineer_enabled=False, deck=None, teams=[],
            note_tabs=[], inventory_categories=[],
        )
        summary = serialize_character(character)
        self.assertNotIn("noteTabs", summary)
        self.assertNotIn("inventoryCategories", summary)
        self.assertIsNone(summary["portraitUrl"])
        self.assertEqual(CharacterSummaryResponse.model_validate(summary).model_dump(), summary)
        detail = serialize_character(character, include_inventory_categories=True, include_note_tabs=True)
        self.assertEqual(detail["noteTabs"], [])
        self.assertEqual(detail["inventoryCategories"], [])
        self.assertEqual(CharacterDetailResponse.model_validate(detail).model_dump(), detail)

    def test_deck_configuration_variants_keep_their_original_shapes(self):
        from types import SimpleNamespace
        from pydantic import TypeAdapter
        from app.routers.hearthstone import serialize_deck
        from app.schemas.hearthstone import DeckStateResponse, DeckUnconfiguredResponse

        unconfigured = {"configured": False, "enabled": False}
        adapter = TypeAdapter(DeckStateResponse | DeckUnconfiguredResponse)
        self.assertEqual(adapter.validate_python(unconfigured).model_dump(), unconfigured)
        state = serialize_deck(
            SimpleNamespace(owner_user_id=1),
            SimpleNamespace(definitions=[], undo_copy_id=None, enabled=False, revision=0),
            SimpleNamespace(id=1, role="admin"),
        )
        self.assertEqual(adapter.validate_python(state).model_dump(), state)

    def test_export_is_reproducible_without_opening_configured_database(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{temp / 'db-parent' / 'forbidden.db'}"}
            results = []
            for name in ("first.json", "second.json"):
                output = temp / name
                result = subprocess.run(
                    [sys.executable, "-B", "-m", "scripts.export_openapi", "--output", str(output)],
                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                results.append(output.read_bytes())
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0], CONTRACT.read_bytes())
            self.assertFalse((temp / "db-parent").exists())
            output.write_text("{}\n", encoding="utf-8")
            check = subprocess.run(
                [sys.executable, "-B", "-m", "scripts.export_openapi", "--check", "--output", str(output)],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(check.returncode, 1)


if __name__ == "__main__":
    unittest.main()
