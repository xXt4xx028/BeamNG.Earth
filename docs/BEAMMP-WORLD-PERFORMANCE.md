# Carga, LOD y memoria — alpha.5

Alpha.5 añade perfiles de generación, detalle exterior por jugador y control del
trabajo de vegetación/colisiones. Es una versión experimental del fork BeamMP.
Las pruebas de componentes pasan; todavía faltan FPS/VRAM y conducción con dos
y ocho juegos reales. Reducir tiles seleccionados no significa aumentar los FPS
en ese mismo porcentaje. El coste de vehículos, sombras, resolución y drivers
sigue dependiendo del juego y del equipo.

## Perfiles del host

El helper `tools/start_beammp_world.py` usa `--performance auto`: bajo con menos
de 16 GiB de RAM física, equilibrado a partir de ahí. No detecta la VRAM ni la
RAM libre, y elige el perfil sólo al iniciar. Puedes elegirlo explícitamente:

```powershell
python tools/start_beammp_world.py --beammp-dir "C:\BeamMP-Test" --public-host 10.0.0.5 --listen 10.0.0.5 --performance balanced
```

| Perfil | Radio exterior fijo | Factor de LOD exterior | Texturas por bandas | Caché DEM agregada | DuckDB por conexión |
|---|---:|---:|---|---:|---:|
| low | 8 km | 0.70 | 128/128/128/64 | hasta 256 MiB | 256 MiB |
| balanced | 12 km | 0.85 | 256/256/128/128 | hasta 512 MiB | 384 MiB |
| scenic | 40 km | 1.00 | 256/256/256/256 | hasta 1024 MiB | 512 MiB |

Los perfiles desactivan el horizonte automático. Antes, el helper indicaba
`--far-radius 12000` pero el horizonte activo por defecto lo sustituía por al
menos 80 km. Ahora el radio se aplica y el cliente sigue su distancia visible
con un margen del 10 %. Los perfiles conservan celdas/bloque y radios exactos
cercanos; low no simplifica alturas físicas ni elimina obstáculos cercanos.
Se pierde alcance y detalle del panorama lejano. scenic también usa radio fijo;
el horizonte real sigue siendo una elección explícita del CLI del generador.

El CLI directo `server/earthd.py` acepta `--performance` y las opciones
`--lod-scale`, `--dem-cache-mib`, `--image-cache-tiles` y `--query-memory-mib`.
Una opción escrita explícitamente prevalece sobre el perfil, incluso
`--horizon`/`--no-horizon`. Sin `--performance`, conserva los valores anteriores.
SSE (`--lod-px`) no se activa automáticamente: puede aumentar la geometría.

## Calidad por jugador

En Pausa → Mods → BeamNG.Earth → World → **Outer terrain detail**:

- **Balanced** conserva el detalle permitido por el host (valor inicial).
- **Low** pide un factor exterior adicional de 0.70.
- **Auto** baja por pasos 1/0.85/0.70/0.55 ante frames lentos sostenidos, con
  objetivo aproximado de 30 FPS. Calienta 3 s, exige 3 s de lentitud, separa los
  cambios por 10 s y exige 20 s de recuperación sostenida para subir. Excluye
  pausa, rebase, teleport y frames aislados de más de 250 ms.

El servidor anuncia `hello.adaptiveLod`; sólo entonces el cliente envía
`quality {lodScale}`. Valida valores finitos en [0.55, 1], limita la recomputación
a un cambio por segundo y mantiene la preferencia independiente de cada jugador.
El cliente reenvía el estado cada 10 s para que cambios rápidos del menú converjan.
La calidad escala K y el umbral SSE en sentidos compatibles. No altera el radio
del host, near radii, alturas, grading, cuadrícula ni colisiones; tampoco garantiza
30 FPS si el cuello de botella es la física u otra parte del render.

La opción **View distance → Fixed** ahora tiene prioridad sobre los mensajes del
horizonte. Su mínimo baja a 2 km. Sólo recorta el render: para reducir generación
y descargas hay que usar el perfil del host o el detalle exterior por cliente.
Los servidores anteriores no reciben mensajes nuevos de calidad.

## Picos de carga y memoria

- El governor aprende el coste base de `Ticking` en frames sin streaming y sólo
  atribuye deuda a imports/trabajo pesado reciente (ventana de 3 frames). Antes,
  un coste base alto podía consumir cada nuevo presupuesto y bloquear las
  importaciones indefinidamente. Conserva la deuda de picos y los frames quietos.
- Los árboles mantienen el batching existente de tres frames, que evita pagar
  costes fijos del motor en cada frame. Crear y retirar items ahora comparte el
  presupuesto de streaming y cede cuando se agota. No cambia densidad ni solidez
  cercanas y respeta los frames pesados/quietos. Una operación del motor sigue
  siendo indivisible y puede exceder el presupuesto.
