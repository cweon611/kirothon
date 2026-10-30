"""Static seeds (sigungu, origins, interests) and codes resolved by sync_tourism."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import json
import os
from pathlib import Path
import re

from ..database import DB_PATH

KST = timezone(timedelta(hours=9))
SEEDS = Path(__file__).with_name("seeds")
CONTENT_TYPES = {"12": "관광지", "14": "문화시설", "15": "축제공연행사", "25": "여행코스",
                 "28": "레포츠", "32": "숙박", "38": "쇼핑", "39": "음식점"}
SPOT_TYPES = ("12", "14", "28")


@dataclass(frozen=True)
class Sigungu:
    code: str
    name: str
    sido: str

    @property
    def area_cd(self) -> str:
        return self.code[:2]

    @property
    def label(self) -> str:
        return f"광주 {self.name}" if self.sido == "광주광역시" else self.name


@dataclass(frozen=True)
class Origin:
    key: str
    name: str
    sigungu_code: str
    lat: float
    lng: float

    @property
    def in_gwangju(self) -> bool:
        return self.sigungu_code.startswith("29")


@dataclass(frozen=True)
class Interest:
    key: str
    label: str
    level: int
    keywords: tuple[str, ...]
    content_types: tuple[str, ...]


def _seed(name: str) -> dict:
    return json.loads((SEEDS / name).read_text(encoding="utf-8"))


@lru_cache
def sigungu_map() -> dict[str, Sigungu]:
    return {row["code"]: Sigungu(row["code"], row["name"], row["sido"])
            for row in _seed("regions.json")["sigungu"]}


@lru_cache
def origins() -> dict[str, Origin]:
    return {row["key"]: Origin(row["key"], row["name"], row["sigungu_code"], row["lat"], row["lng"])
            for row in _seed("origins.json")["origins"]}


@lru_cache
def interests() -> dict[str, Interest]:
    return {row["key"]: Interest(row["key"], row["label"], row["level"], tuple(row["keywords"]),
                                 tuple(row["content_types"]))
            for row in _seed("interest_map.json")["interests"]}


def place_overrides() -> dict[str, str]:
    return dict(_seed("place_overrides.json").get("overrides") or {})


def demo_places() -> list[dict]:
    return list(_seed("demo_places.json").get("places") or [])


def today_kst() -> tuple[date, bool]:
    """Service 'today' in KST. TEAM_TODAY=YYYY-MM-DD pins it for demos."""
    fixed = os.environ.get("TEAM_TODAY", "").strip()
    if fixed:
        return date.fromisoformat(fixed), True
    return datetime.now(KST).date(), False


# Codes resolved from KorService2 ldongCode2 / lclsSystmCode2 live next to the DB,
# not in the source tree, because each server resolves them from its own sync run.
def codes_path() -> Path:
    return DB_PATH.parent / "tourism-codes.json"


def load_codes() -> dict:
    try:
        data = json.loads(codes_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def ldong_for(code: str, codes: dict | None = None) -> tuple[str, str]:
    """KorService2 (lDongRegnCd, lDongSignguCd) for an internal sigungu code."""
    resolved = ((codes if codes is not None else load_codes()).get("ldong") or {}).get(code)
    if resolved and len(resolved) == 2:
        return str(resolved[0]), str(resolved[1])
    return code[:2], code[2:]


def internal_code(regn: str | None, signgu: str | None, codes: dict | None = None) -> str | None:
    """Map KorService2 legal-dong codes back to the internal 5-digit key."""
    if not regn or not signgu:
        return None
    regn, signgu = str(regn).strip(), str(signgu).strip()
    for code, pair in ((codes if codes is not None else load_codes()).get("ldong") or {}).items():
        if pair and str(pair[0]) == regn and str(pair[1]) == signgu:
            return code
    candidate = signgu if len(signgu) == 5 else regn + signgu
    return candidate if candidate in sigungu_map() else None


def name_key(name: str | None) -> str:
    """Normalize a place name for matching: drop spaces, brackets and punctuation."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", name or "")
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).lower()


def place_matches_interest(content_type_id: str | None, lcls1: str | None, lcls2: str | None,
                           interest: Interest, codes: dict) -> bool:
    resolved = ((codes.get("lcls") or {}).get(interest.key) or {})
    level_codes = set(resolved.get("lcls1" if interest.level == 1 else "lcls2") or [])
    if level_codes and (lcls1 or lcls2):
        return (lcls1 if interest.level == 1 else lcls2) in level_codes
    return content_type_id in interest.content_types


def interest_basis(codes: dict) -> str:
    return "lclsSystm" if codes.get("lcls") else "content_type"
