# Optimización medida del transporte — alpha.4

Esta versión reduce el coste del envío y recepción de archivos. Mantiene la
geometría, las fuentes de terreno, la caché compartida de 40 GB y el límite de
ocho conexiones. No se ha medido FPS ni consumo total de CPU dentro de BeamNG.

## Cambios

- El cliente anuncia `remoteAssetBinary: 1` en el hello autenticado. El generador
  envía los bloques del archivo como bytes binarios y conserva los mensajes de
  control/dependencias en JSON. Sin esa capacidad usa el transporte base64 anterior.
- Cada bloque binario lleva prefijo `NUL + EAR1`, offset uint32 LE y hasta 48 KiB
  del archivo en curso, dentro del framing de longitud existente. El receptor
  verifica modo, orden, tamaño y archivo completo antes de entregar el control.
  No acepta bloques binarios en la conexión local de un generador sin modo remoto.
- El ensamblador Lua avanza un cursor. Ya no copia el resto del búfer después de
  cada mensaje; compacta al incorporar nueva entrada y libera el búfer al vaciarlo.
- La recepción tiene un presupuesto suave de **3 ms por actualización**, además
  del límite de 16 mensajes y la lectura acotada. Procesa al menos un mensaje para
  mantener progreso. Una operación individual, como finalizar/escribir/verificar
  un archivo grande, todavía puede superar el presupuesto: no garantiza frames
  de 3 ms ni elimina todos los tirones.
- Si llega EOF con mensajes completos pendientes, termina de procesarlos durante
  las siguientes actualizaciones antes de informar la desconexión. Evita perder
  la cola del stream al aplicar el presupuesto.

El auxiliar TLS no necesita cambios: transporta bytes opacos. Los límites de subida
siguen contabilizando el tamaño real del framing enviado por Earth. El mod y el
generador deben actualizarse juntos y reiniciarse antes de probar.

## Comparación reproducible

Windows, Ryzen 7 5700X, Python 3.14.6 y LuaJIT mediante Lupa. Cinco repeticiones;
medianas. Base de comparación del ensamblador: commit
`54bae46efd9b19a320ead9a758a9fedbdef03922` (alpha.3).

| Prueba | Antes | Después |
|---|---:|---:|
| Bytes para un archivo sintético de 4 MiB enviado a ocho clientes | 44,811,744 | 33,566,064 |
| Preparación/envío del lote a receptores de prueba en memoria | 208.94 ms | 8.88 ms |
| Ensamblaje Lua: veinte pasadas de un lote de 3 MiB, 64 frames por lote | 432.84 ms | 19.84 ms |

En esa carga: **25.1 % menos bytes**, aproximadamente 95.8 % menos tiempo de
preparación/envío y 95.4 % menos tiempo de ensamblaje. Las dos medidas temporales
son microbenchmarks: no incluyen TLS, los límites de velocidad, VFS, generación,
renderizado, físicas, Internet ni FPS. No deben interpretarse como un 95 % más de
rendimiento del juego. Un juego limitado por físicas/GPU puede conservar los
mismos FPS aunque el transporte haga menos trabajo.

Se midió con caché caliente en ambos modos y un receptor que cuenta/descarta
bytes. El archivo aleatorio tiene una semilla fija. La reducción de bytes es
exacta para el caso registrado; las latencias cambian según máquina y carga.

Resultados completos: [JSON](research/2026-10-18-mp-performance-alpha4.json).
Desde un checkout Git con el commit de referencia disponible, NumPy/Pillow y Lupa:

```powershell
python tools/benchmark_mp_transport.py --out resultado.json
```

## Comprobaciones

- El emisor Python genera archivos que el ensamblador y receptor Lua reales
  reconstruyen byte por byte, con segmentos TCP simulados de 7777 bytes.
- Prueba TCP real con generador y DEM sintético, tanto en modo binario como
  legacy base64; el terreno debe llegar completo antes de `anchor_ready`.
- Casos de offsets duplicados, cabeceras incompletas, tamaño excesivo, mezcla de
  codificaciones, fragmentación de frames, presupuesto y EOF pendiente.
- Regresiones del mod Lua, autenticación, límites, TLS y coordinación multijugador.

El siguiente límite a medir dentro del juego es finalizar los archivos grandes
y construir colisiones/objetos. Este cambio no demuestra una mejora de esas
operaciones ni sustituye la prueba con dos y ocho jugadores reales.
