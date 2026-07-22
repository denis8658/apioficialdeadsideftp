import struct
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


MAP_IMAGE = Path("app/static/maps/mirny/deadside_map.png")


def test_consolidated_map_matches_logical_map_bounds():
    content = MAP_IMAGE.read_bytes()
    assert content[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", content[16:24])
    assert (width, height) == (1280, 1408)


def test_map_image_endpoint_and_static_tile():
    client = TestClient(app)
    image = client.get("/api/v1/maps/mirny/image")
    tile = client.get("/static/maps/mirny/tiles/map_1_1.png")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "public, max-age=86400"
    assert tile.status_code == 200
    assert tile.headers["content-type"] == "image/png"