- Carreteras solicita la reconstrucción de colisiones en un slot pesado ANTES
  de importar objetos. Evita mezclar ambos trabajos o impedir que llegue un
  periodo quieto. Conserva la comprobación que evita activar colisión alrededor
  de un coche. Los costes de imports se miden con reloj de pared, no CPU acumulada
  de todos los hilos del juego.
- El HUD oculto ya no construye su vista cada frame; el governor reutiliza el
  array de medianas. Créditos, barra de estado y avisos siguen actualizándose.
- La caché DEM se reparte entre el proceso principal y los procesos configurados.
  balanced con siete procesos pasa de capacidad histórica de 7 × 512 = 3584 MiB
  a 7 × 73 = 511 MiB de datos LRU de elevación. No es una medición del ahorro de
  RAM real ni un límite de RSS. Imágenes raw/corregidas tienen cada una 128/256/512
  entradas por perfil. Se limita también el número de hilos de fetch de estos
  decodificadores.
- Cada conexión de consulta DuckDB recibe un `memory_limit` explícito. Sus
  asignaciones externas, consultas simultáneas, cachés de mapas, arrays de
  construcción, intérpretes Python y BeamNG consumen memoria adicional. No hay
  aún un límite global de RSS/consultas/red entre todos los procesos.
- La recuperación de una caché geográfica dañada cierra ahora el archivo incluso
  si falla la apertura del ZIP. Evita retener handles que dificulten su reemplazo
  en Windows. Las pruebas de rutas y créditos se hacen independientes del sistema.

La caché compartida **40 GB** sigue siendo un objetivo de disco para descargas.
No son 40 GB de RAM y no incluyen runtime generado, paquete regional ni cachés
temporales locales de los jugadores. Los detalles están en la guía central.

## Evidencia reproducible

```powershell
python tools/benchmark_mp_world.py --out resultado.json
```

Prueba sin red con `farfield.select` real, cuatro posiciones, 64 celdas y bloque
512. Referencia: horizonte mínimo de 80 km, selección circular con raíces L10
antes de estar lista su rejilla de visibilidad. Los perfiles fijos seleccionan
su cuadrado exterior. No modela el horizonte de una montaña concreta.

| Selección | Tiles medios | Triángulos de assets | Reducción de tiles |
|---|---:|---:|---:|
| Horizonte mínimo anterior | 290.5 | 2,528,512 | — |
| 12 km fijo, K normal | 197 | 1,714,688 | 32.2 % |
| low | 129 | 1,122,816 | 55.6 % |
| balanced | 176.5 | 1,536,256 | 39.2 % |
| scenic | 261 | 2,271,744 | 10.2 % |

En las cuatro posiciones el conjunto exacto cercano fue idéntico, con media de
19 tiles. Se cuentan triángulos de assets, no triángulos finales dibujados. Se
excluyen DEM, generación, disco, red, VFS, transiciones, vegetación, edificios,
física y render. [Resultados JSON](research/2026-10-18-world-performance-alpha5.json).

Las pruebas cubren progreso del governor con `Ticking` normal de 2/4/8/20 ms,
atribución de picos posteriores, cedencia y reanudación de árboles, slots de
colisión, control de distancia del menú, cambios de calidad por TCP real entre
dos clientes y preservación del conjunto cercano. También se comprueban el CLI
headless, opciones explícitas, presupuesto de procesos y una conexión DuckDB real.
La batería Lua simula el motor; no mide su coste real de import/render.

`python tools/probe_mp_runtime.py` ofrece una comprobación aislada opcional con
BeamNG abierto y MCP activado: ejecuta governor/calidad en un entorno local y
escribe/lee/retira un archivo binario pequeño en VFS. No instala hooks, cambia
el mapa ni mide FPS. La comprobación de esta entrega no dejó un resultado
registrado completo porque la sesión del juego dejó de estar disponible.

Quedan para una evolución posterior la deduplicación de geometría entre orígenes
idénticos, admisión global de trabajos y presupuestos globales, además de técnicas
GPU que requieren APIs y pruebas dentro del motor. No se incluyen como mejoras
ya terminadas. La guía regional distingue mejor resolución de mayor exactitud.

Se consultaron las [recomendaciones oficiales de rendimiento Lua de BeamNG](https://documentation.beamng.com/modding/programming/performance/),
[TSStatic y sus LOD](https://documentation.beamng.com/modding/levels/level_classes/tsstatic/)
y [gestión de memoria de DuckDB](https://duckdb.org/2024/07/09/memory-management).
