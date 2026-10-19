# México y Patagonia para offroad — alpha.3

El objetivo incluye las cordilleras de México y toda Patagonia, por zonas bajo
demanda. No se ha descargado toda esa superficie ni existe una nueva cobertura
uniforme de alta resolución. Con ocho jugadores conviene recorrer juntos una
zona, precargarla y cambiar de región por sesiones. Alpha.3 no obliga aún a los
jugadores a quedarse juntos ni comparte automáticamente su origen geométrico.

## Por qué Estados Unidos puede verse más preciso

Mapterhorn combina fuentes de distintas resoluciones y procedencias; su
[catálogo de atribución](https://mapterhorn.com/attribution/) permite comprobarlas.
Donde hay LiDAR regional fino puede haber detalle que el modelo global no tiene.
Una cuadrícula del juego de un metro no convierte un DEM de 30 m en un
levantamiento de un metro. La foto del suelo y la elevación son datos distintos.

Se hicieron 24 peticiones pequeñas en ocho puntos: Sierra Madre Occidental,
Oriental, del Sur, Eje Volcánico, Bariloche, El Chaltén, Coyhaique y Torres del Paine.
Mapterhorn devolvió imágenes en z12 en los ocho puntos, pero 404 en z15 en todos.
EOX 2023 respondió en z14 en todos. Es disponibilidad en esos puntos, no una
medición de exactitud ni prueba de ausencia de LiDAR en toda una cordillera.
El fallback global del mod sigue funcionando; no se ha detectado un nuevo
servicio regional fino utilizable automáticamente en esos puntos.

Resultados: [JSON de las pruebas](research/2026-10-18-mexico-patagonia-coverage.json).
Se pueden repetir con `python tools/check_regional_data.py --out resultado.json`.

## Fuentes que conviene incorporar por zona

| Región | Datos candidatos | Uso y límites |
|---|---|---|
| México | [INEGI CEM 4.0](https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=794551151600) y [MDE/MDT](https://www.inegi.org.mx/app/geo2/elevacionesmex/) | CEM nacional de 15 m, edición 2025 y cobertura temporal 2024; MDT de 5 m/1.5 m donde exista cobertura. Preferir **Terreno**, no Superficie, para física. No prometer 1.5 m en todas las sierras. |
| Patagonia argentina | [IGN MDE-Ar v2.1](https://www.ign.gob.ar/content/nuevo-modelo-digital-de-elevaciones-de-la-rep%C3%BAblica-argentina) y [catálogo MDE/MDT](https://www.ign.gob.ar/NuestrasActividades/Geodesia/ModeloDigitalElevaciones/faq) | El modelo nacional es de 30 m. El catálogo tiene modelos más finos con cobertura específica; algunos necesitan solicitud. El tamaño de celda por sí solo no demuestra mejora frente a la base actual. |
| Patagonia chilena | [IDE Chile](https://www.ide.cl/), [IDE Magallanes](https://idemagallanes.cl/magallanes) | Buscar productos con cobertura y metadatos del área elegida. No se verificó un MDT fino uniforme ni un endpoint de descarga automática para toda Patagonia chilena. |
| Base global | [Copernicus GLO-30](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM) | DSM de 30 m: incluye vegetación y construcciones. El filtro del mod ayuda, pero no equivale a un MDT LiDAR. |

El MDE-Ar se publica también en formato IMG; la herramienta nueva puede leer
IMG/GeoTIFF mediante Rasterio. La reproyección cambia el CRS horizontal, **no
convierte automáticamente entre geoides/datums verticales**. Hay que verificar
referencias y unidades antes de mezclar fuentes. Revisar uniones: un desfase
vertical o borde de cobertura puede introducir un escalón. No hay validación
real de las colisiones de un paquete regional todavía.

Para las texturas sigue la base EOX existente. No se ha añadido automáticamente
Google/Esri ni un proveedor más fino sin verificar permiso de caché y distribución.
Un dato mejor para conducir suele ser primero un MDT fino y coherente, no
simplemente una textura satelital mayor.

## Importación local implementada

1. Descargar el raster oficial de la zona y comprobar licencia/atribución, alturas
   en metros, CRS y referencia vertical. No incluye descargas masivas automáticas.
2. Instalar Rasterio **sólo en la PC de preparación**:
   `python -m pip install rasterio`.
3. Preparar un paquete nuevo. Ejemplo con nombres de archivo ilustrativos:

```powershell
python tools/import_elevation.py "C:\datos\terreno.tif" --out "C:\EarthData\mexico-sierra-v1" --attribution "INEGI, producto y fecha del archivo" --vertical-reference "Referencia vertical comprobada del producto" --bounds -107.90 27.45 -107.72 27.60
```

4. Reiniciar el generador con `--local-dem-dir "C:\EarthData\mexico-sierra-v1"`
   mediante el helper o el CLI Earth. Todos sus procesos heredan el mismo paquete.

El importador prepara tiles float32 de 512 píxeles en z10–z15, conserva NoData,
limita el número de tiles a 512 por defecto y pide recortar si se supera. Esos
tiles pueden ser más gruesos que un MDT de 1.5 m; alpha.3 sigue limitado a z15,
así que no conserva toda la resolución nativa de los levantamientos más finos.
Sólo la cobertura importada reemplaza al proveedor global. Un tile local completo
evita pedir al proveedor remoto; los huecos recurren al fallback. Importar una
zona nueva requiere otro directorio; no sobrescribir paquetes mientras se juega.
Actualmente se carga **un paquete por ejecución**, no un catálogo de múltiples packs.

El manifiesto registra atribución y referencia vertical. Su identidad forma
parte del perfil multijugador y se comprueba el hash de cada tile al cargarlo;
los datos regionales no se tratan como descargas prescindibles de la caché de
40 GB. Ocupan espacio adicional fuera de ella. Rasterio no es necesario en los
clientes ni en el generador una vez preparado el paquete.

Pruebas: raster sintético reproyectado con GDAL/Rasterio real, alturas y offset,
NoData/fallback, límite de importación, rechazo de modificaciones del pack y
prioridad local sin acceso a la red. No se han importado aún archivos oficiales
de INEGI/IGN ni medido su mejora visual/física dentro de BeamNG.
