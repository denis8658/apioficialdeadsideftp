import struct
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


MAP_IMAGE = Path("app/static/maps/mirny/deadside_map.png")
LOD_TILE_COUNTS = {1: 110, 2: 30, 3: 9, 4: 4}


def test_consolidated_map_matches_logical_map_bounds():
    content = MAP_IMAGE.read_bytes()
    assert content[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", content[16:24])
    assert (width, height) == (1280, 1408)


def test_every_lod_tile_is_a_512_pixel_png():
    for lod, expected_count in LOD_TILE_COUNTS.items():
        tiles = sorted((MAP_IMAGE.parent / f"lod_{lod}").glob("map_*_*.png"))
        assert len(tiles) == expected_count
        for tile in tiles:
            content = tile.read_bytes()
            assert content[:8] == b"\x89PNG\r\n\x1a\n"
            assert struct.unpack(">II", content[16:24]) == (512, 512)


def test_map_image_endpoint_and_lod_tile():
    client = TestClient(app)
    image = client.get("/api/v1/maps/mirny/image")
    tile = client.get("/api/v1/maps/mirny/tiles/lod_1/map_1_1.png")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "public, max-age=86400"
    assert tile.status_code == 200
    assert tile.headers["content-type"] == "image/png"
    assert tile.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/api/v1/maps/mirny/tiles/lod_1/map_10_0.png").status_code == 404
