import argparse
import asyncio
import json
from pathlib import Path

from app.db.session import SessionLocal
from app.services.ingestion import ZipImporter


async def _import(archive: Path, server_slug: str, server_name: str) -> dict:
    async with SessionLocal() as session:
        return await ZipImporter(session).import_archive(archive, server_slug, server_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deadside Data API maintenance commands")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("import-zip", "Import a local hosting backup"), ("sync-once", "Run one local ZIP synchronization")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("archive", type=Path)
        command.add_argument("--server-slug", required=name == "sync-once", default="deadside-local")
        command.add_argument("--server-name", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.archive.is_file():
        raise SystemExit(f"archive does not exist: {args.archive}")
    name = args.server_name or args.server_slug
    result = asyncio.run(_import(args.archive, args.server_slug, name))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
