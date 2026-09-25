-- Clave estable para observaciones: permite reimportar un GeoPackage sin duplicar filas.
-- El fid no sirve para esto: el del GeoPackage no es el de la base y cambia en cada ciclo.
--
-- Correr UNA vez, con un usuario dueño de la tabla (psql o DBeaver/pgAdmin).
-- gen_random_uuid() es nativo desde PostgreSQL 13; en versiones anteriores
-- ejecutar antes: CREATE EXTENSION IF NOT EXISTS pgcrypto;
--
-- Las filas que ya existen reciben un uuid distinto cada una.

BEGIN;

ALTER TABLE inspecciones_os.observaciones
    ADD COLUMN IF NOT EXISTS uuid uuid NOT NULL DEFAULT gen_random_uuid();

CREATE UNIQUE INDEX IF NOT EXISTS observaciones_uuid_key
    ON inspecciones_os.observaciones (uuid);

COMMIT;
