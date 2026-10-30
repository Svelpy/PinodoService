from fastapi import FastAPI
from slowapi import Limiter
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["300/minute"],
    storage_uri="memory://",
    strategy="fixed-window",
    headers_enabled=False,
    key_prefix="api",
)

def register_rate_limiter(app: FastAPI) -> None:
    """Registra el rate limiter global."""
    
    app.state.limiter = limiter
    app.add_middleware(SlowAPIASGIMiddleware)
