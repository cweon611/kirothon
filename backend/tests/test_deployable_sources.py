"""backend/app reaches the server only as .py files (scripts/deploy.ps1, ops/deploy.py)."""
from pathlib import Path

from app.team import regions

APP = Path(__file__).resolve().parents[1] / "app"


def test_backend_app_has_only_python_files():
    stray = sorted(p.relative_to(APP).as_posix() for p in APP.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".py")
    assert stray == [], f"not deployed to the server (only .py ships): {stray}"


def test_seed_modules_load():
    sigungu = regions.sigungu_map()
    assert len(sigungu) == 27
    assert sum(1 for s in sigungu.values() if s.sido == "광주광역시") == 5
    assert regions.origins() and regions.interests()
    assert isinstance(regions.place_overrides(), dict)
    assert isinstance(regions.demo_places(), list)


def test_seed_copies_are_independent():
    regions.place_overrides()["29110:test"] = "1"
    assert "29110:test" not in regions.place_overrides()
