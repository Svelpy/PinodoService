# AGENTS.md

Este archivo contiene las reglas que deben aplicarse siempre al trabajar en este backend.

Para detalles de arquitectura, responsabilidades por archivo, ejemplos y decisiones técnicas ampliadas, consultar `ARCHITECTURE.md` solo cuando la tarea lo requiera.

---

## 1. Stack

- Python
- FastAPI
- PostgreSQL
- SQLModel para modelos persistentes
- SQLAlchemy async / `AsyncSession`
- asyncpg
- Pydantic para schemas
- Alembic para migraciones

Regla fundamental:

```text
models.py  → SQLModel
schemas.py → Pydantic
```

Models y schemas son capas independientes.

Nunca hacer herencia entre un modelo persistente y un schema.

La duplicación razonable de campos entre ambas capas es aceptada para mantener desacopladas la persistencia y la API.

---

## 2. Estructura de `app/`

`app/` contiene únicamente estas cinco carpetas principales:

```text
app/
├── core/
├── domains/
├── integrations/
├── middlewares/
└── shared/
```

Además:

```text
app/
├── __init__.py
├── api.py
└── main.py
```

No crear nuevas carpetas raíz dentro de `app/` sin una necesidad arquitectónica explícita.

---

## 3. Responsabilidades principales

### `core/`
Infraestructura fundamental.

Contiene:

```text
base_model.py
config.py
database.py
logging.py
security.py
system_router.py
```

No colocar lógica funcional de dominios dentro de `core/`.

### `domains/`
Funcionalidad de negocio.

Estructura estándar:

```text
<domain>/
├── __init__.py
├── models.py
├── schemas.py
├── repositories.py
├── services.py
└── routes.py
```

`auth/` incluye además `dependencies.py`.

`error_logs/` es obligatorio y contiene como mínimo su modelo y el repository
que encapsula su persistencia.

### `integrations/`
Adaptadores de proveedores externos.

Ejemplos:

```text
cloudinary.py
resend.py
redis.py
```

Flujo:

```text
service
↓
integration
↓
provider
```

### `middlewares/`
Comportamiento HTTP global.

```text
cors.py
exception_handlers.py
limiter.py
```

### `shared/`
Código realmente reutilizable entre dominios.

No utilizarlo como carpeta miscelánea.

---

## 4. Models

Los modelos persistentes utilizan SQLModel con `table=True`.

Todos los modelos normales heredan del `BaseModel` definido en `core/base_model.py`.

`BaseModel` contiene:

```text
id
created_at
created_by
updated_at
updated_by
is_deleted
deleted_at
deleted_by
```

`BaseModel` no utiliza `table=True`.

Los models definen exclusivamente:

- columnas;
- primary keys;
- foreign keys;
- relaciones;
- índices;
- `unique`;
- `nullable`;
- restricciones persistentes.

No contienen lógica HTTP ni reglas funcionales de negocio.

Las relaciones necesarias para los schemas con embebidos se declaran con
`Relationship()` y carga lazy deshabilitada (`lazy="raise"`), porque la sesión
es async y una carga implícita fallaría.

---

## 5. Soft delete y auditoría

La eliminación estándar es lógica.

`delete` debe actualizar:

```text
is_deleted = True
deleted_at
deleted_by
updated_at
updated_by
```

`get` y `list` excluyen por defecto registros con `is_deleted=True`.

La consulta de eliminados debe ser explícita.

Los services son responsables de asignar:

```text
created_by
updated_by
deleted_by
updated_at
deleted_at
```

cuando corresponda.

---

## 6. Schemas

Los schemas utilizan exclusivamente `pydantic.BaseModel`.

Schemas estándar por dominio:

```text
Create
Update
Response
ResponseAudit
```

`ResponseAudit` hereda de `Response`.

Se permiten schemas especiales cuando exista una operación funcional distinta, por ejemplo:

```text
UserUpdateMe
ChangePassword
ResetPassword
```

Los schemas de respuesta que se construyan desde objetos ORM deben utilizar `ConfigDict(from_attributes=True)`.

En todos los schemas `Update` utilizados por operaciones `PATCH`, cada campo
modificable debe poder omitirse y se declara siempre con este patrón:

```python
field: T | None = Field(default=None)
```

El tipo `T | None` permite representar el valor temporal usado cuando el campo
se omite, y `default=None` hace que el campo no sea obligatorio en la petición.
Esto no significa que todos los campos persistentes sean nullable.

