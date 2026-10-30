import re
import unicodedata


def generate_slug(text: str) -> str:
    """
    Genera un slug URL-friendly a partir de un texto.
    """
    # Normalizar caracteres unicode (tildes, ñ, etc)
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    
    # Convertir a minúsculas
    text = text.lower()
    
    # Reemplazar caracteres no alfanuméricos con guiones
    text = re.sub(r'[^a-z0-9]+', '-', text)
    
    # Eliminar guiones al inicio y final
    text = text.strip('-')
    
    return text
