from fastapi import APIRouter

from app.core.config import get_settings
from app.parsers.character import CharacterParser
from app.parsers.deathlog import DeathlogParser
from app.parsers.permanent_character import PermanentCharacterParser
from app.parsers.storage import StorageParser
from app.parsers.vehicle import VehicleParser

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("/parsers")
async def parsers():
    available = (CharacterParser(), PermanentCharacterParser(), VehicleParser(), StorageParser(), DeathlogParser())
    return {"parsers": [{"name": parser.name, "version": parser.version, "status": "complete"} for parser in available], "base_parser": {"status": "metadata_only"}}


@router.get("/cors")
async def cors_configuration():
    settings = get_settings()
    return {
        "enabled": settings.cors_enabled,
        "environment": settings.environment,
        "allowed_origins": settings.cors_origins,
        "allow_credentials": settings.cors_allow_credentials,
        "allowed_methods": settings.allowed_methods,
        "allowed_headers": settings.allowed_headers,
        "expose_headers": settings.exposed_headers,
        "max_age_seconds": settings.cors_max_age_seconds,
        "websocket_origin_validation": True,
        "websocket_allow_missing_origin": settings.websocket_allow_missing_origin,
    }
