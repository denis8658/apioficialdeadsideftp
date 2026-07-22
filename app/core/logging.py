import logging
import json
import sys
import re
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_text(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = redact_sensitive_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def redact_sensitive_text(value: str) -> str:
    value = re.sub(r"([?&](?:token|access_token)=)[^&\s]+", r"\1***", value, flags=re.IGNORECASE)
    value = re.sub(r"(Authorization:\s*Bearer\s+)[^\s]+", r"\1***", value, flags=re.IGNORECASE)
    value = re.sub(r"((?:Set-)?Cookie:\s*)[^\r\n]+", r"\1***", value, flags=re.IGNORECASE)
    value = re.sub(r"((?:password|secret)\s*[=:]\s*)[^\s,;]+", r"\1***", value, flags=re.IGNORECASE)
    return value


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # Query-string WebSocket tokens must never be emitted by an access logger.
    logging.getLogger("uvicorn.access").disabled = True
