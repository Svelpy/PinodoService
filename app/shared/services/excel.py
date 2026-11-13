"""
Construcción de reportes Excel (.xlsx) con openpyxl.

Un reporte tiene hojas con un encabezado (título, período, generado por y
notas) y tablas:

- tabla_simple: tabla pequeña sin filtros, para un resumen.
- tabla_filtrable: tabla plana con filtro en cada columna y, encima del
  encabezado, una fila «Total filtrado» con SUBTOTAL, que solo suma las filas
  visibles: al filtrar, los totales cambian solos.

No conoce ningún dominio: recibe textos, columnas y filas ya calculados.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO
from typing import Literal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

DINERO = "#,##0.00"
ENTERO = "#,##0"
DECIMAL = "0.00"
PORCENTAJE = "0.0%"
FECHA = "dd/mm/yyyy"
HORA = "hh:mm"

_AZUL = "1F3A5F"
_HEADER_FILL = PatternFill("solid", fgColor=_AZUL)
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_TOTAL_FILL = PatternFill("solid", fgColor="DCE6F1")
_NEGRITA = Font(bold=True)
_NOTA = Font(italic=True, color="666666")

Celda = str | int | float | Decimal | date | datetime | time | None


@dataclass(frozen=True)
class Columna:
    """
    Columna de una tabla filtrable. total decide su celda en «Total filtrado»:
    "suma" suma lo visible; ("ratio", a, b) divide el total de la columna a
    por el de la b (un promedio o un porcentaje no se suman); None la deja vacía.
    """

    titulo: str
    formato: str | None = None
    ancho: int = 12
    total: Literal["suma"] | tuple[Literal["ratio"], str, str] | None = None


def nuevo_libro() -> Workbook:
    libro = Workbook()
    # Excel recalcula las fórmulas (SUBTOTAL) al abrir el archivo.
    libro.calculation.fullCalcOnLoad = True
    return libro


def a_bytes(libro: Workbook) -> bytes:
    buffer = BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


def _valor(valor: Celda) -> Celda:
    # Excel guarda números de punto flotante; Decimal no es un tipo de celda.
    return float(valor) if isinstance(valor, Decimal) else valor


def encabezado(hoja: Worksheet, titulo: str, lineas: list[str], notas: list[str]) -> int:
    """Título y líneas de contexto; devuelve la primera fila libre tras una en blanco."""
    hoja["A1"] = titulo
    hoja["A1"].font = Font(bold=True, size=14, color=_AZUL)
    fila = 2
    for texto in lineas:
        hoja.cell(row=fila, column=1, value=texto)
        fila += 1
    for texto in notas:
        hoja.cell(row=fila, column=1, value=texto).font = _NOTA
        fila += 1
    return fila + 1


def titulo_seccion(hoja: Worksheet, fila: int, texto: str) -> int:
    hoja.cell(row=fila, column=1, value=texto).font = _NEGRITA
    return fila + 1


def nota(hoja: Worksheet, fila: int, texto: str) -> int:
    hoja.cell(row=fila, column=1, value=texto).font = _NOTA
    return fila + 1


def tabla_simple(
    hoja: Worksheet,
    fila: int,
    titulos: list[str],
    filas: list[list[Celda]],
    formatos: list[list[str | None]],
    *,
    negrita: set[int] = frozenset(),
    anchos: list[int] | None = None,
) -> int:
    """
    Tabla sin filtros. formatos lleva el formato de cada celda, fila por fila,
    para admitir tablas de indicadores con un formato distinto en cada fila.
    negrita son los índices de las filas destacadas. Devuelve la fila siguiente
    a la tabla más una en blanco.
    """
    for columna, titulo in enumerate(titulos, start=1):
        celda = hoja.cell(row=fila, column=columna, value=titulo)
        celda.fill, celda.font = _HEADER_FILL, _HEADER_FONT
    for indice, valores in enumerate(filas):
        for columna, valor in enumerate(valores, start=1):
            celda = hoja.cell(row=fila + 1 + indice, column=columna, value=_valor(valor))
            formato = formatos[indice][columna - 1]
            if formato:
                celda.number_format = formato
            if indice in negrita:
                celda.font = _NEGRITA
    for columna, ancho in enumerate(anchos or [], start=1):
        letra = get_column_letter(columna)
        hoja.column_dimensions[letra].width = max(hoja.column_dimensions[letra].width or 0, ancho)
    return fila + len(filas) + 2


def tabla_filtrable(hoja: Worksheet, fila: int, columnas: list[Columna], filas: list[list[Celda]]) -> None:
    """
    Fila «Total filtrado», encabezado con filtros y datos. Los paneles quedan
    congelados bajo el encabezado.
    """
    fila_total, fila_titulos = fila, fila + 1
    primera, ultima = fila_titulos + 1, max(fila_titulos + len(filas), fila_titulos + 1)
    letras = {c.titulo: get_column_letter(i) for i, c in enumerate(columnas, start=1)}

    hoja.cell(row=fila_total, column=1, value="Total filtrado")
    for indice, columna in enumerate(columnas, start=1):
        letra = get_column_letter(indice)
        hoja.column_dimensions[letra].width = columna.ancho
        titulo = hoja.cell(row=fila_titulos, column=indice, value=columna.titulo)
        titulo.fill, titulo.font = _HEADER_FILL, _HEADER_FONT
        titulo.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        total = hoja.cell(row=fila_total, column=indice)
        if columna.total == "suma":
            total.value = f"=SUBTOTAL(109,{letra}{primera}:{letra}{ultima})"
        elif isinstance(columna.total, tuple):
            _, numerador, denominador = columna.total
            total.value = (
                f'=IFERROR({letras[numerador]}{fila_total}/{letras[denominador]}{fila_total},"")'
            )
        if columna.formato and indice > 1:
            total.number_format = columna.formato
        total.fill, total.font = _TOTAL_FILL, _NEGRITA
    hoja.row_dimensions[fila_titulos].height = 30

    for indice, valores in enumerate(filas):
        for numero, valor in enumerate(valores, start=1):
            celda = hoja.cell(row=primera + indice, column=numero, value=_valor(valor))
            if columnas[numero - 1].formato:
                celda.number_format = columnas[numero - 1].formato

    hoja.auto_filter.ref = f"A{fila_titulos}:{get_column_letter(len(columnas))}{ultima}"
    hoja.freeze_panes = hoja.cell(row=primera, column=1)
