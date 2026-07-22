import csv
import io
import json
from enum import StrEnum


class FileFormat(StrEnum):
    JSON = "json"
    CSV = "csv"
    CONFIG = "config"
    LOG = "log"
    TEXT = "text"
    BINARY = "binary"
    EMPTY = "empty"


def decode_text(content: bytes) -> str:
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]
    return content.decode("utf-8", errors="strict")


def detect_format(content: bytes, source_path: str = "") -> FileFormat:
    if not content or not content.strip(b"\x00\t\r\n "):
        return FileFormat.EMPTY
    try:
        text = decode_text(content)
    except UnicodeDecodeError:
        return FileFormat.BINARY
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            return FileFormat.JSON
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and (lines[0].lstrip().startswith("[") or any("=" in line and not line.lstrip().startswith(("#", ";")) for line in lines[:20])):
        return FileFormat.CONFIG
    if source_path.lower().endswith(".csv") or (lines and _looks_like_csv(text)):
        return FileFormat.CSV
    if source_path.lower().endswith(".log") or any(token in text for token in ("LogTemp:", "LogNet:", "Error:", "Warning:")):
        return FileFormat.LOG
    if all(char.isprintable() or char in "\r\n\t" for char in text):
        return FileFormat.TEXT
    return FileFormat.BINARY


def _looks_like_csv(text: str) -> bool:
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        rows = list(csv.reader(io.StringIO(text), dialect))[:3]
        return bool(rows and len(rows[0]) > 1)
    except csv.Error:
        return False
