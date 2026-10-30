from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings


def register_cors(app: FastAPI,settings: Settings) -> None:
    """
    Registra el middleware de CORS en la app.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS_LIST,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With", "X-CSRF-Token"],
    )
