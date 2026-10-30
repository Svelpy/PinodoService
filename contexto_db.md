# Contexto del proyecto: tienda de ropa online (tipo Zara)

Este documento describe el proyecto para que una IA pueda ayudar a desarrollarlo sin volver a preguntar decisiones ya tomadas. Todo lo que está aquí está **decidido**; si una tarea parece contradecirlo, pregunta antes de cambiarlo.

## 1. Resumen

- Tienda de ropa online con catálogo inspirado en la estructura de zara.com.
- **Una sola región, un solo idioma, una sola moneda, una sola tienda física** (sin sucursales ni almacenes).
- Alcance actual: **catálogo y administración**. No hay carrito, pedidos, pagos, envíos, devoluciones, direcciones, favoritos, newsletter, tarjetas regalo, contenido editorial ni segunda mano.

## 2. Stack

- **Backend:** Python, FastAPI, SQLModel (sobre SQLAlchemy).
- **Base de datos:** PostgreSQL 13 o superior (probado en 16).
- **Diagrama:** ChartDB (se importa el script SQL del esquema).
- Arquitectura en capas con patrón **Repository** (ver sección 6).

## 3. Convenciones generales de la base de datos

### 3.1 BaseModel (auditoría y borrado lógico)

Todas las tablas, **excepto `config`**, heredan estos campos:

| Campo | Tipo | Nulo | Notas |
|---|---|---|---|
| `id` | uuid | No | PK. **Lo genera la aplicación** (`uuid4`); la BD no tiene valor por defecto |
| `created_at` | timestamptz | No | Fecha de creación |
| `created_by` | uuid | Sí | Usuario que creó. **Sin FK** hacia `usuarios` |
| `updated_at` | timestamptz | No | **Debe asignarlo la aplicación en cada actualización** (no se actualiza solo) |
| `updated_by` | uuid | Sí | Sin FK |
| `is_deleted` | boolean | No | Borrado lógico. Indexado |
| `deleted_at` | timestamptz | Sí | |
| `deleted_by` | uuid | Sí | Sin FK |

### 3.2 Reglas obligatorias

1. **No existe borrado físico.** Nunca usar `DELETE`. Borrar = `is_deleted = true` + `deleted_at` + `deleted_by`. Por eso **no hay `ON DELETE CASCADE`**.
2. **Toda consulta filtra `is_deleted = false`**, salvo que se pida explícitamente ver lo borrado.
3. **Unicidad solo entre registros activos:** los valores únicos se implementan como índices únicos parciales `WHERE is_deleted = false`, para que un registro borrado no bloquee crear otro con el mismo valor (por ejemplo, el mismo email).
4. **`is_visible` NO es borrado lógico.** Sirve para ocultar algo que todavía no está terminado de crear. Lo tienen: `secciones`, `categorias`, `productos`, `producto_colores`, `skus`.
5. **Regla de visibilidad en la tienda:** un elemento se muestra solo si él y todos sus ancestros son visibles y no están borrados.
   - SKU visible ⇔ sección, producto, producto_color y SKU visibles y no borrados.
   - Producto visible en una categoría ⇔ la categoría (y sus categorías padre), el enlace `categoria_productos` y el producto están activos/visibles.

## 4. Tablas

Además de los campos propios listados, cada tabla (excepto `config`) tiene los campos de BaseModel.

### Catálogo y navegación

**secciones**: grandes divisiones del catálogo (Mujer, Hombre, Niños…).
- `nombre` varchar(100), `slug` varchar(120) único activo, `is_visible`.

**categorias**: árbol del menú (Colección › Cazadoras › Bombers).
- `seccion_id` → secciones, `parent_id` → categorias (nulo = raíz), `nombre`, `slug` único activo dentro de su sección (`seccion_id`, `slug`), `is_visible`.

**categoria_productos**: enlace N:M entre categorías y productos. Un producto puede estar en varias categorías.
- `categoria_id` → categorias, `producto_id` → productos.
- Tiene `id` propio (no PK compuesta) para poder quitar un producto de una categoría con borrado lógico y volver a agregarlo.
- Único activo: (`categoria_id`, `producto_id`).

### Producto

Jerarquía: **producto → producto_colores → skus**. El SKU (color × talla) es la unidad que se vende y tiene su propio precio y stock.

**productos**: el modelo de prenda.
- `seccion_id` → secciones, `nombre` varchar(200), `descripcion`, `cuidados`, `composicion` (text), `is_visible`.

**colores**: catálogo general de colores.
- `nombre` varchar(60), `slug` varchar(80) único activo (interno: evita duplicados como "Azul marino" / "azúl  marino"; no se usa en URLs), `codigo_hex` varchar(7).

**producto_colores**: cada color disponible de un producto.
- `producto_id` → productos, `color_id` → colores (obligatorio), `is_visible`.
- Único activo: (`producto_id`, `color_id`).

**imagenes**: fotos de un color de producto.
- `producto_color_id` → producto_colores, `url` varchar(500), `tipo` varchar(20) (por defecto `MODELO`; valores: MODELO, PRENDA, DETALLE).

**tallas**: lista única de tallas (sin sistemas de talla).
- `etiqueta` varchar(30) único activo (S, M, 38, "6-7 años").

