from collections.abc import Iterable


def missing_vehicle_uids(previous: Iterable[str], current: Iterable[str]) -> set[str]:
    return set(previous) - set(current)


def disappearance_confirmed(missing_observations: int, required_observations: int = 2) -> bool:
    return missing_observations >= required_observations
