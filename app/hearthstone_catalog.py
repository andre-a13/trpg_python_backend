import json
import re
import secrets
import unicodedata
from collections import Counter
from functools import lru_cache
from html import unescape
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).with_name("data") / "cards.frFR.json"
_TAG_RE = re.compile(r"<[^>]+>")
UNASSIGNED_SET_CODE = "__UNASSIGNED__"

# Published/observed Hearthstone pack rates are approximately 71.65% common,
# 22.84% rare, 4.42% epic and 1.10% legendary per card. The application uses
# a deliberately modest boost for epic and legendary cards while retaining a
# guaranteed rare-or-better slot in every five-card pack.
HEARTHSTONE_RARITY_RATES = {
    "COMMON": 71.65,
    "RARE": 22.84,
    "EPIC": 4.42,
    "LEGENDARY": 1.10,
}
PACK_RARITY_TARGETS = {
    "COMMON": 69.25,
    "RARE": 24.00,
    "EPIC": 5.25,
    "LEGENDARY": 1.50,
}
PACK_RARITIES = tuple(PACK_RARITY_TARGETS)
RARE_OR_BETTER = ("RARE", "EPIC", "LEGENDARY")

# HearthstoneJSON exposes stable enum codes in the `set` field. Keep the raw
# code for filtering and persistence, while exposing a readable French
# expansion name to the client. The two technical groups at the end are part
# of the supplied snapshot and must remain searchable.
CARD_SET_NAMES_FR = {
    "VANILLA": "Classique (version originale)",
    "CORE": "Ensemble fondamental",
    "EXPERT1": "Classique",
    "LEGACY": "Héritage",
    "HERO_SKINS": "Portraits de héros",
    "DEMON_HUNTER_INITIATE": "Initié chasseur de démons",
    "PATH_OF_ARTHAS": "Voie d’Arthas",
    "NAXX": "La Malédiction de Naxxramas",
    "GVG": "Gobelins et Gnomes",
    "BRM": "Mont Rochenoire",
    "TGT": "Le Grand Tournoi",
    "LOE": "La Ligue des explorateurs",
    "OG": "Les Murmures des Dieux très anciens",
    "KARA": "Une nuit à Karazhan",
    "GANGS": "Main basse sur Gadgetzan",
    "UNGORO": "Voyage au centre d’Un’Goro",
    "ICECROWN": "Chevaliers du Trône de glace",
    "LOOTAPALOOZA": "Kobolds et Catacombes",
    "GILNEAS": "Le Bois Maudit",
    "BOOMSDAY": "Projet Armageboum",
    "TROLL": "Les Jeux de Rastakhan",
    "DALARAN": "L’Éveil des ombres",
    "ULDUM": "Les Aventuriers d’Uldum",
    "DRAGONS": "L’Envol des Dragons",
    "YEAR_OF_THE_DRAGON": "L’Éveil de Galakrond",
    "BLACK_TEMPLE": "Les Cendres de l’Outreterre",
    "SCHOLOMANCE": "L’Académie Scholomance",
    "DARKMOON_FAIRE": "Folle journée à Sombrelune",
    "THE_BARRENS": "Forgés dans les Tarides",
    "STORMWIND": "Unis à Hurlevent",
    "ALTERAC_VALLEY": "Divisés dans la vallée d’Alterac",
    "THE_SUNKEN_CITY": "Au cœur de la cité engloutie",
    "REVENDRETH": "Meurtre au château Nathria",
    "RETURN_OF_THE_LICH_KING": "La Marche du Roi-Liche",
    "BATTLE_OF_THE_BANDS": "La Fête des légendes",
    "TITANS": "TITANS",
    "WILD_WEST": "Rixe en terres Ingrates",
    "WONDERS": "Cavernes du Temps",
    "PLACEHOLDER_202204": "Ensemble fondamental 2022 (technique)",
    UNASSIGNED_SET_CODE: "Ensemble fondamental sans code de set",
}

CARD_SET_ORDER = tuple(CARD_SET_NAMES_FR)


def normalize_effect_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    without_tags = _TAG_RE.sub("", value.replace("<br>", "\n").replace("<br/>", "\n"))
    return unescape(without_tags).replace("\r\n", "\n").strip()


def _search_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def illustration_url(card_id: str) -> str:
    return f"https://art.hearthstonejson.com/v1/512x/{card_id}.webp"


def render_url(card_id: str) -> str:
    return f"https://art.hearthstonejson.com/v1/render/latest/frFR/512x/{card_id}.png"


def card_set_code(card_set: Any) -> str:
    return card_set if isinstance(card_set, str) and card_set else UNASSIGNED_SET_CODE


def card_set_name(card_set: Any) -> str:
    code = card_set_code(card_set)
    return CARD_SET_NAMES_FR.get(code, code.replace("_", " ").title())


def serialize_catalog_card(card: dict[str, Any]) -> dict[str, Any]:
    card_id = card["id"]
    races = card.get("races")
    tribe = card.get("race")
    if not tribe and isinstance(races, list) and races:
        tribe = ", ".join(str(value) for value in races)
    return {
        "id": card_id,
        "name": card.get("name") or card_id,
        "cost": card.get("cost"),
        "attack": card.get("attack"),
        "health": card.get("health"),
        "durability": card.get("durability"),
        "text": normalize_effect_text(card.get("text")),
        "cardType": card.get("type"),
        "rarity": card.get("rarity"),
        "cardClass": card.get("cardClass"),
        "tribe": tribe,
        "spellSchool": card.get("spellSchool"),
        "cardSet": card.get("set"),
        "cardSetName": card_set_name(card.get("set")),
        "illustrationUrl": illustration_url(card_id),
        "renderUrl": render_url(card_id),
    }


