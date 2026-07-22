import hashlib

from app.db.models import FileCategory
from app.services.ingestion import categorize_path, sha256_bytes
from app.services.vehicle_service import disappearance_confirmed, missing_vehicle_uids


def test_sha256():
    assert sha256_bytes(b"deadside") == hashlib.sha256(b"deadside").hexdigest()


def test_paths_are_discovered_by_pattern_not_fixed_prefix():
    assert categorize_path("vendor/root/characters1-9/world_0/42.sav") == FileCategory.character
    assert categorize_path("other/Saved/new_vehicles7/world_0/new_vehicles.sav") == FileCategory.vehicle
    assert categorize_path("x/other1-9/world_0/bases2026.07.20") == FileCategory.base


def test_vehicle_disappearance_requires_confirmation_window():
    assert missing_vehicle_uids(["a", "b"], ["b"]) == {"a"}
    assert not disappearance_confirmed(1, required_observations=2)
    assert disappearance_confirmed(2, required_observations=2)
