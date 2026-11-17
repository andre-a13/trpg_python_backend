"""Validate spreadsheet deck rows and propose conservative catalogue matches."""
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache

from pydantic import ValidationError

from app.hearthstone_catalog import collectible_cards, find_collectible_card
from app.schemas.hearthstone import DeckDefinitionInput, DeckImportSourceRow


def name_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in decomposed if not unicodedata.combining(c))).strip()


@lru_cache(maxsize=1)
def catalogue_by_name() -> dict[str, list[dict]]:
    names: dict[str, list[dict]] = {}
    for card in collectible_cards():
        names.setdefault(name_key(card["name"]), []).append(card)
    for cards in names.values():
        # Stable original editions avoid arbitrarily choosing a reprint.
        cards.sort(key=lambda card: (card["id"].startswith(("CORE_", "VAN_")), card["id"]))
    return names


def candidates_for(name: str) -> tuple[str, list[dict], str | None]:
    key = name_key(name)
    names = catalogue_by_name()
    if key in names:
        cards = names[key]
        return "matched", cards[:5], cards[0]["id"]
    # Known French/English wording in older character sheets. These remain
    # suggestions: the importer never confirms an approximate name silently.
    aliases = {
        "guerrier mogushan je sais pas quoi": "EX1_396",
        "le mercenaire de venture co": "CS2_227",
        "force tank max": "GVG_079",
        "corsair redoutable": "NEW1_022",
        "criniere haute de savannah": "EX1_534",
        "harpy furie des vents": "EX1_033",
        "ghoul mangeuse de chair": "tt_004",
    }
    ranked = sorted(((SequenceMatcher(None, key, other).ratio(), other) for other in names), reverse=True)
    candidates = [names[other][0] for score, other in ranked[:5] if score >= 0.70]
    alias = find_collectible_card(aliases.get(key, ""))
    if alias is not None:
        candidates = [alias] + [card for card in candidates if card["id"] != alias["id"]][:4]
    # Approximate spelling is always a suggestion requiring a user's choice.
    return ("suggested" if candidates else "missing"), candidates, None


def _number(value: str) -> int | None:
    if not value.strip():
        return None
    if not re.fullmatch(r"\d{1,5}", value.strip()):
        raise ValueError("Expected a non-negative integer")
    return int(value)


def preview_rows(raw_rows: list[tuple[int, list[str], bool]]) -> dict:
    result = []
    total = golden = 0
    for row_number, values, yellow in raw_rows:
        values = (values + [""] * 8)[:8]
        name, quantity, card_type, cost, stats, text, _illustration, edition = [v.strip() for v in values]
        if not any(values):
            continue
        key = name_key(name)
        if key in {"carte fr", "carte", "nom", "name", "nombre de carte dans le deck", "nombre de cartes dans le deck", "total"}:
            continue
        try:
            if any(v.startswith("=") for v in values):
                raise ValueError("Card formulas are not supported; export values instead")
            if not name:
                raise ValueError("Missing card name")
            if edition and name_key(edition) not in {"oui", "non", "true", "false", "1", "0", "doree", "golden", "normal"}:
                raise ValueError("Invalid Dorée value; use Oui or Non")
            is_golden = name_key(edition) in {"oui", "true", "1", "doree", "golden"} if edition else yellow
            if yellow and not is_golden:
                raise ValueError("Yellow background conflicts with Dorée=Non")
            attack = health = None
            if stats:
                pair = re.fullmatch(r"(\d{1,5})\s*[/\-–]\s*(\d{1,5})", stats)
                if not pair:
                    raise ValueError("Expected ATQ/PV statistics, e.g. 3/2 or 3-2")
                attack, health = map(int, pair.groups())
            source = DeckImportSourceRow(
                rowNumber=row_number, name=name, quantity=_number(quantity) if quantity else 1,
                isGolden=is_golden, cardType=card_type or None, cost=_number(cost),
                attack=attack, health=health, text=text or None,
                illustrationUrl=_illustration or None,
            )
            total += source.quantity
            golden += source.quantity if is_golden else 0
            if total > 500:
                raise ValueError("A deck import is limited to 500 copies")
            match_status, candidates, selected = candidates_for(name)
            result.append(dict(rowNumber=row_number, source=source, rawName=name, rawValues=values, status=match_status,
                               candidates=candidates, selectedCardId=selected, error=None))
        except (ValueError, ValidationError) as exc:
            result.append(dict(rowNumber=row_number, source=None, rawName=name, rawValues=values, status="invalid",
                               candidates=[], selectedCardId=None, error=str(exc)))
    if not result:
        raise ValueError("No card rows found")
    return dict(rows=result, totalCount=total, goldenCount=golden)


def definition_from_import(source: DeckImportSourceRow, card_id: str) -> DeckDefinitionInput:
    types = {"sort": "SPELL", "serviteur": "MINION", "arme": "WEAPON", "heros": "HERO", "lieu": "LOCATION"}
    return DeckDefinitionInput(
        sourceCardId=card_id, name=source.name, cost=source.cost, attack=source.attack,
        health=source.health, text=source.text,
        illustrationUrl=source.illustrationUrl,
        cardType=types.get(name_key(source.cardType or "")),
        normalCount=0 if source.isGolden else source.quantity,
        goldenCount=source.quantity if source.isGolden else 0,
    )
