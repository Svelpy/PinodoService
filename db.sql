-- =====================================================================
-- Tienda de ropa - Esquema PostgreSQL v4
-- Todas las tablas, excepto config, llevan los campos de BaseModel:
--   id, created_at, created_by, updated_at, updated_by,
--   is_deleted, deleted_at, deleted_by
-- No hay borrado físico: los registros se marcan con is_deleted = true.
-- Los valores únicos solo se exigen entre registros NO borrados
-- (índices únicos parciales WHERE is_deleted = false).
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS "public";

-- ---------------------------------------------------------------------
-- USUARIOS
-- ---------------------------------------------------------------------
CREATE TABLE "public"."usuarios" (
    "id" uuid NOT NULL,
    "email" varchar(255) NOT NULL,
    "password_hash" varchar(255) NOT NULL,
    "nombre" varchar(100) NOT NULL,
    "apellidos" varchar(150),
    "telefono" varchar(30),
    "rol" varchar(20) NOT NULL,
    "created_at" timestamptz NOT NULL DEFAULT now(),
    "created_by" uuid,
    "updated_at" timestamptz NOT NULL DEFAULT now(),
    "updated_by" uuid,
    "is_deleted" boolean NOT NULL DEFAULT FALSE,
    "deleted_at" timestamptz,
    "deleted_by" uuid,
    PRIMARY KEY ("id")
);
CREATE INDEX "usuarios_idx_is_deleted" ON "public"."usuarios" ("is_deleted");
CREATE UNIQUE INDEX "uq_usuarios_email" ON "public"."usuarios" ("email") WHERE "is_deleted" = FALSE;

-- ---------------------------------------------------------------------
-- CONFIG (una sola fila, id = 1; no hereda BaseModel)
-- ---------------------------------------------------------------------
CREATE TABLE "public"."config" (
    "id" integer NOT NULL DEFAULT 1,
    "nombre_tienda" varchar(150) NOT NULL,
    "descripcion" text,
    "logo_url" varchar(500),
    "favicon_url" varchar(500),
    "email_contacto" varchar(255),
    "telefono" varchar(30),
    "whatsapp" varchar(30),
    "direccion" varchar(255),
    "map_url" varchar(500),
    "ciudad" varchar(100),
    "horario" jsonb NOT NULL DEFAULT '{}',
    "redes_sociales" jsonb NOT NULL DEFAULT '{}',
    "en_mantenimiento" boolean NOT NULL DEFAULT FALSE,
    "updated_at" timestamptz NOT NULL DEFAULT now(),
    "updated_by" uuid,
    PRIMARY KEY ("id"),
    CONSTRAINT "ck_config_fila_unica" CHECK ("id" = 1)
);

-- ---------------------------------------------------------------------
-- CATÁLOGO Y NAVEGACIÓN
-- ---------------------------------------------------------------------
CREATE TABLE "public"."secciones" (
    "id" uuid NOT NULL,
    "nombre" varchar(100) NOT NULL,
    "slug" varchar(120) NOT NULL,
    "is_visible" boolean NOT NULL DEFAULT TRUE,
    "created_at" timestamptz NOT NULL DEFAULT now(),
    "created_by" uuid,
    "updated_at" timestamptz NOT NULL DEFAULT now(),
    "updated_by" uuid,
    "is_deleted" boolean NOT NULL DEFAULT FALSE,
    "deleted_at" timestamptz,
    "deleted_by" uuid,
    PRIMARY KEY ("id")
);
CREATE INDEX "secciones_idx_is_deleted" ON "public"."secciones" ("is_deleted");
CREATE UNIQUE INDEX "uq_secciones_slug" ON "public"."secciones" ("slug") WHERE "is_deleted" = FALSE;

CREATE TABLE "public"."categorias" (
    "id" uuid NOT NULL,
    "seccion_id" uuid NOT NULL,
    "parent_id" uuid,
    "nombre" varchar(100) NOT NULL,
    "slug" varchar(120) NOT NULL,
    "is_visible" boolean NOT NULL DEFAULT TRUE,
    "created_at" timestamptz NOT NULL DEFAULT now(),
    "created_by" uuid,
    "updated_at" timestamptz NOT NULL DEFAULT now(),
    "updated_by" uuid,
    "is_deleted" boolean NOT NULL DEFAULT FALSE,
    "deleted_at" timestamptz,
    "deleted_by" uuid,
    PRIMARY KEY ("id")
);
CREATE INDEX "categorias_idx_categorias_parent" ON "public"."categorias" ("parent_id");
CREATE INDEX "categorias_idx_categorias_seccion" ON "public"."categorias" ("seccion_id");
CREATE INDEX "categorias_idx_is_deleted" ON "public"."categorias" ("is_deleted");
CREATE UNIQUE INDEX "uq_categorias_seccion_slug" ON "public"."categorias" ("seccion_id", "slug") WHERE "is_deleted" = FALSE;

