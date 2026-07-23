import pytest

from app.services.map_service import MapService


@pytest.mark.parametrize(("world_x", "world_y", "map_x", "map_y"), [(-22752.6, -300043.0, 610.876672, -576.05504), (-300245, -76290.4, 255.6864, -289.651712)])
def test_deadside_to_map_and_inverse(world_x, world_y, map_x, map_y):
    service = MapService()
    point = service.deadside_to_map(world_x, world_y)
    assert point.x == pytest.approx(map_x)
    assert point.y == pytest.approx(map_y)
    inverse = service.map_to_deadside(point.x, point.y)
    assert inverse.x == pytest.approx(world_x)
    assert inverse.y == pytest.approx(world_y)


def test_map_grid_and_limits():
    service = MapService()
    point = service.deadside_to_map(-22752.6, -300043.0)
    assert service.map_to_grid(point.x, point.y) == "H5"
    assert service.is_inside_map(0, -1408)
    assert service.is_inside_map(1280, 0)
    assert not service.is_inside_map(-0.01, -100)
    assert service.map_to_grid(-0.01, -100) is None


def test_distance_uses_unreal_centimeters():
    assert MapService.distance_meters(0, 0, 300, 400) == pytest.approx(5.0)
