from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.cors import normalize_origins, parse_csv, validate_origin_regex


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = "Deadside Data API"
    app_version: str = "0.1.0"
    environment: str = Field(default="development", validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT"))
    debug: bool = False
    api_host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("API_HOST", "HOST"))
    api_port: int = Field(default=8000, ge=1, le=65535, validation_alias=AliasChoices("PORT", "API_PORT"))
    cors_enabled: bool = True
    cors_allowed_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
        validation_alias=AliasChoices("CORS_ALLOWED_ORIGINS", "ALLOWED_ORIGINS"),
    )
    cors_allowed_origin_regex: str = ""
    cors_allow_credentials: bool = False
    cors_allowed_methods: str = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    cors_allowed_headers: str = "Authorization,Content-Type,Accept,Origin,X-Requested-With,X-Request-ID,X-CSRF-Token,X-Client-Version,X-Server-ID"
    cors_expose_headers: str = "X-Request-ID,Content-Disposition,X-Total-Count"
    cors_max_age_seconds: int = Field(default=600, ge=0, le=86400)
    allowed_hosts: str = Field(default="localhost,127.0.0.1,test,testserver", validation_alias=AliasChoices("TRUSTED_HOSTS", "ALLOWED_HOSTS"))
    force_https: bool = False
    rate_limit_enabled: bool = True
    rate_limit_requests: int = Field(default=30, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    database_url: str = "postgresql+asyncpg://deadside:deadside@localhost:5432/deadside"
    sql_echo: bool = False
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=20, ge=0)
    database_pool_timeout_seconds: int = Field(default=30, ge=1)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60)
    database_command_timeout_seconds: int = Field(default=30, ge=1)
    ftp_poll_interval_seconds: int = Field(default=5, ge=1)
    ftp_protocol: str = "ftp"
    ftp_host: str = ""
    ftp_port: int = Field(default=21, ge=1, le=65535)
    ftp_username: str = ""
    ftp_password: SecretStr = SecretStr("")
    ftp_use_tls: bool = False
    ftp_passive_mode: bool = True
    ftp_connection_timeout_seconds: float = Field(default=20, gt=0)
    ftp_operation_timeout_seconds: float = Field(default=30, gt=0)
    ftp_max_retries: int = Field(default=5, ge=1)
    ftp_retry_base_seconds: float = Field(default=2, gt=0)
    ftp_discovery_max_depth: int = Field(default=8, ge=1)
    ftp_root_path: str = "/"
    ftp_max_concurrent_downloads: int = Field(default=2, ge=1)
    ftp_max_files_per_cycle: int = Field(default=500, ge=1)
    ftp_max_file_size_mb: int = Field(default=100, ge=1)
    ftp_stability_delay_seconds: float = Field(default=0.75, ge=0.5, le=1.0)
    kills_leaderboard_min_kills_for_kd: int = Field(default=3, ge=1)
    websocket_enabled: bool = True
    websocket_heartbeat_interval_seconds: float = Field(default=25, gt=0)
    websocket_heartbeat_timeout_seconds: float = Field(default=60, gt=0)
    websocket_send_timeout_seconds: float = Field(default=5, gt=0)
    websocket_max_connections_per_server: int = Field(default=500, ge=1)
    websocket_max_connections_per_user: int = Field(default=10, ge=1)
    websocket_max_message_bytes: int = Field(default=65536, ge=1024)
    websocket_event_retention_hours: int = Field(default=24, ge=1)
    websocket_persist_events: bool = True
    websocket_jwt_secret: SecretStr = SecretStr("")
    websocket_allowed_origins: str = "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173"
    websocket_allow_missing_origin: bool = False
    map_min_x: float = 0.0
    map_max_x: float = 1280.0
    map_min_y: float = -1408.0
    map_max_y: float = 0.0
    map_origin_x: float = 640.0
    map_origin_y: float = -896.0
    unreal_units_per_map_unit: float = 781.25
    map_grid_size: float = 128.0
    map_grid_start_column_offset: int = 3
    position_tolerance_unreal: float = 1.0

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value):
        """Use the async PostgreSQL driver with provider-issued URLs."""
        if isinstance(value, str):
            if value.startswith("postgresql://"):
                return value.replace("postgresql://", "postgresql+asyncpg://", 1)
            if value.startswith("postgres://"):
                return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value

    @model_validator(mode="after")
    def validate_browser_security(self):
        origins = self.cors_origins
        websocket_origins = self.websocket_origins
        methods = self.allowed_methods
        headers = {header.casefold() for header in self.allowed_headers}
        production = self.environment.casefold() == "production"
        origin_regex = self.origin_regex
        if self.cors_allow_credentials and "*" in origins:
            raise ValueError("CORS credentials cannot be combined with wildcard origins")
        if "OPTIONS" not in methods:
            raise ValueError("CORS_ALLOWED_METHODS must include OPTIONS")
        if "authorization" not in headers:
            raise ValueError("CORS_ALLOWED_HEADERS must include Authorization")
        if production:
            if not origins or "*" in origins:
                raise ValueError("production requires explicit CORS origins")
            if not websocket_origins or "*" in websocket_origins:
                raise ValueError("production requires explicit WebSocket origins")
            local_hosts = {"localhost", "127.0.0.1", "::1"}
            if any(urlsplit(origin).hostname in local_hosts for origin in origins):
                raise ValueError("production CORS origins cannot use localhost")
            if any(urlsplit(origin).hostname in local_hosts for origin in websocket_origins):
                raise ValueError("production WebSocket origins cannot use localhost")
            if origin_regex in {"*", ".*", "^.*$"}:
                raise ValueError("production forbids a permissive CORS origin regex")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return normalize_origins(self.cors_allowed_origins)

    @property
    def origin_regex(self) -> str | None:
        return validate_origin_regex(self.cors_allowed_origin_regex)

    @property
    def allowed_methods(self) -> list[str]:
        return parse_csv(self.cors_allowed_methods, uppercase=True)

    @property
    def allowed_headers(self) -> list[str]:
        return parse_csv(self.cors_allowed_headers)

    @property
    def exposed_headers(self) -> list[str]:
        return parse_csv(self.cors_expose_headers)

    @property
    def websocket_origins(self) -> list[str]:
        return normalize_origins(self.websocket_allowed_origins)

    @property
    def trusted_hosts(self) -> list[str]:
        return parse_csv(self.allowed_hosts)


@lru_cache
def get_settings() -> Settings:
    return Settings()