@lru_cache(maxsize=1)
def collectible_cards() -> tuple[dict[str, Any], ...]:
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        raw_cards = json.load(handle)
    cards = [
        serialize_catalog_card(card)
        for card in raw_cards
        if card.get("collectible") is True and isinstance(card.get("id"), str)
    ]
    cards.sort(key=lambda card: (_search_key(card["name"]), card["id"]))
    return tuple(cards)


@lru_cache(maxsize=1)
def collectible_cards_by_id() -> dict[str, dict[str, Any]]:
    return {card["id"]: card for card in collectible_cards()}


def find_collectible_card(card_id: str) -> dict[str, Any] | None:
    return collectible_cards_by_id().get(card_id)


@lru_cache(maxsize=1)
def collectible_card_sets() -> tuple[dict[str, Any], ...]:
    counts = Counter(card_set_code(card.get("cardSet")) for card in collectible_cards())
    order = {code: index for index, code in enumerate(CARD_SET_ORDER)}
    rows = [
        {
            "code": code,
            "name": CARD_SET_NAMES_FR.get(code, code.replace("_", " ").title()),
            "cardCount": count,
        }
        for code, count in counts.items()
    ]
    rows.sort(key=lambda row: (order.get(row["code"], len(order)), row["name"].casefold()))
    return tuple(rows)


def search_collectible_cards(
    query: str,
    page: int,
    page_size: int,
    card_set: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    normalized_query = _search_key(query.strip())
    rows = collectible_cards()
    if normalized_query:
        rows = tuple(card for card in rows if normalized_query in _search_key(card["name"]))
    if card_set:
        rows = tuple(card for card in rows if card_set_code(card.get("cardSet")) == card_set)
    total = len(rows)
    start = (page - 1) * page_size
    return list(rows[start:start + page_size]), total


def _pack_rarity(card: dict[str, Any]) -> str:
    rarity = str(card.get("rarity") or "").upper()
    # Hearthstone's FREE cards have no pack rarity. Treat them like commons so
    # technical/core sets remain usable by the custom pack opener.
    return rarity if rarity in PACK_RARITY_TARGETS else "COMMON"


def _weighted_rarity_choice(
    pools: dict[str, list[dict[str, Any]]],
    weights: dict[str, float],
    allowed: tuple[str, ...],
    rng: Any,
) -> str | None:
    available = [rarity for rarity in allowed if pools.get(rarity) and weights.get(rarity, 0) > 0]
    if not available:
        return None

    threshold = rng.random() * sum(weights[rarity] for rarity in available)
    cumulative = 0.0
    for rarity in available:
        cumulative += weights[rarity]
        if threshold < cumulative:
            return rarity
    return available[-1]


def _ordinary_slot_weights(count: int) -> dict[str, float]:
    """Calibrate non-guaranteed slots so final five-card rates meet targets."""
    rare_plus_total = sum(PACK_RARITY_TARGETS[rarity] for rarity in RARE_OR_BETTER)
    guaranteed_share = {
        rarity: PACK_RARITY_TARGETS[rarity] / rare_plus_total
        for rarity in RARE_OR_BETTER
    }
    ordinary_slots = max(count - 1, 1)
    return {
        rarity: max(
            0.0,
            (
                count * PACK_RARITY_TARGETS[rarity] / 100
                - guaranteed_share.get(rarity, 0.0)
            ) / ordinary_slots,
        )
        for rarity in PACK_RARITIES
    }


def weighted_pack_sample(
    rows: list[dict[str, Any]],
    count: int = 5,
    rng: Any | None = None,
) -> list[dict[str, Any]]:
    if count <= 0 or len(rows) < count:
        return []

    random_source = rng or secrets.SystemRandom()
    pools = {rarity: [] for rarity in PACK_RARITIES}
    for card in rows:
        pools[_pack_rarity(card)].append(card)

    selected: list[dict[str, Any]] = []
    guaranteed_rarity = _weighted_rarity_choice(
        pools,
        PACK_RARITY_TARGETS,
        RARE_OR_BETTER,
        random_source,
    )
    if guaranteed_rarity is not None:
        guaranteed_pool = pools[guaranteed_rarity]
        selected.append(guaranteed_pool.pop(random_source.randrange(len(guaranteed_pool))))

    ordinary_weights = _ordinary_slot_weights(count) if guaranteed_rarity is not None else PACK_RARITY_TARGETS
    while len(selected) < count:
        rarity = _weighted_rarity_choice(pools, ordinary_weights, PACK_RARITIES, random_source)
        if rarity is None:
            return []
        pool = pools[rarity]
        selected.append(pool.pop(random_source.randrange(len(pool))))

    random_source.shuffle(selected)
    return selected


def random_collectible_cards(
    card_set: str,
    count: int = 5,
    rng: Any | None = None,
) -> list[dict[str, Any]]:
    rows = [
        card for card in collectible_cards()
        if card_set_code(card.get("cardSet")) == card_set
    ]
    return weighted_pack_sample(rows, count, rng)