-- ---------------------------------------------------------------------
-- PRODUCTO
-- ---------------------------------------------------------------------
CREATE TABLE "public"."productos" (
    "id" uuid NOT NULL,
    "seccion_id" uuid NOT NULL,
    "nombre" varchar(200) NOT NULL,
    "descripcion" text,
    "cuidados" text,
    "composicion" text,
    "is_visible" boolean NOT NULL DEFAULT TRUE,
    "created_at" timestamptz NOT NULL DEFAULT now(),
    "created_by" uuid,
    "updated_at" timestamptz NOT NULL DEFAULT now(),
    "updated_by" uuid,
    "is_deleted" boolean NOT NULL DEFAULT FALSE,
    "deleted_at" timestamptz,
    "deleted_by" uuid,
    PRIMARY KEY ("id")
);
CREATE INDEX "productos_idx_productos_seccion" ON "public"."productos" ("seccion_id");
CREATE INDEX "productos_idx_is_deleted" ON "public"."productos" ("is_deleted");

-- Enlace categoría-producto: ahora tiene id propio para poder marcarse
-- como borrado (quitar un producto de una categoría sin borrado físico).
CREATE TABLE "public"."categoria_productos" (
    "id" uuid NOT NULL,
    "categoria_id" uuid NOT NULL,
    "producto_id" uuid NOT NULL,
    "created_at" timestamptz NOT NULL DEFAULT now(),
    "created_by" uuid,
    "updated_at" timestamptz NOT NULL DEFAULT now(),
    "updated_by" uuid,
    "is_deleted" boolean NOT NULL DEFAULT FALSE,
    "deleted_at" timestamptz,
    "deleted_by" uuid,
    PRIMARY KEY ("id")
);
CREATE INDEX "categoria_productos_idx_catprod_producto" ON "public"."categoria_productos" ("producto_id");
CREATE INDEX "categoria_productos_idx_is_deleted" ON "public"."categoria_productos" ("is_deleted");
CREATE UNIQUE INDEX "uq_categoria_productos" ON "public"."categoria_productos" ("categoria_id", "producto_id") WHERE "is_deleted" = FALSE;

CREATE TABLE "public"."colores" (
    "id" uuid NOT NULL,
    "nombre" varchar(60) NOT NULL,
    "slug" varchar(80) NOT NULL,
    "codigo_hex" varchar(7) NOT NULL,
    "created_at" timestamptz NOT NULL DEFAULT now(),
    "created_by" uuid,
    "updated_at" timestamptz NOT NULL DEFAULT now(),
    "updated_by" uuid,
    "is_deleted" boolean NOT NULL DEFAULT FALSE,
    "deleted_at" timestamptz,
    "deleted_by" uuid,
    PRIMARY KEY ("id")
);
CREATE INDEX "colores_idx_is_deleted" ON "public"."colores" ("is_deleted");
CREATE UNIQUE INDEX "uq_colores_slug" ON "public"."colores" ("slug") WHERE "is_deleted" = FALSE;

CREATE TABLE "public"."producto_colores" (
    "id" uuid NOT NULL,
    "producto_id" uuid NOT NULL,
    "color_id" uuid NOT NULL,
    "is_visible" boolean NOT NULL DEFAULT TRUE,
    "created_at" timestamptz NOT NULL DEFAULT now(),
    "created_by" uuid,
    "updated_at" timestamptz NOT NULL DEFAULT now(),
    "updated_by" uuid,
    "is_deleted" boolean NOT NULL DEFAULT FALSE,
    "deleted_at" timestamptz,
    "deleted_by" uuid,
    PRIMARY KEY ("id")
);
CREATE INDEX "producto_colores_idx_prodcolor_producto" ON "public"."producto_colores" ("producto_id");
CREATE INDEX "producto_colores_idx_is_deleted" ON "public"."producto_colores" ("is_deleted");
CREATE UNIQUE INDEX "uq_producto_colores_producto_color" ON "public"."producto_colores" ("producto_id", "color_id") WHERE "is_deleted" = FALSE;

CREATE TABLE "public"."imagenes" (
    "id" uuid NOT NULL,
    "producto_color_id" uuid NOT NULL,
    "url" varchar(500) NOT NULL,
    "tipo" varchar(20) NOT NULL DEFAULT 'MODELO',
    "created_at" timestamptz NOT NULL DEFAULT now(),
    "created_by" uuid,
    "updated_at" timestamptz NOT NULL DEFAULT now(),
    "updated_by" uuid,
    "is_deleted" boolean NOT NULL DEFAULT FALSE,
    "deleted_at" timestamptz,
    "deleted_by" uuid,
    PRIMARY KEY ("id")
);
CREATE INDEX "imagenes_idx_imagenes_prodcolor" ON "public"."imagenes" ("producto_color_id");
CREATE INDEX "imagenes_idx_is_deleted" ON "public"."imagenes" ("is_deleted");

