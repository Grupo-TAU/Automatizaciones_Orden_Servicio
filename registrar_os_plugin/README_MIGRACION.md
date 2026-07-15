# Migración cargar_os.py → plugin QGIS

Base generada a partir de `cargar_os.py` (repo `Automatizaciones_Orden_Servicio`).

## Resuelto

1. **`icon.png`** — generado placeholder 64x64 (círculo azul con "OS"). Reemplazar por el
   icono definitivo del Grupo TAU cuando esté disponible.
2. **pdfplumber**: se agregó un botón "Instalar dependencia (pdfplumber)…" en el diálogo,
   visible solo si la librería no está disponible. Pide confirmación antes de correr pip
   y llama a `pdf_parser.instalar_pdfplumber()`.
3. **`plugins.xml` + `Lanzamientos/registrar_os_plugin.zip`** — a diferencia de
   `Plugin_CF_Y_PF` (que usa provider de Processing, no aplica acá porque este plugin
   registra un botón de toolbar, no algoritmos), se replicó el patrón de release:
   `plugins.xml` en la raíz del repo con un `download_url` a un zip en `Lanzamientos/`.
   Decisión: se quedó en este mismo repo (`Grupo-TAU/Automatizaciones_Orden_Servicio`),
   no en un repo separado — el `download_url` apunta ahí. Para agregar este repo como
   fuente en QGIS: Complementos → Administrar e instalar complementos → Configuración →
   Agregar, con la URL
   `https://raw.githubusercontent.com/Grupo-TAU/Automatizaciones_Orden_Servicio/main/plugins.xml`.
   Recordar re-generar el zip cada vez que cambie el contenido de `registrar_os_plugin/`.

## Pendiente (para resolver con Claude Code, con QGIS abierto para probar)

1. **Email real** en `metadata.txt` (`email=CAMBIAR_EMAIL@grupotau.com`).
2. **Probar instalación local**: copiar la carpeta `registrar_os_plugin/` completa a
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

```
registrar_os_plugin/
├── __init__.py            # classFactory
├── metadata.txt           # manifest QGIS
├── registrar_os.py        # initGui / unload / run
├── dialogo_registro_os.py # UI (QDialog + captura de punto en mapa)
├── pdf_parser.py          # parseo del PDF del SOMS
├── capa_utils.py          # config + acceso a capas + escritura del feature
└── icon.png                # placeholder generado
```
