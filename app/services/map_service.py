from dataclasses import dataclass
from math import floor, hypot

from app.core.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class MapPoint:
    x: float
    y: float


class MapService:
    """Mirny calibration anchored by an in-game world/grid observation."""

    calibration_name = "mirny-live-h5-v2"
    calibration_version = 2
    calibration_status = "field_calibrated"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def deadside_to_map(self, world_x: float, world_y: float) -> MapPoint:
        scale = self.settings.unreal_units_per_map_unit
        return MapPoint(self.settings.map_origin_x + world_x / scale, self.settings.map_origin_y + world_y / scale)

    def map_to_deadside(self, map_x: float, map_y: float) -> MapPoint:
        scale = self.settings.unreal_units_per_map_unit
        return MapPoint((map_x - self.settings.map_origin_x) * scale, (map_y - self.settings.map_origin_y) * scale)

    def is_inside_map(self, map_x: float, map_y: float) -> bool:
        s = self.settings
        return s.map_min_x <= map_x <= s.map_max_x and s.map_min_y <= map_y <= s.map_max_y

    def map_to_grid(self, map_x: float, map_y: float) -> str | None:
        if not self.is_inside_map(map_x, map_y):
            return None
        size = self.settings.map_grid_size
        column_index = floor((map_x - self.settings.map_min_x) / size)
        row_index = floor(abs(map_y - self.settings.map_max_y) / size)
        column = chr(ord("A") + column_index + self.settings.map_grid_start_column_offset)
        return f"{column}{row_index + 1}"

    @staticmethod
    def distance_meters(x1: float, y1: float, x2: float, y2: float) -> float:
        return hypot(x2 - x1, y2 - y1) / 100.0

    def position(self, world_x: float, world_y: float, world_z: float | None = None) -> dict:
        point = self.deadside_to_map(world_x, world_y)
        return {"world_position": {"x": world_x, "y": world_y, "z": world_z}, "map_position": {"x": point.x, "y": point.y, "inside_map": self.is_inside_map(point.x, point.y), "grid": self.map_to_grid(point.x, point.y)}}