Cada `field_validator` debe aplicar explícitamente una de estas políticas:

- si la columna es nullable, aceptar `None` y devolver `None` para permitir que
  el cliente elimine su valor;
- si la columna no es nullable, rechazar un `None` enviado explícitamente;
- si existe un valor concreto, delegar su validación de tipo, formato y
  normalización en la función `object → T` correspondiente de
  `shared/services/validators.py`.

Los services deben procesar estas actualizaciones con:

```python
model_dump(exclude_unset=True)
```

No utilizar `exclude_none=True` para este flujo, porque eliminaría también los
`None` enviados explícitamente y haría imposible limpiar campos nullable. Los
valores explícitos `0` y `False` tampoco deben descartarse.

### Schemas de lectura con embebidos

Los dominios cuyo model tiene al menos una foreign key definen además:

```text
ListItem
Detail
```

Los dominios que solo tienen primary key no los definen.

Se crean siempre, incluso cuando no añaden campos respecto al schema del que
heredan; en ese caso quedan como una clase vacía. Cadena de herencia:

```text
Response → ListItem → Detail
```

`ResponseAudit` hereda de `Response`, no forma parte de esta cadena y nunca se
embebe.

#### Dueño y referencia

Cada foreign key se clasifica como:

```text
dueño       → el registro vive dentro de una colección del otro
referencia  → el registro apunta a un objeto compartido que existe por sí mismo
```

Prueba práctica: si en Python se escribiría `padre.hijos.append(obj)`, la
foreign key es de dueño; si se escribiría `Obj(campo=VALOR_COMPARTIDO)`, como
quien elige un miembro de un `Enum`, es de referencia.

Ejemplo: en una línea de pedido, `pedido_id` es de dueño y `producto_id` es de
referencia.

En las tablas de enlace N:M, ambas foreign keys son de referencia.

#### Contenido de cada schema

```text
Response  → columnas propias + foreign keys como id. No embebe nada.

ListItem  → Response
            + cada foreign key de referencia embebida como el Response del
              registro referenciado.
            Nunca contiene colecciones.

Detail    → ListItem
            + los hijos propios (registros cuya foreign key de dueño apunta a
              este registro), embebidos como el Detail del hijo.
            + las asociaciones N:M acotadas, embebidas como el Response del
              extremo lejano, sin exponer la tabla de enlace.
```

#### Profundidad

El embebido solo se mueve en dos direcciones:

```text
hacia abajo   (dueño → hijos)  → continúa mientras existan hijos
hacia un lado (referencia)     → un solo paso; el Response es plano y termina
hacia arriba  (hijo → dueño)   → nunca
```

Por tanto:

- `ListItem` tiene exactamente un nivel.
- `Detail` desciende hasta las hojas del árbol de dueños, con un paso lateral
  por cada referencia.
- Ningún embebido vuelve al objeto de partida ni produce ciclos.

#### Restricciones

- La foreign key de dueño nunca se embebe; permanece como id.
- Una referencia embebida utiliza siempre `Response`; nunca `ListItem`,
  `Detail` ni `ResponseAudit`.
- Las colecciones sin límite natural no se embeben; se exponen como un listado
  filtrado y paginado.
- Si la foreign key de dueño apunta al mismo model (jerarquía
  autorreferenciada), el `Detail` embebe los hijos como `ListItem` y desciende
  un solo nivel. La jerarquía completa se expone con los schemas de
  `shared/schemas/tree.py` en un endpoint propio.
- Todo elemento embebido excluye los registros con `is_deleted=True`. En
  endpoints públicos aplica además las reglas de visibilidad del dominio.

---

## 7. Validaciones

Separación obligatoria:

```text
Schema
→ formato, estructura y normalización

Service
→ reglas de negocio y coordinación de las validaciones con base de datos

Repository
→ queries y operaciones de persistencia

Model / PostgreSQL
→ integridad persistente

Integration
→ restricciones técnicas necesarias para proteger o utilizar al proveedor externo
```

Los validadores reutilizables sin acceso a base de datos viven en:

```text
shared/services/validators.py
```

Todas las funciones reutilizables de validación reciben el valor de entrada
como `object`, comprueban internamente su tipo en tiempo de ejecución y
devuelven un valor concreto validado o normalizado:

```text
object → T
```

