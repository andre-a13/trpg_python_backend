import atexit
import os
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from httpx import ASGITransport, AsyncClient


_temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
atexit.register(_temp_dir.cleanup)
_db_path = os.path.join(_temp_dir.name, "test.db")

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db_path}"
os.environ["AUTH_TOKEN_SECRET"] = "test-secret-with-enough-length"
os.environ["DB_SNAPSHOT_ON_SHUTDOWN"] = "false"
os.environ["REFRESH_TOKEN_COOKIE_SECURE"] = "false"
os.environ["ALLOW_FIRST_USER_REGISTRATION"] = "true"

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.migrations import run_migrations  # noqa: E402
from app.config import Settings  # noqa: E402
from app.storage.scaleway import ScalewayObjectStorage, UploadValidationError, get_object_storage  # noqa: E402


ADMIN_CREDENTIALS = {
    "username": "admin",
    "password": "replace-with-a-long-password",
}


class FakeBackgroundStorage:
    class SettingsStub:
        character_image_upload_url_expires_seconds = 900

    settings = SettingsStub()

    def validate_character_background(self, content_type: str, size: int) -> None:
        if content_type != "image/webp" or size > 15 * 1024 * 1024:
            raise UploadValidationError("Invalid background")

    def create_character_background_key(self, character_slug: str, content_type: str) -> str:
        return f"characters/{character_slug}/backgrounds/test.webp"

    def create_presigned_put_url(self, object_key: str, content_type: str) -> str:
        return f"https://upload.example.com/{object_key}"

    def public_url(self, object_key: str) -> str:
        return f"https://files.example.com/{object_key}"


