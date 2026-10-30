from pydantic import BaseModel
from typing import TypeVar, Generic, List

T = TypeVar('T')
class PaginatedResponse(BaseModel, Generic[T]):
    """Schema genérico de respuesta paginada. Uso: PaginatedResponse[UserResponse]"""
    total: int          # Total de registros encontrados
    page: int           # Página actual (empieza en 1)
    per_page: int       # Registros por página
    total_pages: int    # Total de páginas
    data: List[T]       # Lista de objetos tipados