Cuando el tipo recibido no es válido, deben lanzar `ValueError`; no deben
depender de métodos del tipo esperado antes de comprobarlo. Esta convención
permite reutilizarlas tanto con `field_validator(mode="before")` como después
del tipado de Pydantic.

Estas funciones no devuelven `None`. La decisión de permitir, conservar o
rechazar un valor `None` pertenece al schema y debe expresarse explícitamente
en su `field_validator`. Esto permite diferenciar entre un campo nullable y un
campo que puede omitirse en un `PATCH`, pero no establecerse como `null`.

---

## 8. Services

Los services contienen:

- lógica de negocio;
- coordinación de repositories;
- creación;
- actualización;
- soft delete;
- transacciones;
- validaciones con base de datos;
- asignación de campos de auditoría;
- coordinación de integrations.

CRUD estándar:

```text
get
list
create
update
delete
```

No duplicar services si uno existente resuelve correctamente la operación.

### Repositories

Cada dominio persistente utiliza `repositories.py` para encapsular el acceso a
datos. Los repositories:

- construyen y ejecutan queries con SQLModel y SQLAlchemy;
- reciben o utilizan `AsyncSession`;
- recuperan y persisten models;
- aplican filtros, orden, paginación y condiciones de soft delete solicitadas
  por el service;
- cargan explícitamente las relaciones que requiere cada `ListItem` y `Detail`,
  por ejemplo con `selectinload`, aplicando soft delete también a los
  elementos embebidos;
- pueden usar `flush()` y `refresh()` cuando la operación lo requiera.

Los repositories no contienen reglas de negocio, decisiones HTTP, schemas de
API ni llamadas a integrations. El service decide qué operación debe
realizarse y conserva el control de `commit()` y `rollback()` para poder
coordinar una misma transacción entre varios repositories.

No crear un repository genérico o una clase base por defecto. Cada repository
debe exponer operaciones explícitas que respondan a necesidades reales del
dominio.

Las routes no ejecutan queries ni llaman repositories directamente.

---

## 9. Routes

Las routes gestionan únicamente:

- HTTP;
- `Depends`;
- path/query parameters;
- schemas;
- status codes;
- llamada al service.

CRUD estándar:

```text
GET    /
GET    /{id}
GET    /{id}/audit
POST   /
PATCH  /{id}
DELETE /{id}
```

`GET /` devuelve paginación por defecto.

Schema de respuesta de cada endpoint de lectura:

```text
                  dominio sin foreign keys        dominio con foreign keys
GET /             PaginatedResponse[Response]     PaginatedResponse[ListItem]
GET /{id}         Response                        Detail
GET /{id}/audit   ResponseAudit                   ResponseAudit
```

`ListItem` y `Detail` contienen todos los campos de `Response`, por lo que lo
sustituyen sin necesidad de endpoints adicionales.

`GET /{id}/audit` expone los campos de auditoría autorizados. Cuando
`GET /{id}` y `GET /{id}/audit` recuperan el mismo registro y aplican las
mismas reglas de negocio, deben reutilizar el mismo `get`; la diferencia queda
en el `response_model`, los permisos de acceso, la información expuesta y las
relaciones que el repository carga para el `Detail`.

`GET /me` y `PATCH /me` deben reutilizar `get` y `update` cuando la lógica sea equivalente.

---

## 10. Base de datos

`core/database.py` administra:

```text
AsyncEngine
async_sessionmaker
initialize_database
check_database_connection
get_db
close_database
```

Nombres oficiales en `app.state`:

```text
app.state.db_engine
app.state.db_session_factory
```

No utilizar nombres alternativos para estos objetos.

En routes/dependencies, usar normalmente:

```python
Depends(get_db)
```

Código global fuera del flujo normal de `Depends()` puede usar `app.state.db_session_factory`.

El proyecto utiliza exactamente dos bases de datos, seleccionadas únicamente
mediante `ENVIRONMENT`:

```text
production                    → DATABASE_URL
development | test | staging → TEST_DATABASE_URL
```

`DATABASE_URL` está reservada para los datos reales de producción.
`TEST_DATABASE_URL` es la base no productiva compartida por desarrollo,
pruebas y staging. Mientras estos entornos compartan la misma base, las pruebas
automatizadas no deben vaciar tablas ni destruir datos sin una protección
explícita.

La selección de la base no depende de `DEBUG`. Tanto la aplicación en
`core/database.py` como Alembic en `migrations/env.py` deben aplicar exactamente
la misma regla.

