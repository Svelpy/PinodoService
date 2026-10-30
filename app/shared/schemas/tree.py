from typing import Generic, List, TypeVar

from pydantic import BaseModel, Field

T = TypeVar('T')


class TreeNodeResponse(BaseModel, Generic[T]):
    """Schema genérico de nodo en estructura de árbol. Uso: TreeNodeResponse[CategoryResponse]"""

    data: T  # Objeto o datos del nodo
    children: List['TreeNodeResponse[T]'] = Field(default_factory=list)  # Hijos o sub-nodos del árbol


class TreeResponse(BaseModel, Generic[T]):
    """Schema genérico de respuesta en árbol. Uso: TreeResponse[CategoryResponse]"""

    total: int  # Total de nodos en el árbol
    data: List[TreeNodeResponse[T]]  # Lista de nodos raíz
