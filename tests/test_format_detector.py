import pytest

from app.parsers.format_detector import FileFormat, decode_text, detect_format


def test_detects_json_inside_sav():
    assert detect_format(b'\xef\xbb\xbf{"BaseCharacter": {}}', "42.sav") == FileFormat.JSON


def test_invalid_incomplete_json_is_not_json():
    assert detect_format(b'{"BaseCharacter": {', "42.sav") != FileFormat.JSON


def test_strict_utf8_does_not_silently_replace_bytes():
    with pytest.raises(UnicodeDecodeError):
        decode_text(b"\xff")


def test_detects_binary_by_content():
    assert detect_format(b"\x00\xff\x01\x80", "bases") == FileFormat.BINARY