---

## 11. Alembic

Las tablas no se crean durante startup.

No crear funciones como:

```text
create_users_table
create_auth_session_table
create_all_tables
```

No usar `SQLModel.metadata.create_all()` como sistema normal de migraciones.

Flujo:

```text
models.py
↓
Alembic autogenerate
↓
revisar migration
↓
alembic upgrade
↓
PostgreSQL
```

Al crear o modificar modelos, garantizar que Alembic pueda descubrirlos.

---

## 12. Config

Toda configuración proviene de `core/config.py`.

No leer `.env` directamente en otros módulos.

`ENVIRONMENT` es la fuente principal de comportamiento:

```text
development
staging
production
test
```

Propiedades como `DEBUG`, expiraciones, cookies y CORS pueden derivarse de `ENVIRONMENT`.

---

## 13. Logging

Todos los módulos utilizan:

```python
from app.core.logging import get_logger

logger = get_logger(__name__)
```

No configurar logging localmente.

`setup_logging(settings)` se ejecuta una sola vez durante el arranque.

---

## 14. Security

`core/security.py` contiene primitivas reutilizables:

```text
password hashing
JWT
refresh tokens
CSRF
one-time tokens
```

No contiene:

```text
login
logout
sesiones
consultas de usuarios
roles
permisos
Depends
cookies
respuestas HTTP
```

`SECRET_KEY` y `CSRF_SECRET_KEY` deben ser diferentes.

### Roles y permisos

`shared/services/permissions.py` es la única fuente de verdad de la
autorización:

```text
ROLE_PERMISSIONS → acciones que cada rol puede ejecutar en cada módulo
ROLE_LEVEL       → jerarquía de roles; un número mayor es un rango superior
```

Expone:

```python
has_permission(role, module, action) -> bool
can_manage_role(actor_role, target_role) -> bool
```

Agregar un rol exige actualizar ambas estructuras en ese archivo, y solo en
ese archivo.

Las routes verifican el permiso por módulo. El service de usuarios aplica
además la jerarquía:

- un usuario solo puede crear, modificar, eliminar o restablecer la contraseña
  de usuarios con un rol estrictamente inferior al suyo; nunca de su mismo rol
  ni de uno superior;
- solo puede asignar roles estrictamente inferiores al suyo;
- al modificar un usuario se valida tanto su rol actual como el rol resultante;
- nadie puede cambiar su propio rol: los schemas y endpoints `/me` no aceptan
  el campo de rol;
- en consecuencia, el rol de mayor rango no es gestionable desde la API y se
  crea mediante seed;
- el rol de quien actúa se obtiene siempre del usuario autenticado en el
  servidor, nunca de datos enviados por el cliente.

Una violación de la jerarquía responde `403` con `ErrorCode.PERMISSION_DENIED`.

---

## 15. Integrations

Las integrations encapsulan SDKs y proveedores externos.

No deben decidir reglas funcionales del dominio.

Pueden contener restricciones técnicas destinadas a proteger al proveedor.

### Cloudinary

Puede validar:

```text
tipo de imagen
bloqueo de SVG
tamaño máximo
```

Guardar la URL segura de la imagen:

```text
image_url
```

Para eliminar o administrar recursos, la integration puede obtener el
`public_id` desde una URL válida de Cloudinary mediante una función dedicada.
La extracción debe permanecer centralizada en `integrations/cloudinary.py`; no
debe duplicarse en routes ni services.

Si el SDK ejecuta operaciones síncronas dentro del backend async, usar un mecanismo como `asyncio.to_thread()`.

---

## 16. Middlewares

`middlewares/__init__.py` es el punto único de registro:

```python
register_exception_handlers(app, settings)
register_rate_limiter(app)
register_cors(app, settings)
```

### CORS
Solo configura `CORSMiddleware`.

### Limiter
Solo configura SlowAPI y guarda:

```text
app.state.limiter
```

El handler `429` vive únicamente en `exception_handlers.py`.

`memory://` es válido para una sola instancia/proceso efectivo. Si existen varios workers o instancias, usar almacenamiento compartido como Redis.

### Exception handlers

Centraliza:

```text
AppException
RequestValidationError
RateLimitExceeded
StarletteHTTPException
Exception
```

Los errores inesperados:

```text
→ se registran con logging
→ pueden persistirse en ErrorLog
→ no exponen detalles internos fuera de DEBUG
```

