"""Region name normalization.

Only exact (normalized) name comparison is used. No fuzzy matching, so a typo
produces "no match" instead of a wrong match.
"""
from .schemas import Region

# 2026-07-01 전남광주통합특별시 출범: 주소에 기존 명칭과 통합 명칭이 섞여 들어올 수 있다.
_INTEGRATED = "전남광주통합특별시"
_SIDO_ALIASES = {
    "전남": "전라남도", "전라남도": "전라남도",
    "광주": "광주광역시", "광주광역시": "광주광역시", "광주시": "광주광역시",
    "전남광주": _INTEGRATED, "전남광주통합특별시": _INTEGRATED, "전남광주특별시": _INTEGRATED,
    "전북": "전북특별자치도", "전라북도": "전북특별자치도", "전북특별자치도": "전북특별자치도",
    "경남": "경상남도", "경상남도": "경상남도", "경북": "경상북도", "경상북도": "경상북도",
    "충남": "충청남도", "충청남도": "충청남도", "충북": "충청북도", "충청북도": "충청북도",
    "강원": "강원특별자치도", "강원도": "강원특별자치도", "강원특별자치도": "강원특별자치도",
    "제주": "제주특별자치도", "제주도": "제주특별자치도", "제주특별자치도": "제주특별자치도",
    "서울": "서울특별시", "서울특별시": "서울특별시", "서울시": "서울특별시",
    "부산": "부산광역시", "부산광역시": "부산광역시", "대구": "대구광역시", "대구광역시": "대구광역시",
    "인천": "인천광역시", "인천광역시": "인천광역시", "대전": "대전광역시", "대전광역시": "대전광역시",
    "울산": "울산광역시", "울산광역시": "울산광역시", "세종": "세종특별자치시", "세종특별자치시": "세종특별자치시",
    "경기": "경기도", "경기도": "경기도",
}
# Names that the integrated city may cover. Matching across these is reported, not hidden.
_INTEGRATED_MEMBERS = {"전라남도", "광주광역시"}


def norm_sido(value: str | None) -> str | None:
    if not value:
        return None
    key = value.replace(" ", "")
    return _SIDO_ALIASES.get(key, key)


def norm_sigungu(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace(" ", "")


def sido_compatible(a: str | None, b: str | None) -> bool:
    """True when either side is unknown, equal, or one is the integrated-city name."""
    a, b = norm_sido(a), norm_sido(b)
    if a is None or b is None or a == b:
        return True
    pair = {a, b}
    return _INTEGRATED in pair and bool(pair & _INTEGRATED_MEMBERS)


def region_matches(target: Region, actual: Region) -> bool:
    """``actual`` lies within ``target``.

    target with only sido matches any sigungu in that sido; a target sigungu
    requires the same sigungu.
    """
    if not sido_compatible(target.sido, actual.sido):
        return False
    if target.sigungu:
        return norm_sigungu(target.sigungu) == norm_sigungu(actual.sigungu)
    # sido-only target: actual must state a compatible sido
    return actual.sido is not None


def region_label(region: Region) -> str:
    return " ".join(x for x in (region.sido, region.sigungu) if x)


def text_mentions_region(text: str | None, region: Region) -> bool:
    """Used only to find gov24 *candidates*; never as an eligibility basis."""
    if not text or not region.sigungu:
        return False
    name = norm_sigungu(region.sigungu)
    compact = text.replace(" ", "")
    if name in compact:
        return True
    # "무안군" -> also accept "무안" when the stem has >= 2 chars (e.g. 무안사랑상품권)
    stem = name[:-1] if name[-1:] in {"시", "군", "구"} and len(name) >= 3 else None
    return bool(stem) and stem in compact
