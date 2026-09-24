# Migración cargar_os.py → plugin QGIS

Base generada a partir de `cargar_os.py` (repo `Automatizaciones_Orden_Servicio`).

## Resuelto

1. **`icon.png`** — generado placeholder 64x64 (círculo azul con "OS"). Reemplazar por el
   icono definitivo del Grupo TAU cuando esté disponible.
2. **pdfplumber**: se agregó un botón "Instalar dependencia (pdfplumber)…" en el diálogo,
   visible solo si la librería no está disponible. Pide confirmación antes de correr pip
   y llama a `pdf_parser.instalar_pdfplumber()`.
3. **`plugins.xml` + `Lanzamientos/inspecciones_plugin.zip`** — a diferencia de
   `Plugin_CF_Y_PF` (que usa provider de Processing, no aplica acá porque este plugin
   registra un botón de toolbar, no algoritmos), se replicó el patrón de release:
   `plugins.xml` en la raíz del repo con un `download_url` a un zip en `Lanzamientos/`.
   Decisión: se quedó en este mismo repo (`Grupo-TAU/Automatizaciones_Orden_Servicio`),
   no en un repo separado — el `download_url` apunta ahí. Para agregar este repo como
   fuente en QGIS: Complementos → Administrar e instalar complementos → Configuración →
   Agregar, con la URL
   `https://raw.githubusercontent.com/Grupo-TAU/Automatizaciones_Orden_Servicio/main/plugins.xml`.
   Recordar re-generar el zip cada vez que cambie el contenido de `inspecciones_plugin/`.

## Pendiente (para resolver con Claude Code, con QGIS abierto para probar)

1. **Email real** en `metadata.txt` (`email=CAMBIAR_EMAIL@grupotau.com`).
2. **Probar instalación local**: copiar la carpeta `inspecciones_plugin/` completa a
   `C:\Users\grupo\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
   y activar desde el Administrador de complementos (modo "Instalado" → buscar en la lista,
   puede requerir reiniciar QGIS o `Reload` con el plugin Plugin Reloader).
3. **`RAIZ_IMAGENES` hardcodeada** en `capa_utils.py` — si varía entre las 6 PCs, migrar a
   `QgsSettings` con un default y un campo de configuración en el diálogo o en las
   opciones del plugin.
4. Revisar el regex de `padron` en `pdf_parser.py` con PDFs reales de ambos tipos de OS.
   Nota: comparado contra el `cargar_os.py` actual del repo, la lógica de anidado ya era
   igual en ambos — no hubo una regresión que corregir en la migración, solo falta
   validar con casos reales.

## Estructura

El plugin se llama **Inspecciones** y agrupa estas funcionalidades, todas
bajo el menú *Complementos → Grupo TAU*:

| Acción | Diálogo | Motor |
|---|---|---|
| Registrar OS | `dialogo_registro_os.py` | `capa_utils.py`, `pdf_parser.py` |
| Copiar imágenes de OS | `dialogo_copiar_imagenes.py` | `copiar_imagenes.py` |
| Números de inspecciones | `dialogo_conteo.py` | `sacar_numeros.py` |
| Exportar paquete de campo | `campo/dialogo_exportar.py` | `campo/exportar.py` |
| Importar cambios de campo | `campo/dialogo_importar.py` | `campo/importar.py` |
| Configurar conexión PostGIS | `campo/dialogo_conexion.py` | `campo/conexion.py`, `campo/esquema.py` |

```
inspecciones_plugin/
├── __init__.py                 # classFactory
├── metadata.txt                # manifest QGIS
├── inspecciones.py             # initGui / unload / run de las tres acciones
├── dialogo_registro_os.py      # UI (QDialog + captura de punto en mapa)
├── dialogo_copiar_imagenes.py  # UI de la copia de imágenes
├── dialogo_conteo.py           # UI de la matriz Etapa x Contrato
├── pdf_parser.py               # parseo del PDF del SOMS
├── capa_utils.py               # config + acceso a capas + escritura del feature
├── copiar_imagenes.py          # copia de fotos de una OS a una carpeta
├── sacar_numeros.py            # conteo por Etapa y Contrato (capa o planilla)
├── campo/                      # ida y vuelta con QField contra PostGIS
│   ├── config.py               # tabla, clave, COLUMNAS_EDITABLES, claves de QgsSettings
│   ├── conexion.py             # QgsSettings + QgsAuthManager, executeSql
│   ├── esquema.py              # information_schema (equivalente a \d)
│   ├── exportar.py             # PostGIS filtrado → .gpkg (reemplaza al ogr2ogr)
│   ├── importar.py             # .gpkg → staging → UPSERT → DROP
│   └── dialogo_*.py            # UIs
└── icon.png                    # placeholder generado
```

`sacar_numeros.py` no tiene interfaz ni CLI: es solo el motor de conteo. Además
del diálogo se puede llamar desde la consola de Python de QGIS con
`from inspecciones_plugin import sacar_numeros; sacar_numeros.resumen()`.

## Renombre a "Inspecciones" (v1.3.0)

La carpeta pasó de `registrar_os_plugin/` a `inspecciones_plugin/` y el zip de
release, de `registrar_os_plugin.zip` a `inspecciones_plugin.zip`. QGIS
identifica los plugins por el nombre de la carpeta, así que lo ve como un
plugin distinto: **cada usuario tiene que desinstalar "Registrar OS" antes de
instalar "Inspecciones"**, o le van a quedar los dos activos con los menús
duplicados.

## Módulo de campo (v1.4.0)

Ida y vuelta con QField contra `inspecciones_os.inspecciones` en PostGIS.

- **Conexión**: primera vez, *Configurar conexión PostGIS…*. Se puede elegir una
  conexión ya guardada en el Navegador de QGIS o cargar una propia; en la propia
  la contraseña va cifrada en el gestor de autenticación de QGIS (authcfg), y en
  `QgsSettings` (`inspecciones/campo/*`) solo quedan host, puerto, base y el id.
  El botón *Ver columnas de la tabla* muestra los nombres reales y cuáles son
  editables.
- **Exportar**: filtro por N° de OS y/o etapa (AND) → GeoPackage con la capa
  `inspecciones`, sin reproyectar (EPSG:32721). Después, QFieldSync aparte.
- **Importar**: el gpkg se copia a `inspecciones_os.inspecciones_staging_<iniciales>`
  (iniciales del operario que se piden en el diálogo, en minúsculas: `NA` → `_na`)
  (mismos tipos que la tabla real), se valida (clave nula o repetida corta), y
  un único `INSERT ... ON CONFLICT ("n°_os") DO UPDATE` actualiza **solo**
  `COLUMNAS_EDITABLES` de `campo/config.py`. La geometría y el resto de las
  columnas se escriben solo en OS nuevas creadas en campo. `fid` lo genera la
  base. El staging se borra siempre. *Probar* muestra los números sin tocar nada.
- Permisos que necesita el usuario de la base: `SELECT/INSERT/UPDATE` sobre la
  tabla y `CREATE` en el esquema `inspecciones_os` (para el staging).
- Pendiente para otra fase: resolución de conflictos server/campo (se enchufa en
  `Importacion.analizar()` / `aplicar()`), fotos (`fotos_os`), integración con
  QFieldSync.