El handler global puede utilizar `app.state.db_session_factory` porque no usa
el flujo normal de `Depends(get_db)`, pero delega las queries y la persistencia
de `ErrorLog` en su repository.

---

## 17. API y main

`api.py` es exclusivamente un agregador de routers.

Estructura:

```text
api_router
├── system_router
└── no_system_router (/api/v1)
```

`main.py` debe mantenerse pequeño.

Puede:

- obtener settings;
- configurar logging;
- crear FastAPI;
- configurar lifespan;
- configurar integrations;
- inicializar PostgreSQL;
- comprobar conexión;
- guardar `db_engine` y `db_session_factory`;
- registrar middlewares;
- incluir `api_router`;
- cerrar recursos.

No debe crear tablas ni contener lógica de negocio.

---

## 18. Dirección de dependencias

Mantener:

```text
routes
↓
services
↓
repositories
↓
models
```

Para proveedores:

```text
services
↓
integrations
```

Evitar:

```text
models → services
models → routes
repositories → services
repositories → routes
services → routes
schemas → routes
integrations → routes
routes → repositories
```

---

## 19. Imports y archivos `__init__.py`

Los archivos `__init__.py` no deben utilizarse para reexportar clases,
funciones, schemas, modelos, enums ni otros símbolos definidos en módulos del
paquete.

No añadir imports de reexportación ni declaraciones `__all__` a estos archivos.
Cuando un módulo necesite un símbolo, debe importarlo mediante la ruta completa
del archivo donde se encuentra definido.

Usar:

```python
from app.domains.users.models import User
from app.domains.users.schemas import UserResponse
```

No usar:

```python
from app.domains.users import User, UserResponse
```

Como regla general, los archivos `__init__.py` deben permanecer vacíos, salvo
que exista una necesidad técnica explícita que no consista en crear una fachada
de imports.

---

## 20. Reglas para cambios

Antes de modificar código:

1. Revisar el código relacionado.
2. Reutilizar funciones existentes.
3. No crear archivos o capas innecesarias.
4. Mantener SQLModel en persistencia y Pydantic en schemas.
5. No hacer herencia entre models y schemas.
6. Mantener queries en repositories y reglas de negocio en services.
7. Mantener routes pequeñas.
8. Utilizar el logging global.
9. Utilizar `Settings` como fuente central de configuración.
10. Respetar soft delete y auditoría.
11. Utilizar Alembic para cambios estructurales.
12. Mantener los nombres oficiales de `app.state`.
13. No duplicar handlers ni services.
14. No exponer stack traces ni errores internos fuera de DEBUG.
15. Elegir la solución más simple compatible con esta arquitectura.

---

## 21. Protección de la documentación

Los archivos Markdown no se modifican como efecto secundario de implementar
un cambio funcional. En particular, `AGENTS.md` y `ARCHITECTURE.md` describen
convenciones estables y reutilizables de la plantilla, no el detalle de cada
módulo o tarea.

Crear, modificar o eliminar un dominio, endpoint, campo, schema, repository,
service, validación, regla de negocio o migration no justifica por sí solo
cambiar estos documentos. Tampoco deben actualizarse por correcciones locales,
refactors pequeños o decisiones que solo afecten a un módulo.

Solo se modifican cuando la decisión:

- cambia una regla arquitectónica transversal;
- será aplicable a los módulos futuros;
- resulta estable y útil para reutilizar la plantilla en otros servicios; o
- ha sido solicitada explícitamente como un cambio de documentación.

Antes de modificar un `.md`, comprobar si el cambio pertenece realmente a la
plantilla. Si es específico de la aplicación o de un dominio, debe quedar en el
código, tests, migrations o documentación específica de ese dominio, sin
alterar `AGENTS.md` ni `ARCHITECTURE.md`.

---

## 22. Cuándo consultar `ARCHITECTURE.md`

No leer `ARCHITECTURE.md` antes de cada cambio.

Consultarlo cuando la tarea involucre:

- crear un nuevo dominio;
- decidir dónde debe vivir una responsabilidad;
- models, auditoría o soft delete;
- schemas y validaciones;
- acceso a PostgreSQL;
- migraciones Alembic;
- autenticación o seguridad;
- integrations;
- middlewares y exception handlers;
- cambios en `main.py` o `api.py`;
- decisiones arquitectónicas no cubiertas claramente en este archivo.
