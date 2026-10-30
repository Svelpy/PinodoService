from functools import lru_cache
from typing import Literal, Self
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr, model_validator
Environment = Literal["development","staging","production","test"]

class Settings(BaseSettings):
    """Configuración de la aplicación usando variables de entorno"""
    
    # =================================
    # Application
    # =================================
    APP_NAME: str = "Proyect_Service_API"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = """Lorep Ipsum"""
    ENVIRONMENT: Environment = "development"
    # =================================
    # Regional
    # =================================
    # Bolivia (UTC-4) no aplica horario de verano: un desplazamiento fijo es exacto.
    TIMEZONE_OFFSET_HOURS: int = Field(default=-4, ge=-12, le=14)
    # =================================
    # PostgreSQL
    # =================================
    DATABASE_URL: str | None = None
    TEST_DATABASE_URL: str | None = None
    # =================================
    # Seeds
    # =================================
    SEED_ADMIN_EMAIL_1: str | None = None
    SEED_ADMIN_NAME_1: str | None = None
    SEED_ADMIN_LASTNAME_1: str | None = None
    SEED_ADMIN_PASSWORD_1: SecretStr | None = None

    SEED_ADMIN_EMAIL_2: str | None = None
    SEED_ADMIN_NAME_2: str | None = None
    SEED_ADMIN_LASTNAME_2: str | None = None
    SEED_ADMIN_PASSWORD_2: SecretStr | None = None

    SEED_ADMIN_EMAIL_3: str | None = None
    SEED_ADMIN_NAME_3: str | None = None
    SEED_ADMIN_LASTNAME_3: str | None = None
    SEED_ADMIN_PASSWORD_3: SecretStr | None = None
    # =================================
    # JWT
    # =================================
    SECRET_KEY: str
    CSRF_SECRET_KEY: str
    ALGORITHM: Literal["HS256"] = "HS256"
    # =================================
    # Cloudinary
    # =================================
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None
    CLOUDINARY_FOLDER_NAME: str | None = None
    # =================================
    # CORS
    # =================================
    DEV_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://localhost:5175"
    PROD_ORIGINS: str | None = None

    @property
    def CORS_ORIGINS_LIST(self) -> list[str]:
        if self.ENVIRONMENT in {"development", "test"}:
            origins = self.DEV_ORIGINS
            var_name = "DEV_ORIGINS"
        else:
            origins = self.PROD_ORIGINS
            var_name = "PROD_ORIGINS"

        if not origins:
            raise ValueError(f"Debe configurarse {var_name} para el entorno '{self.ENVIRONMENT}'")

        # El navegador envía el Origin sin "/" final; se normaliza para que coincida.
        return [
            origin.strip().rstrip("/")
            for origin in origins.split(",")
            if origin.strip().rstrip("/")
        ]

    ACCESS_TOKEN_EXPIRE_MINUTES_DEVELOPMENT: int = Field(default=600, gt=0)
    ACCESS_TOKEN_EXPIRE_MINUTES_STAGING: int = Field(default=15, gt=0)
    ACCESS_TOKEN_EXPIRE_MINUTES_PRODUCTION: int = Field(default=15, gt=0)
    @property
    def ACCESS_TOKEN_EXPIRE_MINUTES(self) -> int:
        durations = {
            "development": self.ACCESS_TOKEN_EXPIRE_MINUTES_DEVELOPMENT,
            "staging": self.ACCESS_TOKEN_EXPIRE_MINUTES_STAGING,
            "production": self.ACCESS_TOKEN_EXPIRE_MINUTES_PRODUCTION,
            "test": self.ACCESS_TOKEN_EXPIRE_MINUTES_DEVELOPMENT,
        }
        return durations[self.ENVIRONMENT]

    REFRESH_TOKEN_EXPIRE_DAYS_DEVELOPMENT: int = Field(default=7, gt=0)
    REFRESH_TOKEN_EXPIRE_DAYS_STAGING: int = Field(default=7, gt=0)
    REFRESH_TOKEN_EXPIRE_DAYS_PRODUCTION: int = Field(default=7, gt=0)
    @property
    def REFRESH_TOKEN_EXPIRE_DAYS(self) -> int:
        durations = {
            "development": self.REFRESH_TOKEN_EXPIRE_DAYS_DEVELOPMENT,
            "staging": self.REFRESH_TOKEN_EXPIRE_DAYS_STAGING,
            "production": self.REFRESH_TOKEN_EXPIRE_DAYS_PRODUCTION,
            "test": self.REFRESH_TOKEN_EXPIRE_DAYS_DEVELOPMENT,
        }
        return durations[self.ENVIRONMENT]

    REFRESH_TOKEN_COOKIE_NAME: str = "refresh_token"
    @property
    def REFRESH_TOKEN_COOKIE_SECURE(self) -> bool:
        return self.ENVIRONMENT in {"staging", "production"}
    
    @property
    def DEBUG(self) -> bool:
        return self.ENVIRONMENT == "development"

    @model_validator(mode="after")
    def validate_security_settings(self) -> Self:
        if len(self.SECRET_KEY.encode("utf-8")) < 32:
            raise ValueError("SECRET_KEY debe contener al menos 32 bytes.")

        if len(self.CSRF_SECRET_KEY.encode("utf-8")) < 32:
            raise ValueError("CSRF_SECRET_KEY debe contener al menos 32 bytes.")

        if self.SECRET_KEY == self.CSRF_SECRET_KEY:
            raise ValueError("SECRET_KEY y CSRF_SECRET_KEY deben ser diferentes.")

        return self
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )
    
@lru_cache
def get_settings() -> Settings:
    return Settings()

