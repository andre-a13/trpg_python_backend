import atexit
import asyncio
from contextlib import closing
import os
import random
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine


_temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
atexit.register(_temp_dir.cleanup)
_db_path = os.path.join(_temp_dir.name, "test.db")

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db_path}"
os.environ["AUTH_TOKEN_SECRET"] = "test-secret-with-enough-length"
os.environ["DB_SNAPSHOT_ON_SHUTDOWN"] = "false"
os.environ["REFRESH_TOKEN_COOKIE_SECURE"] = "false"
os.environ["ALLOW_FIRST_USER_REGISTRATION"] = "true"

from app.db import engine, SessionLocal  # noqa: E402
from app.models import Character  # noqa: E402
from app.main import app  # noqa: E402
from app.migrations import MIGRATIONS, run_migrations  # noqa: E402
from app.config import Settings  # noqa: E402
from app.hearthstone_catalog import (  # noqa: E402
    HEARTHSTONE_RARITY_RATES,
    PACK_RARITY_TARGETS,
    RARE_OR_BETTER,
    _ordinary_slot_weights,
    weighted_pack_sample,
)
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

    async def create_account(
        self,
        client: AsyncClient,
        admin_headers: dict[str, str],
        role: str = "player",
    ) -> tuple[dict, dict[str, str]]:
        credentials = {
            "username": f"{role}-{uuid4().hex}",
            "password": "replace-with-a-long-password",
        }
        response = await client.post(
            "/accounts",
            json={**credentials, "role": role},
            headers=admin_headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        login = await client.post("/auth/login", json=credentials)
        self.assertEqual(login.status_code, 200, login.text)
        return response.json(), self.auth_headers(login.json()["access_token"])

    async def test_private_reads_require_auth(self):
        async with self.client() as client:
            characters = await client.get("/characters")
            teams = await client.get("/teams")

        self.assertEqual(characters.status_code, 401)
        self.assertEqual(teams.status_code, 401)

    async def test_cors_preflight_allows_deck_composition_put(self):
        async with self.client() as client:
            response = await client.options(
                "/characters/example/deck/composition",
                headers={
                    "Origin": "http://127.0.0.1:5173",
                    "Access-Control-Request-Method": "PUT",
                    "Access-Control-Request-Headers": (
                        "authorization,content-type,ngrok-skip-browser-warning"
                    ),
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://127.0.0.1:5173",
        )
        self.assertIn("PUT", response.headers.get("access-control-allow-methods", ""))

    async def test_authenticated_reads_succeed(self):
        async with self.client() as client:
            access_token = await self.login(client)
            characters = await client.get("/characters", headers=self.auth_headers(access_token))
            teams = await client.get("/teams", headers=self.auth_headers(access_token))
            me = await client.get("/auth/me", headers=self.auth_headers(access_token))

        self.assertEqual(characters.status_code, 200)
        self.assertEqual(teams.status_code, 200)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["role"], "admin")

    async def test_admin_account_management_and_last_admin_guard(self):
        async with self.client() as client:
            access_token = await self.login(client)
            headers = self.auth_headers(access_token)
            me = await client.get("/auth/me", headers=headers)

            last_admin_demote = await client.patch(
                f"/accounts/{me.json()['id']}",
                json={"role": "player"},
                headers=headers,
            )
            player, _ = await self.create_account(client, headers, "player")
            promote = await client.patch(
                f"/accounts/{player['id']}",
                json={"role": "admin"},
                headers=headers,
            )
            demote = await client.patch(
                f"/accounts/{player['id']}",
                json={"role": "player"},
                headers=headers,
            )
            accounts = await client.get("/accounts", headers=headers)

        self.assertEqual(last_admin_demote.status_code, 409)
        self.assertEqual(promote.status_code, 200)
        self.assertEqual(promote.json()["role"], "admin")
        self.assertEqual(demote.status_code, 200)
        self.assertEqual(demote.json()["role"], "player")
        self.assertEqual(accounts.status_code, 200)
        self.assertTrue(any(account["id"] == player["id"] for account in accounts.json()))

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

    async def test_admin_can_bind_and_unbind_character_owner(self):
        async with self.client() as client:
            access_token = await self.login(client)
            headers = self.auth_headers(access_token)
            player, _ = await self.create_account(client, headers, "player")
            slug = f"owner-bind-{uuid4().hex}"

            created = await client.post(
                "/characters",
                json={
                    "slug": slug,
                    "name": "Owner Bind Hero",
                    "race": "Human",
                    "stats": {"corps": 50, "mental": 50, "social": 50},
                },
                headers=headers,
            )
            bound = await client.patch(
                f"/characters/{slug}",
                json={"ownerUserId": player["id"]},
                headers=headers,
            )
            unbound = await client.patch(
                f"/characters/{slug}",
                json={"ownerUserId": None},
                headers=headers,
            )

        self.assertEqual(created.status_code, 201)
        self.assertIsNone(created.json()["ownerUserId"])
        self.assertEqual(bound.status_code, 200)
        self.assertEqual(bound.json()["ownerUserId"], player["id"])
        self.assertEqual(bound.json()["ownerUsername"], player["username"])
        self.assertEqual(unbound.status_code, 200)
        self.assertIsNone(unbound.json()["ownerUserId"])
        self.assertIsNone(unbound.json()["ownerUsername"])

    async def test_player_visibility_and_owned_character_write_rules(self):
        async with self.client() as client:
            access_token = await self.login(client)
            admin_headers = self.auth_headers(access_token)
            player, player_headers = await self.create_account(client, admin_headers, "player")
            owned_slug = f"owned-{uuid4().hex}"
            teammate_slug = f"teammate-{uuid4().hex}"
            unrelated_slug = f"unrelated-{uuid4().hex}"
            team_uuid = str(uuid4())
            unrelated_team_uuid = str(uuid4())

            for payload in (
                {
                    "slug": owned_slug,
                    "name": "Owned Hero",
                    "race": "Human",
                    "ownerUserId": player["id"],
                },
                {
                    "slug": teammate_slug,
                    "name": "Team Mate",
                    "race": "Elf",
                },
                {
                    "slug": unrelated_slug,
                    "name": "Unrelated Hero",
                    "race": "Dwarf",
                },
            ):
                response = await client.post(
                    "/characters",
                    json={
                        **payload,
                        "stats": {"corps": 50, "mental": 50, "social": 50},
                    },
                    headers=admin_headers,
                )
                self.assertEqual(response.status_code, 201, response.text)

            await client.post("/teams", json={"uuid": team_uuid, "name": "Player Team"}, headers=admin_headers)
            await client.post(f"/teams/{team_uuid}/characters/{owned_slug}", headers=admin_headers)
            await client.post(f"/teams/{team_uuid}/characters/{teammate_slug}", headers=admin_headers)
            await client.post(
                "/teams",
                json={"uuid": unrelated_team_uuid, "name": "Hidden Team"},
                headers=admin_headers,
            )
            await client.post(f"/teams/{unrelated_team_uuid}/characters/{unrelated_slug}", headers=admin_headers)

            player_create_character = await client.post(
                "/characters",
                json={
                    "slug": f"forbidden-{uuid4().hex}",
                    "name": "Forbidden",
                    "race": "Human",
                    "stats": {"corps": 50, "mental": 50, "social": 50},
                },
                headers=player_headers,
            )
            player_create_team = await client.post(
                "/teams",
                json={"uuid": str(uuid4()), "name": "Forbidden Team"},
                headers=player_headers,
            )
            player_teams = await client.get("/teams", headers=player_headers)
            visible_team = await client.get(f"/teams/{team_uuid}", headers=player_headers)
            hidden_team = await client.get(f"/teams/{unrelated_team_uuid}", headers=player_headers)
            player_characters = await client.get("/characters", headers=player_headers)
            owned_detail = await client.get(f"/characters/{owned_slug}", headers=player_headers)
            teammate_detail = await client.get(f"/characters/{teammate_slug}", headers=player_headers)
            unrelated_detail = await client.get(f"/characters/{unrelated_slug}", headers=player_headers)
            owned_patch = await client.patch(
                f"/characters/{owned_slug}",
                json={"gold": 5, "notes": "Player note"},
                headers=player_headers,
            )
            owned_note = await client.post(
                f"/characters/{owned_slug}/notes",
                json={"title": "Player", "content": "Owned note tab"},
                headers=player_headers,
            )
            owned_inventory = await client.post(
                f"/characters/{owned_slug}/inventory-categories",
                json={"name": "Player Bag"},
                headers=player_headers,
            )
            teammate_patch = await client.patch(
                f"/characters/{teammate_slug}",
                json={"gold": 99},
                headers=player_headers,
            )
            unrelated_patch = await client.patch(
                f"/characters/{unrelated_slug}",
                json={"gold": 99},
                headers=player_headers,
            )

            app.dependency_overrides[get_object_storage] = lambda: FakeBackgroundStorage()
            try:
                owned_upload = await client.post(
                    f"/characters/{owned_slug}/background-upload",
                    json={"filename": "bg.webp", "content_type": "image/webp", "size": 1024},
                    headers=player_headers,
                )
                teammate_upload = await client.post(
                    f"/characters/{teammate_slug}/background-upload",
                    json={"filename": "bg.webp", "content_type": "image/webp", "size": 1024},
                    headers=player_headers,
                )
            finally:
                app.dependency_overrides.pop(get_object_storage, None)

        self.assertEqual(player_create_character.status_code, 403)
        self.assertEqual(player_create_team.status_code, 403)
        self.assertEqual(player_teams.status_code, 200)
        self.assertEqual([team["uuid"] for team in player_teams.json()], [team_uuid])
        self.assertEqual(visible_team.status_code, 200)
        self.assertEqual({character["slug"] for character in visible_team.json()["characters"]}, {owned_slug, teammate_slug})
        self.assertEqual(hidden_team.status_code, 404)
        self.assertEqual(player_characters.status_code, 200)
        self.assertEqual({character["slug"] for character in player_characters.json()}, {owned_slug, teammate_slug})
        self.assertEqual(owned_detail.status_code, 200)
        self.assertEqual(teammate_detail.status_code, 200)
        self.assertEqual(unrelated_detail.status_code, 404)
        self.assertEqual(owned_patch.status_code, 200)
        self.assertEqual(owned_patch.json()["gold"], 5)
        self.assertEqual(owned_note.status_code, 201)
        self.assertEqual(owned_inventory.status_code, 201)
        self.assertEqual(teammate_patch.status_code, 403)
        self.assertEqual(unrelated_patch.status_code, 403)
        self.assertEqual(owned_upload.status_code, 200)
        self.assertEqual(teammate_upload.status_code, 403)

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

    async def test_invention_import_runs_once_and_preserves_catalogue_changes(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = os.path.join(temp_dir, "inventions.db")
            isolated_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            try:
                await run_migrations(isolated_engine)
                with closing(sqlite3.connect(db_path)) as conn, conn:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM inventions").fetchone()[0], 100)
                    self.assertEqual(conn.execute("SELECT name, description FROM inventions WHERE id = 1").fetchone(), ("Rayon mortel", ""))
                    self.assertEqual(conn.execute("SELECT COUNT(DISTINCT name_key) FROM inventions").fetchone()[0], 100)
                    columns = {row[1] for row in conn.execute("PRAGMA table_info(characters)")}
                    self.assertIn("invengineer_enabled", columns)
                    conn.execute("UPDATE inventions SET is_active = 0 WHERE id = 1")
                await run_migrations(isolated_engine)
                with closing(sqlite3.connect(db_path)) as conn, conn:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM inventions").fetchone()[0], 100)
                    self.assertEqual(conn.execute("SELECT is_active FROM inventions WHERE id = 1").fetchone()[0], 0)
            finally:
                await isolated_engine.dispose()

    async def test_invention_catalogue_requires_admin_and_rejects_duplicates(self):
        async with self.client() as client:
            headers = self.auth_headers(await self.login(client))
            _, player_headers = await self.create_account(client, headers)
            name = f"Inventor tool {uuid4().hex}"
            self.assertEqual((await client.get("/inventions")).status_code, 401)
            self.assertEqual((await client.get("/inventions", headers=player_headers)).status_code, 403)
            self.assertEqual((await client.post("/inventions", json={"name": name}, headers=player_headers)).status_code, 403)
            self.assertEqual((await client.post("/inventions", json={"name": "   "}, headers=headers)).status_code, 422)
            added = await client.post("/inventions", json={"name": name}, headers=headers)
            self.assertEqual(added.status_code, 201, added.text)
            invention = added.json()
            self.assertEqual(invention["description"], "")
            duplicate = await client.post("/inventions", json={"name": f" {name.upper()} "}, headers=headers)
            self.assertEqual(duplicate.status_code, 409)
            route = f"/inventions/{invention['id']}"
            self.assertEqual((await client.delete(route, headers=player_headers)).status_code, 403)
            self.assertEqual((await client.delete(route, headers=headers)).status_code, 204)
            catalogue = await client.get("/inventions", headers=headers)
            self.assertNotIn(invention["id"], {item["id"] for item in catalogue.json()})
            restored = await client.post("/inventions", json={"name": name}, headers=headers)
            self.assertEqual(restored.status_code, 201)
            self.assertEqual(restored.json()["id"], invention["id"])
            await client.delete(route, headers=headers)

    async def test_invengineer_draw_replaces_associations_and_preserves_existing_items(self):
        async with self.client() as client:
            headers = self.auth_headers(await self.login(client))
            owner, owner_headers = await self.create_account(client, headers)
            _, outsider_headers = await self.create_account(client, headers)
            slug = f"inventor-{uuid4().hex}"
            created = await client.post("/characters", json={
                "slug": slug, "name": "Inventor", "race": "Human", "ownerUserId": owner["id"],
                "stats": {"corps": 50, "mental": 50, "social": 50},
            }, headers=headers)
            self.assertEqual(created.status_code, 201, created.text)
            character_id = created.json()["id"]
            base = f"/characters/{slug}"
            self.assertEqual((await client.get(base + "/inventions", headers=owner_headers)).json()["items"], [])
            self.assertEqual((await client.post(base + "/inventions/draw", headers=owner_headers)).status_code, 403)
            self.assertEqual((await client.patch(base + "/invengineer", json={"enabled": True}, headers=owner_headers)).status_code, 403)
            enabled = await client.patch(base + "/invengineer", json={"enabled": True}, headers=headers)
            self.assertEqual(enabled.status_code, 200, enabled.text)
            self.assertTrue((await client.get(base, headers=owner_headers)).json()["invengineerEnabled"])
            self.assertEqual((await client.get(base + "/inventions", headers=outsider_headers)).status_code, 404)
            self.assertEqual((await client.post(base + "/inventions/draw", headers=outsider_headers)).status_code, 404)

            first = await client.post(base + "/inventions/draw", headers=owner_headers)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(len(first.json()["items"]), 5)
            self.assertEqual(len({item["id"] for item in first.json()["items"]}), 5)
            # Catalogue removals do not remove already assigned inventions.
            removed = first.json()["items"][0]
            try:
                self.assertEqual((await client.delete(f"/inventions/{removed['id']}", headers=headers)).status_code, 204)
                read = await client.get(base + "/inventions", headers=owner_headers)
                self.assertEqual(read.json(), first.json())
                # There is intentionally no server cooldown: only the browser blocks redraws.
                second = await client.post(base + "/inventions/draw", headers=owner_headers)
                self.assertEqual(second.status_code, 200, second.text)
                self.assertNotIn(removed["id"], {item["id"] for item in second.json()["items"]})
                self.assertEqual((await client.get(base + "/inventions", headers=owner_headers)).json(), second.json())
                with closing(sqlite3.connect(_db_path)) as conn, conn:
                    rows = conn.execute("SELECT invention_id FROM character_inventions WHERE character_id = ? ORDER BY position", (character_id,)).fetchall()
                self.assertEqual([row[0] for row in rows], [item["id"] for item in second.json()["items"]])
                self.assertEqual(len(rows), 5)
                await client.patch(base + "/invengineer", json={"enabled": False}, headers=headers)
                self.assertEqual((await client.post(base + "/inventions/draw", headers=owner_headers)).status_code, 403)
                retained = (await client.get(base + "/inventions", headers=owner_headers)).json()
                self.assertFalse(retained["enabled"])
                self.assertEqual(retained["items"], second.json()["items"])
                async with SessionLocal() as session:
                    character = await session.get(Character, character_id)
                    await session.delete(character)
                    await session.commit()
                with closing(sqlite3.connect(_db_path)) as conn, conn:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM character_inventions WHERE character_id = ?", (character_id,)).fetchone()[0], 0)
            finally:
                await client.post("/inventions", json={"name": removed["name"]}, headers=headers)

    async def test_invention_team_read_only_small_catalogue_and_concurrent_replacement(self):
        async with self.client() as client:
            headers = self.auth_headers(await self.login(client))
            owner, owner_headers = await self.create_account(client, headers)
            teammate, teammate_headers = await self.create_account(client, headers)
            slug = f"inv-owner-{uuid4().hex}"
            teammate_slug = f"inv-reader-{uuid4().hex}"
            team_uuid = str(uuid4())
            for character_slug, owner_id in ((slug, owner["id"]), (teammate_slug, teammate["id"])):
                created = await client.post("/characters", json={
                    "slug": character_slug, "name": character_slug, "race": "Human", "ownerUserId": owner_id,
                    "stats": {"corps": 50, "mental": 50, "social": 50},
                }, headers=headers)
                self.assertEqual(created.status_code, 201, created.text)
            await client.post("/teams", json={"uuid": team_uuid, "name": "Inventor Team"}, headers=headers)
            await client.post(f"/teams/{team_uuid}/characters/{slug}", headers=headers)
            await client.post(f"/teams/{team_uuid}/characters/{teammate_slug}", headers=headers)
            base = f"/characters/{slug}"
            await client.patch(base + "/invengineer", json={"enabled": True}, headers=headers)
            self.assertFalse((await client.get(base + "/inventions", headers=teammate_headers)).json()["permissions"]["canDraw"])
            self.assertEqual((await client.post(base + "/inventions/draw", headers=teammate_headers)).status_code, 403)
            draws = await asyncio.gather(*[
                client.post(base + "/inventions/draw", headers=owner_headers) for _ in range(2)
            ])
            for draw in draws:
                self.assertEqual(draw.status_code, 200, draw.text)
                self.assertEqual(len({item["id"] for item in draw.json()["items"]}), 5)
            state = (await client.get(base + "/inventions", headers=owner_headers)).json()
            self.assertIn(state["items"], [draw.json()["items"] for draw in draws])
            # With exactly 5 active entries, all 5 may repeat on a later draw.
            with closing(sqlite3.connect(_db_path)) as conn, conn:
                active_ids = [row[0] for row in conn.execute("SELECT id FROM inventions WHERE is_active = 1")]
                conn.execute("UPDATE inventions SET is_active = 0")
                conn.executemany("UPDATE inventions SET is_active = 1 WHERE id = ?", [(item["id"],) for item in state["items"]])
            try:
                repeat = await client.post(base + "/inventions/draw", headers=owner_headers)
                self.assertEqual(repeat.status_code, 200, repeat.text)
                self.assertEqual({item["id"] for item in state["items"]}, {item["id"] for item in repeat.json()["items"]})
                with closing(sqlite3.connect(_db_path)) as conn, conn:
                    conn.execute("UPDATE inventions SET is_active = 0 WHERE id = ?", (state["items"][0]["id"],))
                rejected = await client.post(base + "/inventions/draw", headers=owner_headers)
                self.assertEqual(rejected.status_code, 409)
                self.assertEqual((await client.get(base + "/inventions", headers=owner_headers)).json(), repeat.json())
            finally:
                with closing(sqlite3.connect(_db_path)) as conn, conn:
                    conn.execute("UPDATE inventions SET is_active = 0")
                    conn.executemany("UPDATE inventions SET is_active = 1 WHERE id = ?", [(item_id,) for item_id in active_ids])

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
        self.assertIn("character_notes", tables)
        with sqlite3.connect(_db_path) as conn:
            character_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(characters)")
            }
            user_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(users)")
            }
            note_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(character_notes)")
            }
        self.assertIn("background_url", character_columns)
        self.assertIn("owner_user_id", character_columns)
        self.assertIn("role", user_columns)
        self.assertEqual(
            {"id", "character_id", "title", "content", "sort_order", "created_at", "updated_at"},
            note_columns,
        )

    async def test_character_note_migration_copies_legacy_notes(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = os.path.join(temp_dir, "legacy.db")
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE schema_migrations (
                        version VARCHAR(100) NOT NULL PRIMARY KEY,
                        applied_at DATETIME NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE characters (
                        id INTEGER NOT NULL,
                        notes TEXT,
                        PRIMARY KEY (id)
                    )
                    """
                )
                conn.executemany(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                    [(version,) for version, _ in MIGRATIONS if version != "011_character_note_tabs"],
                )
                conn.executemany(
                    "INSERT INTO characters (id, notes) VALUES (?, ?)",
                    [(1, "Legacy campaign note"), (2, None)],
                )
                conn.commit()
            finally:
                conn.close()

            legacy_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
            try:
                await run_migrations(legacy_engine)
            finally:
                await legacy_engine.dispose()

            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT character_id, title, content, sort_order FROM character_notes ORDER BY character_id"
                ).fetchall()
            finally:
                conn.close()

        self.assertEqual(
            rows,
            [
                (1, "Notes", "Legacy campaign note", 0),
                (2, "Notes", "", 0),
            ],
        )

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

    async def test_character_notes_default_tab_and_legacy_patch_compatibility(self):
        async with self.client() as client:
            access_token = await self.login(client)
            headers = self.auth_headers(access_token)
            slug = f"notes-{uuid4().hex}"

            await client.post(
                "/characters",
                json={
                    "slug": slug,
                    "name": "Notes Hero",
                    "race": "Human",
                    "stats": {"corps": 50, "mental": 50, "social": 50},
                    "notes": "Opening note",
                },
                headers=headers,
            )
            detail = await client.get(f"/characters/{slug}", headers=headers)
            list_response = await client.get("/characters", headers=headers)
            legacy_patch = await client.patch(
                f"/characters/{slug}",
                json={"notes": "Updated through legacy field"},
                headers=headers,
            )
            patched_detail = await client.get(f"/characters/{slug}", headers=headers)

        self.assertEqual(detail.status_code, 200)
        body = detail.json()
        self.assertEqual(body["notes"], "Opening note")
        self.assertEqual(len(body["noteTabs"]), 1)
        self.assertEqual(body["noteTabs"][0]["title"], "Notes")
        self.assertEqual(body["noteTabs"][0]["content"], "Opening note")
        listed = next(item for item in list_response.json() if item["slug"] == slug)
        self.assertEqual(listed["notes"], "Opening note")
        self.assertNotIn("noteTabs", listed)
        self.assertEqual(legacy_patch.status_code, 200)
        self.assertEqual(legacy_patch.json()["notes"], "Updated through legacy field")
        self.assertEqual(patched_detail.json()["noteTabs"][0]["content"], "Updated through legacy field")

    async def test_character_note_tab_crud_reorder_and_scoping(self):
        async with self.client() as client:
            access_token = await self.login(client)
            headers = self.auth_headers(access_token)
            first_slug = f"tabs-a-{uuid4().hex}"
            second_slug = f"tabs-b-{uuid4().hex}"

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

            first_detail = await client.get(f"/characters/{first_slug}", headers=headers)
            default_note = first_detail.json()["noteTabs"][0]
            session_note = await client.post(
                f"/characters/{first_slug}/notes",
                json={"title": "Session", "content": "Session notes"},
                headers=headers,
            )
            duplicate = await client.post(
                f"/characters/{first_slug}/notes",
                json={"title": "Session"},
                headers=headers,
            )
            wrong_character = await client.patch(
                f"/characters/{second_slug}/notes/{session_note.json()['id']}",
                json={"content": "Should fail"},
                headers=headers,
            )
            renamed = await client.patch(
                f"/characters/{first_slug}/notes/{session_note.json()['id']}",
                json={"title": "Clues", "content": "Clue notes"},
                headers=headers,
            )
            reordered = await client.patch(
                f"/characters/{first_slug}/notes/reorder",
                json={
                    "items": [
                        {"id": session_note.json()["id"], "sortOrder": 0},
                        {"id": default_note["id"], "sortOrder": 1},
                    ]
                },
                headers=headers,
            )
            deleted = await client.delete(
                f"/characters/{first_slug}/notes/{default_note['id']}",
                headers=headers,
            )
            last_delete = await client.delete(
                f"/characters/{first_slug}/notes/{session_note.json()['id']}",
                headers=headers,
            )

        self.assertEqual(session_note.status_code, 201)
        self.assertEqual(session_note.json()["sortOrder"], 1)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(wrong_character.status_code, 404)
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["title"], "Clues")
        self.assertEqual(renamed.json()["content"], "Clue notes")
        self.assertEqual(reordered.status_code, 200)
        self.assertEqual([note["title"] for note in reordered.json()], ["Clues", "Notes"])
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(last_delete.status_code, 409)

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

    async def test_hearthstone_pack_rarity_weights(self):
        self.assertGreater(PACK_RARITY_TARGETS["EPIC"], HEARTHSTONE_RARITY_RATES["EPIC"])
        self.assertGreater(PACK_RARITY_TARGETS["LEGENDARY"], HEARTHSTONE_RARITY_RATES["LEGENDARY"])

        cards = [
            {"id": f"{rarity}-{index}", "rarity": rarity}
            for rarity in PACK_RARITY_TARGETS
            for index in range(25)
        ]
        random_source = random.Random(20261006)
        ordinary_weights = _ordinary_slot_weights(5)
        rare_plus_total = sum(PACK_RARITY_TARGETS[rarity] for rarity in RARE_OR_BETTER)

        for rarity, target in PACK_RARITY_TARGETS.items():
            guaranteed_share = (
                PACK_RARITY_TARGETS[rarity] / rare_plus_total
                if rarity in RARE_OR_BETTER
                else 0
            )
            expected_per_pack = guaranteed_share + 4 * ordinary_weights[rarity]
            self.assertAlmostEqual(expected_per_pack, 5 * target / 100)

        for _ in range(100):
            pack = weighted_pack_sample(cards, 5, random_source)
            self.assertEqual(len({card["id"] for card in pack}), 5)
            self.assertTrue(any(card["rarity"] != "COMMON" for card in pack))

    async def test_hearthstone_catalog_activation_and_deck_lifecycle(self):
        async with self.client() as client:
            access_token = await self.login(client)
            admin_headers = self.auth_headers(access_token)
            player, player_headers = await self.create_account(client, admin_headers, "player")
            slug = f"hearth-{uuid4().hex}"
            created = await client.post(
                "/characters",
                json={
                    "slug": slug,
                    "name": "Hearth Hero",
                    "race": "Human",
                    "ownerUserId": player["id"],
                    "stats": {"corps": 50, "mental": 50, "social": 50},
                },
                headers=admin_headers,
            )
            self.assertEqual(created.status_code, 201, created.text)

            catalog = await client.get(
                "/hearthstone/cards",
                params={"q": "heros defunt", "pageSize": 10},
                headers=player_headers,
            )
            self.assertEqual(catalog.status_code, 200, catalog.text)
            catalog_body = catalog.json()
            catalog_card = next(item for item in catalog_body["items"] if item["id"] == "AT_003")
            self.assertEqual(
                catalog_card["renderUrl"],
                "https://art.hearthstonejson.com/v1/render/latest/frFR/512x/AT_003.png",
            )
            self.assertEqual(catalog_card["cardSet"], "TGT")
            self.assertEqual(catalog_card["cardSetName"], "Le Grand Tournoi")
            self.assertEqual(len(catalog_body["sets"]), 40)
            self.assertEqual(
                sum(card_set["cardCount"] for card_set in catalog_body["sets"]),
                5845,
            )
            self.assertIn(
                {"code": "__UNASSIGNED__", "name": "Ensemble fondamental sans code de set", "cardCount": 127},
                catalog_body["sets"],
            )
            filtered_catalog = await client.get(
                "/hearthstone/cards",
                params={"cardSet": "TGT", "pageSize": 100},
                headers=player_headers,
            )
            self.assertEqual(filtered_catalog.status_code, 200, filtered_catalog.text)
            self.assertEqual(filtered_catalog.json()["total"], 132)
            self.assertTrue(all(item["cardSet"] == "TGT" for item in filtered_catalog.json()["items"]))

            forbidden_activation = await client.patch(
                f"/characters/{slug}/hearthstomancer",
                json={"enabled": True},
                headers=player_headers,
            )
            self.assertEqual(forbidden_activation.status_code, 403)
            activation = await client.patch(
                f"/characters/{slug}/hearthstomancer",
                json={"enabled": True},
                headers=admin_headers,
            )
            self.assertEqual(activation.status_code, 200, activation.text)

            opened_pack = await client.post(
                f"/characters/{slug}/deck/pack/open",
                json={"cardSet": "TGT"},
                headers=player_headers,
            )
            self.assertEqual(opened_pack.status_code, 200, opened_pack.text)
            pack_cards = opened_pack.json()["cards"]
            self.assertEqual(len(pack_cards), 5)
            self.assertEqual(len({card["id"] for card in pack_cards}), 5)
            self.assertTrue(all(card["cardSet"] == "TGT" for card in pack_cards))
            saved_pack = await client.post(
                f"/characters/{slug}/deck/pack/save",
                json={"sourceCardIds": [card["id"] for card in pack_cards]},
                headers=player_headers,
            )
            self.assertEqual(saved_pack.status_code, 200, saved_pack.text)
            self.assertEqual(saved_pack.json()["counts"]["total"], 5)
            self.assertTrue(all(
                definition["isVariant"] is False
                for definition in saved_pack.json()["definitions"]
            ))

            composition = await client.put(
                f"/characters/{slug}/deck/composition",
                json={
                    "definitions": [
                        {
                            "sourceCardId": "AT_003",
                            "name": "Heros JDR",
                            "attack": 7,
                            "text": "Effet personnalise",
                            "normalCount": 1,
                            "goldenCount": 0,
                        },
                        {
                            "sourceCardId": "AT_003",
                            "name": "Heros JDR",
                            "attack": 7,
                            "text": "Effet personnalise",
                            "normalCount": 0,
                            "goldenCount": 1,
                        },
                    ]
                },
                headers=player_headers,
            )
            self.assertEqual(composition.status_code, 200, composition.text)
            body = composition.json()
            self.assertEqual(body["counts"], {"total": 2, "remaining": 2, "drawn": 0})
            self.assertEqual(len(body["definitions"]), 1)
            self.assertEqual(body["definitions"][0]["normalCount"], 1)
            self.assertEqual(body["definitions"][0]["goldenCount"], 1)
            self.assertTrue(body["definitions"][0]["isVariant"])

            for _ in range(2):
                drawn = await client.post(f"/characters/{slug}/deck/draw", headers=player_headers)
                self.assertEqual(drawn.status_code, 200, drawn.text)
            state = drawn.json()
            normal = next(card for card in state["drawnCards"] if not card["isGolden"])
            golden = next(card for card in state["drawnCards"] if card["isGolden"])

            golden_play = await client.post(
                f"/characters/{slug}/deck/copies/{golden['copyId']}/play",
                headers=player_headers,
            )
            self.assertEqual(golden_play.status_code, 409)
            played = await client.post(
                f"/characters/{slug}/deck/copies/{normal['copyId']}/play",
                headers=player_headers,
            )
            self.assertEqual(played.status_code, 200, played.text)
            self.assertIsNotNone(played.json()["undoablePlay"])
            undone = await client.post(f"/characters/{slug}/deck/undo-play", headers=player_headers)
            self.assertEqual(undone.status_code, 200, undone.text)
            self.assertEqual(undone.json()["counts"]["drawn"], 2)

            forbidden_drawn_removal = await client.post(
                f"/characters/{slug}/deck/remove",
                json={
                    "zone": "drawn",
                    "definitionId": golden["definition"]["id"],
                    "isGolden": True,
                    "copyId": golden["copyId"],
                },
                headers=player_headers,
            )
            self.assertEqual(forbidden_drawn_removal.status_code, 422)

            discarded = await client.post(
                f"/characters/{slug}/deck/copies/{normal['copyId']}/discard",
                headers=player_headers,
            )
            self.assertEqual(discarded.status_code, 200, discarded.text)
            discarded_golden = await client.post(
                f"/characters/{slug}/deck/copies/{golden['copyId']}/discard",
                headers=player_headers,
            )
            self.assertEqual(discarded_golden.status_code, 200, discarded_golden.text)
            removed_golden = await client.post(
                f"/characters/{slug}/deck/remove",
                json={
                    "zone": "deck",
                    "definitionId": golden["definition"]["id"],
                    "isGolden": True,
                },
                headers=player_headers,
            )
            self.assertEqual(removed_golden.status_code, 200, removed_golden.text)
            self.assertEqual(removed_golden.json()["counts"]["total"], 1)

            definition = removed_golden.json()["definitions"][0]
            removed_normal = await client.post(
                f"/characters/{slug}/deck/remove",
                json={
                    "zone": "deck",
                    "definitionId": definition["id"],
                    "isGolden": False,
                },
                headers=player_headers,
            )
            self.assertEqual(removed_normal.status_code, 200, removed_normal.text)
            self.assertEqual(removed_normal.json()["definitions"], [])

            deactivation = await client.patch(
                f"/characters/{slug}/hearthstomancer",
                json={"enabled": False},
                headers=admin_headers,
            )
            self.assertEqual(deactivation.status_code, 200)
            inactive_read = await client.get(f"/characters/{slug}/deck", headers=player_headers)
            inactive_draw = await client.post(f"/characters/{slug}/deck/draw", headers=player_headers)

        self.assertEqual(inactive_read.status_code, 200)
        self.assertFalse(inactive_read.json()["enabled"])
        self.assertEqual(inactive_draw.status_code, 409)

    async def test_hearthstomancer_team_read_only_and_play_finalization(self):
        async with self.client() as client:
            access_token = await self.login(client)
            admin_headers = self.auth_headers(access_token)
            owner, owner_headers = await self.create_account(client, admin_headers, "player")
            teammate, teammate_headers = await self.create_account(client, admin_headers, "player")
            owner_slug = f"deck-owner-{uuid4().hex}"
            teammate_slug = f"deck-reader-{uuid4().hex}"
            team_uuid = str(uuid4())

            for slug, owner_id in ((owner_slug, owner["id"]), (teammate_slug, teammate["id"])):
                response = await client.post(
                    "/characters",
                    json={
                        "slug": slug,
                        "name": slug,
                        "race": "Human",
                        "ownerUserId": owner_id,
                        "stats": {"corps": 50, "mental": 50, "social": 50},
                    },
                    headers=admin_headers,
                )
                self.assertEqual(response.status_code, 201, response.text)
            await client.post("/teams", json={"uuid": team_uuid, "name": "Deck Team"}, headers=admin_headers)
            await client.post(f"/teams/{team_uuid}/characters/{owner_slug}", headers=admin_headers)
            await client.post(f"/teams/{team_uuid}/characters/{teammate_slug}", headers=admin_headers)
            await client.patch(
                f"/characters/{owner_slug}/hearthstomancer",
                json={"enabled": True},
                headers=admin_headers,
            )
            await client.put(
                f"/characters/{owner_slug}/deck/composition",
                json={"definitions": [{"sourceCardId": "AT_003", "normalCount": 1}]},
                headers=owner_headers,
            )

            teammate_read = await client.get(f"/characters/{owner_slug}/deck", headers=teammate_headers)
            teammate_draw = await client.post(f"/characters/{owner_slug}/deck/draw", headers=teammate_headers)
            self.assertEqual(teammate_read.status_code, 200, teammate_read.text)
            self.assertFalse(teammate_read.json()["permissions"]["canManage"])
            self.assertEqual(teammate_draw.status_code, 403)

            drawn = await client.post(f"/characters/{owner_slug}/deck/draw", headers=owner_headers)
            copy_id = drawn.json()["drawnCards"][0]["copyId"]
            played = await client.post(
                f"/characters/{owner_slug}/deck/copies/{copy_id}/play",
                headers=owner_headers,
            )
            self.assertIsNotNone(played.json()["undoablePlay"])
            reset = await client.post(f"/characters/{owner_slug}/deck/reset", headers=owner_headers)
            late_undo = await client.post(f"/characters/{owner_slug}/deck/undo-play", headers=owner_headers)

        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.json()["counts"]["total"], 0)
        self.assertEqual(reset.json()["definitions"], [])
        self.assertEqual(late_undo.status_code, 409)

    async def test_concurrent_hearthstomancer_draws_never_return_the_same_copy(self):
        async with self.client() as client:
            access_token = await self.login(client)
            headers = self.auth_headers(access_token)
            slug = f"deck-concurrent-{uuid4().hex}"
            await client.post(
                "/characters",
                json={
                    "slug": slug,
                    "name": "Concurrent Hero",
                    "race": "Human",
                    "stats": {"corps": 50, "mental": 50, "social": 50},
                },
                headers=headers,
            )
            await client.patch(
                f"/characters/{slug}/hearthstomancer",
                json={"enabled": True},
                headers=headers,
            )
            await client.put(
                f"/characters/{slug}/deck/composition",
                json={"definitions": [{"sourceCardId": "AT_003", "normalCount": 2}]},
                headers=headers,
            )

            responses = await asyncio.gather(
                client.post(f"/characters/{slug}/deck/draw", headers=headers),
                client.post(f"/characters/{slug}/deck/draw", headers=headers),
            )
            self.assertTrue(all(response.status_code in {200, 409} for response in responses))
            successful = [response for response in responses if response.status_code == 200]
            self.assertGreaterEqual(len(successful), 1)
            state = await client.get(f"/characters/{slug}/deck", headers=headers)

        drawn_ids = [card["copyId"] for card in state.json()["drawnCards"]]
        self.assertEqual(len(drawn_ids), len(set(drawn_ids)))
        self.assertEqual(len(drawn_ids), len(successful))