CREATE TABLE "public"."tallas" (
    "id" uuid NOT NULL,
    "etiqueta" varchar(30) NOT NULL,
    "created_at" timestamptz NOT NULL DEFAULT now(),
    "created_by" uuid,
    "updated_at" timestamptz NOT NULL DEFAULT now(),
    "updated_by" uuid,
    "is_deleted" boolean NOT NULL DEFAULT FALSE,
    "deleted_at" timestamptz,
    "deleted_by" uuid,
    PRIMARY KEY ("id")
);
CREATE INDEX "tallas_idx_is_deleted" ON "public"."tallas" ("is_deleted");
CREATE UNIQUE INDEX "uq_tallas_etiqueta" ON "public"."tallas" ("etiqueta") WHERE "is_deleted" = FALSE;

CREATE TABLE "public"."skus" (
    "id" uuid NOT NULL,
    "producto_color_id" uuid NOT NULL,
    "talla_id" uuid NOT NULL,
    "codigo_barras" varchar(50),
    "is_visible" boolean NOT NULL DEFAULT TRUE,
    "precio" jsonb NOT NULL DEFAULT '{"normal": 0, "rebajado": null, "rebaja_hasta": null}',
    "stock" jsonb NOT NULL DEFAULT '{"cantidad": 0, "minimo": 0, "actualizado": null}',
    "created_at" timestamptz NOT NULL DEFAULT now(),
    "created_by" uuid,
    "updated_at" timestamptz NOT NULL DEFAULT now(),
    "updated_by" uuid,
    "is_deleted" boolean NOT NULL DEFAULT FALSE,
    "deleted_at" timestamptz,
    "deleted_by" uuid,
    PRIMARY KEY ("id")
);
CREATE INDEX "skus_idx_skus_talla" ON "public"."skus" ("talla_id");
CREATE INDEX "skus_idx_is_deleted" ON "public"."skus" ("is_deleted");
CREATE UNIQUE INDEX "uq_skus_color_talla" ON "public"."skus" ("producto_color_id", "talla_id") WHERE "is_deleted" = FALSE;
CREATE UNIQUE INDEX "uq_skus_codigo_barras" ON "public"."skus" ("codigo_barras") WHERE "is_deleted" = FALSE;

-- ---------------------------------------------------------------------
-- Foreign key constraints
-- ---------------------------------------------------------------------
ALTER TABLE "public"."categoria_productos" ADD CONSTRAINT "fk_categoria_productos_categoria_id_categorias_id" FOREIGN KEY("categoria_id") REFERENCES "public"."categorias"("id");
ALTER TABLE "public"."categoria_productos" ADD CONSTRAINT "fk_categoria_productos_producto_id_productos_id" FOREIGN KEY("producto_id") REFERENCES "public"."productos"("id");
ALTER TABLE "public"."categorias" ADD CONSTRAINT "fk_categorias_parent_id_categorias_id" FOREIGN KEY("parent_id") REFERENCES "public"."categorias"("id");
ALTER TABLE "public"."categorias" ADD CONSTRAINT "fk_categorias_seccion_id_secciones_id" FOREIGN KEY("seccion_id") REFERENCES "public"."secciones"("id");
ALTER TABLE "public"."imagenes" ADD CONSTRAINT "fk_imagenes_producto_color_id_producto_colores_id" FOREIGN KEY("producto_color_id") REFERENCES "public"."producto_colores"("id");
ALTER TABLE "public"."producto_colores" ADD CONSTRAINT "fk_producto_colores_color_id_colores_id" FOREIGN KEY("color_id") REFERENCES "public"."colores"("id");
ALTER TABLE "public"."producto_colores" ADD CONSTRAINT "fk_producto_colores_producto_id_productos_id" FOREIGN KEY("producto_id") REFERENCES "public"."productos"("id");
ALTER TABLE "public"."productos" ADD CONSTRAINT "fk_productos_seccion_id_secciones_id" FOREIGN KEY("seccion_id") REFERENCES "public"."secciones"("id");
ALTER TABLE "public"."skus" ADD CONSTRAINT "fk_skus_producto_color_id_producto_colores_id" FOREIGN KEY("producto_color_id") REFERENCES "public"."producto_colores"("id");
ALTER TABLE "public"."skus" ADD CONSTRAINT "fk_skus_talla_id_tallas_id" FOREIGN KEY("talla_id") REFERENCES "public"."tallas"("id");