class SecurityDataTests(unittest.IsolatedAsyncioTestCase):
    _migrated = False
    _admin_created = False

    async def asyncSetUp(self):
        if not self.__class__._migrated:
            await run_migrations(engine)
            self.__class__._migrated = True

    def client(self) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def ensure_admin(self, client: AsyncClient) -> None:
        if self.__class__._admin_created:
            return

        response = await client.post("/auth/register", json=ADMIN_CREDENTIALS)
        if response.status_code == 401:
            self.__class__._admin_created = True
            return
        if response.status_code not in {201, 409}:
            self.fail(f"admin registration failed: {response.status_code} {response.text}")
        self.__class__._admin_created = True

    async def login(self, client: AsyncClient) -> str:
        await self.ensure_admin(client)
        response = await client.post("/auth/login", json=ADMIN_CREDENTIALS)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("refresh_token", body)
        self.assertIn("access_token", body)
        self.assertIsNotNone(client.cookies.get("trpg_refresh_token"))
        return body["access_token"]

    def auth_headers(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    async def test_private_reads_require_auth(self):
        async with self.client() as client:
            characters = await client.get("/characters")
            teams = await client.get("/teams")

        self.assertEqual(characters.status_code, 401)
        self.assertEqual(teams.status_code, 401)

    async def test_authenticated_reads_succeed(self):
        async with self.client() as client:
            access_token = await self.login(client)
            characters = await client.get("/characters", headers=self.auth_headers(access_token))
            teams = await client.get("/teams", headers=self.auth_headers(access_token))

        self.assertEqual(characters.status_code, 200)
        self.assertEqual(teams.status_code, 200)

    async def test_refresh_cookie_rotates_and_logout_clears_cookie(self):
        async with self.client() as client:
            await self.login(client)
            first_refresh_token = client.cookies.get("trpg_refresh_token")

            refresh = await client.post("/auth/refresh")
            self.assertEqual(refresh.status_code, 200)
            self.assertNotIn("refresh_token", refresh.json())
            self.assertNotEqual(first_refresh_token, client.cookies.get("trpg_refresh_token"))

            logout = await client.post("/auth/logout")
            self.assertEqual(logout.status_code, 204)
            self.assertIsNone(client.cookies.get("trpg_refresh_token"))

    async def test_duplicate_character_slug_conflict(self):
        async with self.client() as client:
            access_token = await self.login(client)
            payload = {
                "slug": f"hero-{uuid4().hex}",
                "name": "Hero",
                "race": "Human",
                "stats": {"corps": 50, "mental": 50, "social": 50},
            }

            first = await client.post("/characters", json=payload, headers=self.auth_headers(access_token))
            duplicate = await client.post("/characters", json=payload, headers=self.auth_headers(access_token))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(duplicate.status_code, 409)

    async def test_duplicate_team_uuid_conflict(self):
        async with self.client() as client:
            access_token = await self.login(client)
            payload = {
                "uuid": str(uuid4()),
                "name": "Test Company",
            }

            first = await client.post("/teams", json=payload, headers=self.auth_headers(access_token))
            duplicate = await client.post("/teams", json=payload, headers=self.auth_headers(access_token))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(duplicate.status_code, 409)

    async def test_team_character_summaries_include_roster_fields(self):
        async with self.client() as client:
            access_token = await self.login(client)
            headers = self.auth_headers(access_token)
            slug = f"roster-{uuid4().hex}"
            team_uuid = str(uuid4())

            await client.post(
                "/characters",
                json={
                    "slug": slug,
                    "name": "Roster Hero",
                    "race": "Elf",
                    "portraitUrl": "https://example.com/portrait.jpg",
                    "stats": {"corps": 50, "mental": 50, "social": 50},
                },
                headers=headers,
            )
            await client.post("/teams", json={"uuid": team_uuid, "name": "Roster Team"}, headers=headers)
            await client.post(f"/teams/{team_uuid}/characters/{slug}", headers=headers)

            response = await client.get(f"/teams/{team_uuid}", headers=headers)

        self.assertEqual(response.status_code, 200)
        member = response.json()["characters"][0]
        self.assertEqual(member["race"], "Elf")
        self.assertEqual(member["portraitUrl"], "https://example.com/portrait.jpg")

    async def test_migration_bootstrap_created_current_schema(self):
        with sqlite3.connect(_db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }

        self.assertIn("schema_migrations", tables)
        self.assertIn("characters", tables)
        self.assertIn("teams", tables)
        self.assertIn("users", tables)
        self.assertIn("refresh_tokens", tables)
        self.assertIn("inventory_categories", tables)
        self.assertIn("inventory_contents", tables)
        with sqlite3.connect(_db_path) as conn:
            character_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(characters)")
            }
        self.assertIn("background_url", character_columns)

    async def test_character_background_url_patch_and_detail(self):
        async with self.client() as client:
            access_token = await self.login(client)
            headers = self.auth_headers(access_token)
            slug = f"background-{uuid4().hex}"

            await client.post(
                "/characters",
                json={
                    "slug": slug,
                    "name": "Background Hero",
                    "race": "Human",
                    "stats": {"corps": 50, "mental": 50, "social": 50},
                },
                headers=headers,
            )
            patch = await client.patch(
                f"/characters/{slug}",
                json={"backgroundUrl": "https://example.com/background.webp"},
                headers=headers,
            )
            detail = await client.get(f"/characters/{slug}", headers=headers)
            clear = await client.patch(
                f"/characters/{slug}",
                json={"backgroundUrl": None},
                headers=headers,
            )

        self.assertEqual(patch.status_code, 200)
        self.assertEqual(patch.json()["backgroundUrl"], "https://example.com/background.webp")
        self.assertEqual(detail.json()["backgroundUrl"], "https://example.com/background.webp")
        self.assertIsNone(clear.json()["backgroundUrl"])

    async def test_background_upload_route_requires_character_and_uses_background_prefix(self):
        async with self.client() as client:
            access_token = await self.login(client)
            headers = self.auth_headers(access_token)
            slug = f"upload-bg-{uuid4().hex}"
            app.dependency_overrides[get_object_storage] = lambda: FakeBackgroundStorage()
            try:
                missing = await client.post(
                    f"/characters/{slug}/background-upload",
                    json={"filename": "bg.webp", "content_type": "image/webp", "size": 15 * 1024 * 1024},
                    headers=headers,
                )
                await client.post(
                    "/characters",
                    json={
                        "slug": slug,
                        "name": "Upload Background Hero",
                        "race": "Human",
                        "stats": {"corps": 50, "mental": 50, "social": 50},
                    },
                    headers=headers,
                )
                response = await client.post(
                    f"/characters/{slug}/background-upload",
                    json={"filename": "bg.webp", "content_type": "image/webp", "size": 15 * 1024 * 1024},
                    headers=headers,
                )
            finally:
                app.dependency_overrides.pop(get_object_storage, None)

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["object_key"].startswith(f"characters/{slug}/backgrounds/"))

    async def test_background_upload_limit_is_separate_from_portrait_limit(self):
        settings = Settings(
            character_image_max_size_mb=5,
            character_background_image_max_size_mb=15,
        )
        storage = ScalewayObjectStorage(settings)
        fifteen_mb = 15 * 1024 * 1024

        storage.validate_character_background("image/jpeg", fifteen_mb)
        with self.assertRaises(UploadValidationError):
            storage.validate_character_portrait("image/jpeg", fifteen_mb)

    async def test_custom_inventory_category_crud_and_nested_character_payload(self):
        async with self.client() as client:
            access_token = await self.login(client)
            headers = self.auth_headers(access_token)
            slug = f"inventory-{uuid4().hex}"

            character = await client.post(
                "/characters",
                json={
                    "slug": slug,
                    "name": "Inventory Hero",
                    "race": "Human",
                    "stats": {"corps": 50, "mental": 50, "social": 50},
                    "inventory": ["legacy rope"],
                },
                headers=headers,
            )
            self.assertEqual(character.status_code, 201)

            category = await client.post(
                f"/characters/{slug}/inventory-categories",
                json={"name": "Potions"},
                headers=headers,
            )
            duplicate = await client.post(
                f"/characters/{slug}/inventory-categories",
                json={"name": "Potions"},
                headers=headers,
            )
            self.assertEqual(category.status_code, 201)
            self.assertEqual(duplicate.status_code, 409)
            category_id = category.json()["id"]

            first_item = await client.post(
                f"/characters/{slug}/inventory-categories/{category_id}/items",
                json={"name": "Healing potion", "quantity": 2, "notes": "Red vial"},
                headers=headers,
            )
            second_item = await client.post(
                f"/characters/{slug}/inventory-categories/{category_id}/items",
                json={"name": "Antidote", "quantity": 1},
                headers=headers,
            )
            self.assertEqual(first_item.status_code, 201)
            self.assertEqual(second_item.status_code, 201)

            reorder = await client.patch(
                f"/characters/{slug}/inventory-categories/{category_id}/items/reorder",
                json={
                    "items": [
                        {"id": second_item.json()["id"], "sortOrder": 0},
                        {"id": first_item.json()["id"], "sortOrder": 1},
                    ]
                },
                headers=headers,
            )
            self.assertEqual(reorder.status_code, 200)

            response = await client.get(f"/characters/{slug}", headers=headers)
            list_response = await client.get("/characters", headers=headers)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["inventory"], ["legacy rope"])
        self.assertEqual(body["inventoryCategories"][0]["name"], "Potions")
        self.assertEqual(body["inventoryCategories"][0]["contents"][0]["name"], "Antidote")
        self.assertNotIn("inventoryCategories", list_response.json()[0])

    async def test_custom_inventory_content_is_scoped_to_character(self):
        async with self.client() as client:
            access_token = await self.login(client)
            headers = self.auth_headers(access_token)
            first_slug = f"scope-a-{uuid4().hex}"
            second_slug = f"scope-b-{uuid4().hex}"

            for slug in (first_slug, second_slug):
                response = await client.post(
                    "/characters",
                    json={
                        "slug": slug,
                        "name": slug,
                        "race": "Human",
                        "stats": {"corps": 50, "mental": 50, "social": 50},
                    },
                    headers=headers,
                )
                self.assertEqual(response.status_code, 201)

            category = await client.post(
                f"/characters/{first_slug}/inventory-categories",
                json={"name": "Scoped"},
                headers=headers,
            )
            self.assertEqual(category.status_code, 201)

            wrong_character = await client.post(
                f"/characters/{second_slug}/inventory-categories/{category.json()['id']}/items",
                json={"name": "Should fail"},
                headers=headers,
            )

        self.assertEqual(wrong_character.status_code, 404)

    async def test_deleting_custom_inventory_category_cascades_content(self):
        async with self.client() as client:
            access_token = await self.login(client)
            headers = self.auth_headers(access_token)
            slug = f"cascade-{uuid4().hex}"

            await client.post(
                "/characters",
                json={
                    "slug": slug,
                    "name": "Cascade Hero",
                    "race": "Human",
                    "stats": {"corps": 50, "mental": 50, "social": 50},
                },
                headers=headers,
            )
            category = await client.post(
                f"/characters/{slug}/inventory-categories",
                json={"name": "Temporary"},
                headers=headers,
            )
            category_id = category.json()["id"]
            item = await client.post(
                f"/characters/{slug}/inventory-categories/{category_id}/items",
                json={"name": "Temporary item"},
                headers=headers,
            )
            self.assertEqual(item.status_code, 201)

            delete_response = await client.delete(
                f"/characters/{slug}/inventory-categories/{category_id}",
                headers=headers,
            )
            response = await client.patch(
                f"/characters/{slug}/inventory-categories/{category_id}/items/{item.json()['id']}",
                json={"name": "Gone"},
                headers=headers,
            )
            character = await client.get(f"/characters/{slug}", headers=headers)

        self.assertEqual(delete_response.status_code, 204)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(character.json()["inventoryCategories"], [])

    async def test_legacy_inventory_patch_still_works(self):
        async with self.client() as client:
            access_token = await self.login(client)
            headers = self.auth_headers(access_token)
            slug = f"legacy-{uuid4().hex}"

            await client.post(
                "/characters",
                json={
                    "slug": slug,
                    "name": "Legacy Hero",
                    "race": "Human",
                    "stats": {"corps": 50, "mental": 50, "social": 50},
                    "inventory": ["old"],
                },
                headers=headers,
            )
            patch = await client.patch(
                f"/characters/{slug}",
                json={"inventory": ["new", "still legacy"]},
                headers=headers,
            )

        self.assertEqual(patch.status_code, 200)
        self.assertEqual(patch.json()["inventory"], ["new", "still legacy"])
