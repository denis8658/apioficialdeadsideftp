from app.db.models import FileCategory
from app.parsers.character import CharacterParser
from app.parsers.deathlog import DeathlogParser
from app.parsers.permanent_character import PermanentCharacterParser
from app.parsers.storage import StorageParser
from app.parsers.vehicle import VehicleParser


def parser_for(category: FileCategory):
    if category == FileCategory.character:
        return CharacterParser()
    if category == FileCategory.character_nowipe:
        return PermanentCharacterParser()
    if category == FileCategory.vehicle:
        return VehicleParser()
    if category == FileCategory.storage:
        return StorageParser()
    if category == FileCategory.deathlog:
        return DeathlogParser()
    return None
