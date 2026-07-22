#!/usr/bin/env python3
"""Monta o mapa Mirny do Deadside a partir de uma grade explícita de 3×3 tiles."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

LOGGER = logging.getLogger("montar_mapa_deadside")
TILE_PATTERN = re.compile(r"^map_(\d+)_(\d+)\.png$", re.IGNORECASE)
EXPECTED_COORDINATES = {(x, y) for y in range(3) for x in range(3)}
LEAFLET_RATIO = 1280 / 1408


class MapAssemblyError(RuntimeError):
    """Erro estrutural que impede uma montagem segura."""


@dataclass(frozen=True)
class TileInfo:
    x: int
    y: int
    path: Path
    width: int
    height: int


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monta nove tiles map_x_y.png sem redimensionar ou inverter eixos."
    )
    parser.add_argument("--input-dir", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("deadside_map_full.png"))
    parser.add_argument("--crop-mode", choices=("none", "auto", "manual"), default="none")
    parser.add_argument("--crop-left", type=int)
    parser.add_argument("--crop-top", type=int)
    parser.add_argument("--crop-right", type=int)
    parser.add_argument("--crop-bottom", type=int)
    parser.add_argument("--crop-to-leaflet-ratio", action="store_true")
    parser.add_argument("--black-threshold", type=int, default=15)
    parser.add_argument("--convert-rgb", action="store_true")
    parser.add_argument("--quality", type=int, default=95)
    parser.add_argument("--debug-grid", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.black_threshold <= 255:
        parser.error("--black-threshold deve estar entre 0 e 255")
    if not 1 <= args.quality <= 100:
        parser.error("--quality deve estar entre 1 e 100")
    return args


def discover_tiles(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        raise MapAssemblyError(f"diretório de entrada não existe: {input_dir}")
    if not input_dir.is_dir():
        raise MapAssemblyError(f"entrada não é um diretório: {input_dir}")

    candidates = list(input_dir.glob("map_*.png"))
    malformed = sorted(path.name for path in candidates if TILE_PATTERN.fullmatch(path.name) is None)
    if malformed:
        raise MapAssemblyError("nomes de tile inválidos: " + ", ".join(malformed))

    by_coordinate: dict[tuple[int, int], Path] = {}
    for path in candidates:
        match = TILE_PATTERN.fullmatch(path.name)
        assert match is not None
        coordinate = (int(match.group(1)), int(match.group(2)))
        if coordinate not in EXPECTED_COORDINATES:
            raise MapAssemblyError(f"coordenada fora da grade 3×3: {path.name}")
        if coordinate in by_coordinate:
            raise MapAssemblyError(
                f"tiles duplicados para {coordinate}: "
                f"{by_coordinate[coordinate].name}, {path.name}"
            )
        by_coordinate[coordinate] = path

    missing = [f"map_{x}_{y}.png" for y in range(3) for x in range(3) if (x, y) not in by_coordinate]
    if missing:
        raise MapAssemblyError("tiles ausentes: " + ", ".join(missing))
    return [by_coordinate[x, y] for y in range(3) for x in range(3)]


def validate_tiles(paths: Sequence[Path]) -> list[TileInfo]:
    infos: list[TileInfo] = []
    expected_size: tuple[int, int] | None = None
    seen: set[tuple[int, int]] = set()
    for path in paths:
        match = TILE_PATTERN.fullmatch(path.name)
        if match is None:
            raise MapAssemblyError(f"nome inválido: {path.name}")
        coordinate = (int(match.group(1)), int(match.group(2)))
        if coordinate in seen:
            raise MapAssemblyError(f"tile duplicado para a coordenada {coordinate}")
        seen.add(coordinate)
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                size = image.size
        except (UnidentifiedImageError, OSError) as exc:
            raise MapAssemblyError(f"arquivo não é uma imagem PNG válida: {path}") from exc
        if expected_size is None:
            expected_size = size
        elif size != expected_size:
            raise MapAssemblyError(
                f"tile com tamanho diferente: {path.name} tem {size[0]}×{size[1]}, "
                f"esperado {expected_size[0]}×{expected_size[1]}"
            )
        infos.append(TileInfo(*coordinate, path, *size))
    if seen != EXPECTED_COORDINATES:
        missing = EXPECTED_COORDINATES - seen
        raise MapAssemblyError(f"grade incompleta; coordenadas ausentes: {sorted(missing)}")
    return sorted(infos, key=lambda tile: (tile.y, tile.x))


def load_tiles(tiles: Sequence[TileInfo]) -> dict[tuple[int, int], Image.Image]:
    loaded: dict[tuple[int, int], Image.Image] = {}
    try:
        for tile in tiles:
            with Image.open(tile.path) as image:
                loaded[tile.x, tile.y] = image.convert("RGBA").copy()
    except (UnidentifiedImageError, OSError) as exc:
        for image in loaded.values():
            image.close()
        raise MapAssemblyError(f"falha ao carregar tile: {tile.path}") from exc
    return loaded


def compose_tiles(tiles: Sequence[TileInfo], images: dict[tuple[int, int], Image.Image]) -> Image.Image:
    if not tiles:
        raise MapAssemblyError("nenhum tile para montar")
    tile_width, tile_height = tiles[0].width, tiles[0].height
    canvas = Image.new("RGBA", (tile_width * 3, tile_height * 3), (0, 0, 0, 0))
    for tile in sorted(tiles, key=lambda item: (item.y, item.x)):
        canvas_x = tile.x * tile_width
        canvas_y = tile.y * tile_height
        canvas.paste(images[tile.x, tile.y], (canvas_x, canvas_y))
    return canvas


def detect_outer_crop(image: Image.Image, black_threshold: int = 15) -> tuple[int, int, int, int]:
    """Retorna o menor retângulo externo com pixels opacos e acima da tolerância."""
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size

    def significant(x: int, y: int) -> bool:
        red, green, blue, alpha = pixels[x, y]
        return alpha > 0 and max(red, green, blue) > black_threshold

    top = next((y for y in range(height) if any(significant(x, y) for x in range(width))), height)
    if top == height:
        return (0, 0, width, height)
    bottom = next(y + 1 for y in range(height - 1, top - 1, -1) if any(significant(x, y) for x in range(width)))
    left = next(x for x in range(width) if any(significant(x, y) for y in range(top, bottom)))
    right = next(x + 1 for x in range(width - 1, left - 1, -1) if any(significant(x, y) for y in range(top, bottom)))
    return (left, top, right, bottom)


def validate_manual_crop(
    image: Image.Image,
    left: int | None,
    top: int | None,
    right: int | None,
    bottom: int | None,
) -> tuple[int, int, int, int]:
    values = (left, top, right, bottom)
    if any(value is None for value in values):
        raise MapAssemblyError("crop manual exige left, top, right e bottom")
    box = (int(left), int(top), int(right), int(bottom))  # type: ignore[arg-type]
    width, height = image.size
    if not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
        raise MapAssemblyError(f"retângulo de recorte manual inválido {box} para imagem {width}×{height}")
    return box


def crop_to_ratio(image: Image.Image, ratio: float = LEAFLET_RATIO) -> tuple[Image.Image, tuple[int, int, int, int]]:
    if ratio <= 0:
        raise MapAssemblyError("a proporção deve ser positiva")
    width, height = image.size
    current = width / height
    if current > ratio:
        new_width = max(1, round(height * ratio))
        left = (width - new_width) // 2
        box = (left, 0, left + new_width, height)
    else:
        new_height = max(1, round(width / ratio))
        top = (height - new_height) // 2
        box = (0, top, width, top + new_height)
    return image.crop(box), box


def draw_debug_grid(image: Image.Image, tile_width: int, tile_height: int) -> Image.Image:
    debug = image.convert("RGBA").copy()
    draw = ImageDraw.Draw(debug)
    line_width = max(2, min(tile_width, tile_height) // 128)
    for x in (tile_width, tile_width * 2):
        draw.line((x, 0, x, debug.height), fill=(255, 40, 40, 255), width=line_width)
    for y in (tile_height, tile_height * 2):
        draw.line((0, y, debug.width, y), fill=(255, 40, 40, 255), width=line_width)
    font = ImageFont.load_default()
    for y in range(3):
        for x in range(3):
            label = f"map_{x}_{y}"
            center_x = x * tile_width + tile_width // 2
            center_y = y * tile_height + tile_height // 2
            box = draw.textbbox((0, 0), label, font=font, stroke_width=1)
            text_width, text_height = box[2] - box[0], box[3] - box[1]
            position = (center_x - text_width // 2, center_y - text_height // 2)
            draw.text(position, label, font=font, fill="white", stroke_width=2, stroke_fill="black")
    return debug


def save_image(image: Image.Image, output: Path, convert_rgb: bool = False, quality: int = 95) -> None:
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MapAssemblyError(f"não foi possível criar o diretório de saída {output.parent}: {exc}") from exc
    result = image.convert("RGB") if convert_rgb else image
    suffix = output.suffix.lower()
    if suffix in {".jpg", ".jpeg"} and result.mode != "RGB":
        raise MapAssemblyError("JPEG não suporta transparência; use --convert-rgb")
    save_options = {"quality": quality} if suffix in {".jpg", ".jpeg", ".webp"} else {}
    try:
        result.save(output, **save_options)
    except (OSError, ValueError) as exc:
        raise MapAssemblyError(f"não foi possível salvar {output}: {exc}") from exc
    finally:
        if result is not image:
            result.close()


def _report(original_size: tuple[int, int], final_size: tuple[int, int], output: Path) -> None:
    width, height = final_size
    ratio = width / height
    difference = abs(ratio - LEAFLET_RATIO) / LEAFLET_RATIO * 100
    print("Relatório da montagem")
    print(f"  Canvas 3×3: {original_size[0]} × {original_size[1]}")
    print(f"  Imagem final: {width} × {height}")
    print(f"  Proporção final: {ratio:.8f}")
    print(f"  Proporção Leaflet esperada: {LEAFLET_RATIO:.8f} (1280:1408)")
    print(f"  Diferença percentual: {difference:.4f}%")
    print(f"  Arquivo: {output.resolve()}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    images: dict[tuple[int, int], Image.Image] = {}
    canvas: Image.Image | None = None
    final: Image.Image | None = None
    try:
        paths = discover_tiles(args.input_dir)
        tiles = validate_tiles(paths)
        images = load_tiles(tiles)
        canvas = compose_tiles(tiles, images)
        LOGGER.info("9 tiles validados e montados por coordenadas x/y")

        if args.debug_grid:
            debug = draw_debug_grid(canvas, tiles[0].width, tiles[0].height)
            debug_path = args.output.parent / "deadside_map_debug.png"
            try:
                save_image(debug, debug_path, args.convert_rgb, args.quality)
            finally:
                debug.close()
            LOGGER.info("diagnóstico salvo em %s", debug_path)

        final = canvas.copy()
        if args.crop_mode == "auto":
            box = detect_outer_crop(final, args.black_threshold)
            LOGGER.info("recorte automático: %s", box)
            cropped = final.crop(box)
            final.close()
            final = cropped
        elif args.crop_mode == "manual":
            box = validate_manual_crop(final, args.crop_left, args.crop_top, args.crop_right, args.crop_bottom)
            LOGGER.info("recorte manual: %s", box)
            cropped = final.crop(box)
            final.close()
            final = cropped

        if args.crop_to_leaflet_ratio:
            cropped, ratio_box = crop_to_ratio(final)
            print(f"Retângulo de recorte para proporção Leaflet: {ratio_box}")
            final.close()
            final = cropped

        save_image(final, args.output, args.convert_rgb, args.quality)
        _report(canvas.size, final.size, args.output)
        return 0
    except MapAssemblyError as exc:
        LOGGER.error("%s", exc)
        return 2
    finally:
        if final is not None:
            final.close()
        if canvas is not None:
            canvas.close()
        for image in images.values():
            image.close()


if __name__ == "__main__":
    sys.exit(main())
