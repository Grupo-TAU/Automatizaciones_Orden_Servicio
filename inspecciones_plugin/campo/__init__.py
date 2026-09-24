"""
Ida y vuelta de datos con el trabajo de campo (QField).

- exportar.py: arma el GeoPackage filtrado desde PostGIS (reemplaza al ogr2ogr manual).
- importar.py: trae el GeoPackage editado en campo y hace UPSERT seguro en PostGIS.

Los motores no tienen UI; los diálogo_*.py son la interfaz del plugin.
"""
