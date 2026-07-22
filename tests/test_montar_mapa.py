from pathlib import Path

import pytest
from PIL import Image

from montar_mapa_deadside import (
    LEAFLET_RATIO,
    MapAssemblyError,
    compose_tiles,
    crop_to_ratio,
    detect_outer_crop,
    discover_tiles,
    load_tiles,
    validate_manual_crop,
    validate_tiles,
)


COLORS = {
    (0, 0): (255, 0, 0, 255), (1, 0): (0, 255, 0, 255), (2, 0): (0, 0, 255, 255),
    (0, 1): (255, 255, 0, 255), (1, 1): (255, 0, 255, 255), (2, 1): (0, 255, 255, 255),
    (0, 2): (120, 20, 20, 255), (1, 2): (20, 120, 20, 255), (2, 2): (20, 20, 120, 255),
}


def make_tiles(directory: Path, size: tuple[int, int] = (8, 6)) -> None:
    for (x, y), color in COLORS.items():
        Image.new("RGBA", size, color).save(directory / f"map_{x}_{y}.png")


def compose_fixture(directory: Path):
    infos = validate_tiles(discover_tiles(directory))
    images = load_tiles(infos)
    return infos, images, compose_tiles(infos, images)


def test_tiles_are_ordered_numerically_by_y_then_x(tmp_path):
    make_tiles(tmp_path)
    tiles = validate_tiles(discover_tiles(tmp_path))
    assert [(tile.x, tile.y) for tile in tiles] == [
        (0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (0, 2), (1, 2), (2, 2)
    ]


def test_each_tile_is_pasted_at_its_numeric_position_without_axis_swap(tmp_path):
    make_tiles(tmp_path)
    _, images, canvas = compose_fixture(tmp_path)
    try:
        for (x, y), color in COLORS.items():
            assert canvas.getpixel((x * 8 + 3, y * 6 + 2)) == color
    finally:
        canvas.close()
        for image in images.values():
            image.close()


def test_missing_tile_is_reported_by_name(tmp_path):
    make_tiles(tmp_path)
    (tmp_path / "map_1_2.png").unlink()
    with pytest.raises(MapAssemblyError, match="map_1_2.png"):
        discover_tiles(tmp_path)


def test_different_tile_size_is_rejected(tmp_path):
    make_tiles(tmp_path)
    Image.new("RGBA", (9, 6), "white").save(tmp_path / "map_2_1.png")
    with pytest.raises(MapAssemblyError, match="tamanho diferente"):
        validate_tiles(discover_tiles(tmp_path))


def test_manual_crop_validation():
    image = Image.new("RGBA", (30, 20))
    try:
        assert validate_manual_crop(image, 1, 2, 29, 19) == (1, 2, 29, 19)
        with pytest.raises(MapAssemblyError, match="inválido"):
            validate_manual_crop(image, 10, 2, 9, 19)
        with pytest.raises(MapAssemblyError, match="exige"):
            validate_manual_crop(image, None, 0, 20, 20)
    finally:
        image.close()


def test_automatic_crop_removes_only_external_black_border():
    image = Image.new("RGBA", (12, 10), (0, 0, 0, 255))
    for y in range(2, 8):
        for x in range(3, 10):
            image.putpixel((x, y), (80, 90, 100, 255))
    image.putpixel((6, 5), (0, 0, 0, 255))
    try:
        assert detect_outer_crop(image, black_threshold=15) == (3, 2, 10, 8)
    finally:
        image.close()


def test_crop_to_leaflet_ratio_preserves_center_without_resizing():
    image = Image.new("RGBA", (300, 300), "white")
    try:
        cropped, box = crop_to_ratio(image)
        assert cropped.height == 300
        assert cropped.width < image.width
        assert cropped.width / cropped.height == pytest.approx(LEAFLET_RATIO, abs=0.002)
        assert abs(box[0] - (image.width - box[2])) <= 1
        cropped.close()
    finally:
        image.close()


def test_x_and_y_are_not_inverted(tmp_path):
    make_tiles(tmp_path)
    _, images, canvas = compose_fixture(tmp_path)
    try:
        assert canvas.getpixel((1 * 8 + 4, 2 * 6 + 3)) == COLORS[1, 2]
        assert canvas.getpixel((2 * 8 + 4, 1 * 6 + 3)) == COLORS[2, 1]
    finally:
        canvas.close()
        for image in images.values():
            image.close()


def test_map_2_0_is_in_the_top_right(tmp_path):
    make_tiles(tmp_path)
    _, images, canvas = compose_fixture(tmp_path)
    try:
        assert canvas.getpixel((2 * 8 + 4, 3)) == COLORS[2, 0]
    finally:
        canvas.close()
        for image in images.values():
            image.close()


def test_map_0_2_is_in_the_bottom_left(tmp_path):
    make_tiles(tmp_path)
    _, images, canvas = compose_fixture(tmp_path)
    try:
        assert canvas.getpixel((4, 2 * 6 + 3)) == COLORS[0, 2]
        assert canvas.size == (24, 18)
    finally:
        canvas.close()
        for image in images.values():
            image.close()