**skus**: combinación color × talla.
- `producto_color_id` → producto_colores, `talla_id` → tallas, `codigo_barras` varchar(50) único activo, `is_visible`.
- Único activo: (`producto_color_id`, `talla_id`).
- `precio` jsonb obligatorio: `{"normal": number, "rebajado": number | null, "rebaja_hasta": fecha | null}`.
- `stock` jsonb obligatorio: `{"cantidad": int, "minimo": int, "actualizado": fecha | null}`.
- **El precio puede variar por color y por talla.** En los listados se muestra "desde X" (menor precio entre los SKUs visibles del color).

### Usuarios y configuración

**usuarios**: personal que administra el catálogo (y eventualmente clientes, distinguidos por `rol`).
- `email` varchar(255) único activo, `password_hash` varchar(255), `nombre` varchar(100), `apellidos` varchar(150) nulo, `telefono` varchar(30) nulo, `rol` varchar(20).

**config**: datos de la tienda online. **Una sola fila con `id = 1`** (CHECK). No hereda BaseModel.
- `id` integer, `nombre_tienda`, `descripcion`, `logo_url`, `favicon_url`, `email_contacto`, `telefono`, `whatsapp`, `direccion`, `map_url` (enlace al mapa de la tienda física), `ciudad`, `horario` jsonb (`{"lunes": "09:00-20:00", …}`), `redes_sociales` jsonb (`{"instagram": "url", …}`), `en_mantenimiento` boolean, `updated_at`, `updated_by`.

### Relaciones

- secciones 1→N categorias; categorias 1→N categorias (parent_id)
- secciones 1→N productos
- categorias N↔M productos (vía categoria_productos)
- productos 1→N producto_colores N→1 colores
- producto_colores 1→N imagenes
- producto_colores 1→N skus N→1 tallas

## 5. Decisiones descartadas (no proponerlas de nuevo salvo que se pida)

- Mercados/países, idiomas y precios por mercado.
- Sucursales, almacenes, tabla de ubicaciones.
- Etiquetas (NEW, etc.), colecciones/colaboraciones/licencias, sistemas de talla.
- Tabla de precios separada y tabla de stock separada (ambos van embebidos en `skus`).
- Borrado en cascada y borrado físico.
- Campos `referencia` y `fecha_alta` en productos; `activo` y `fecha_registro` en usuarios.
- Carrito, pedidos, pagos, envíos, devoluciones, direcciones, favoritos, newsletter, tarjetas/tickets regalo, contenido editorial, Pre-Owned.

## 6. Arquitectura del backend (patrón Repository)

### Capas

| Capa | Responsabilidad | No debe contener |
|---|---|---|
| **routers/** | Endpoints HTTP, validación con schemas, códigos de respuesta, dependencias (sesión, usuario autenticado) | Consultas a BD ni reglas de negocio |
| **services/** | Reglas de negocio, coordinación de varios repositorios, **commit/rollback de la transacción** | SQL ni detalles HTTP |
| **repositories/** | Acceso a datos: obtener, listar, filtrar, paginar, crear, actualizar, borrado lógico | Reglas de negocio, excepciones HTTP, commit |
| **models/** | Tablas SQLModel (heredan BaseModel) | Lógica |
| **schemas/** | Modelos de entrada/salida de la API, separados de las tablas | — |
| **database.py** | Motor de conexión y dependencia `get_session` | — |

Flujo: router → service → repository → base de datos.

### Sesión de base de datos

- El repositorio **nunca crea su propia sesión**: la recibe desde afuera, **preferentemente en el constructor**.
- La sesión se crea **una vez por petición** con la dependencia de FastAPI (`Depends(get_session)`) y se **comparte** entre el servicio y todos los repositorios de esa petición.
- El **servicio hace el commit** una sola vez al final de la operación; si algo falla, rollback. Así una operación compuesta (por ejemplo, crear producto + colores + SKUs) es atómica.

### Repositorio base genérico

Implementa una vez las operaciones comunes a todas las tablas con BaseModel:

- **get(id)**: solo registros con `is_deleted = false`.
- **list(...)**: con paginación, filtrando borrados.
- **create(obj, user_id)**: asigna `created_by` (y `updated_by`).
- **update(obj, datos, user_id)**: asigna `updated_at = ahora (UTC)` y `updated_by`.
- **soft_delete(obj, user_id)**: `is_deleted = true`, `deleted_at = ahora (UTC)`, `deleted_by`. Nunca `DELETE`.

Cada tabla tiene su repositorio que hereda del base y agrega sus consultas propias, por ejemplo:

- ProductoRepository: productos visibles de una categoría; búsqueda por nombre.
- CategoriaRepository: buscar por slug; árbol de una sección.
- SkuRepository: SKUs de un color; SKUs con stock por debajo del mínimo.
- UsuarioRepository: buscar por email.
- ConfigRepository: leer y actualizar la fila `id = 1` (sin borrado lógico).

## 7. Instrucciones para la IA

- Responde en **español**.
- Respeta todas las decisiones de este documento; si una tarea parece requerir cambiarlas, pregunta antes.
- Al escribir consultas o repositorios, aplica siempre el filtro `is_deleted = false` y la regla de visibilidad cuando sea para la tienda pública.
- No generes código de borrado físico ni `ON DELETE CASCADE`.
- Los UUID se generan en la aplicación, no en la base de datos.
- El esquema SQL de referencia es `tienda_ropa_schema_v4.sql`.
