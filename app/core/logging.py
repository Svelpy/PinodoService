import logging

from app.core.config import Settings


def setup_logging(settings: Settings) -> None:
    """Configura el sistema de logging global."""

    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    """
    Devuelve un logger identificado por nombre.

    Uso:
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)