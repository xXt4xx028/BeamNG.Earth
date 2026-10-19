# LOD, visibilidad y carga de terreno

## ¿Qué fallos concretos impiden optimizar el LOD actual?

### Takeaway

Hay dos problemas prioritarios: el límite de 12 km del lanzador no tiene efecto porque el horizonte está activado por defecto, y el governor puede bloquear indefinidamente las importaciones al cargarle el tiempo base normal del motor. Son conclusiones de lectura de código y reproducción sintética; no se midieron FPS dentro del juego. [Lanzador](../../tools/start_beammp_world.py#L15) · [Selección](../../server/earthd.py#L2933) · [Governor](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/governor.lua#L235)

### Cited Findings

1. **P0: `--far-radius 12000` queda anulado por el horizonte.** El lanzador especifica 12 km, pero omite `--no-horizon`. `resolve_horizon(None, 'mesh')` devuelve `True`; `update_far()` escoge `horizon_select()` en ese caso y deja de usar `s.radius`. El horizonte comienza como mínimo en 80 km, incluso antes de tener el mapa de alturas máximas. Arreglo de bajo riesgo: pasar `--no-horizon` explícitamente en todos los perfiles de conducción y habilitar horizonte sólo como opción escénica consciente. [Lanzador:25](../../tools/start_beammp_world.py#L25) · [Resolución por defecto:156](../../server/earthd.py#L156) · [Ruta de horizonte:2873](../../server/earthd.py#L2873) · [Mínimo de 80 km:121](../../server/farfield.py#L121)

2. **P0/P1: el governor cobra trabajo ajeno al streaming y puede no permitir progreso.** `chargeEngine()` resta `max(0, Ticking-2)` cada frame, aunque no se importó nada en los frames recientes. Con presupuesto de conducción de 2 ms y un coste base de motor de 4 ms, el saldo nunca alcanza los 4 ms de una importación. Reproducción LuaJIT con el módulo real: 600 frames a 60 Hz, cada importación cuesta 4 ms; Ticking de 0/2/3/4/8 ms produce respectivamente 290/290/140/0/0 importaciones. Las filas de 4 y 8 ms terminan con tokens -39.05 y -50. No demuestra que el Ticking real de esta PC sea 4 ms; demuestra una condición alcanzable de bloqueo en equipos cuyo coste base lo sea. [Deuda:235](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/governor.lua#L235) · [Llamada incondicional del core:1184](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/core.lua#L1184)

3. **P1: hay dos escritores para la distancia de render y no se coordinan.** El ajuste `fixed` cambia sólo `LevelInfo.visibleDistance`; el core mantiene un mínimo de 100 km y vuelve a escribirlo cuando recibe un nuevo radio de horizonte. `settings.applyViewDistance()` guarda el valor ya aplicado y puede abstenerse de reponerlo aunque el core lo haya sobrescrito. Además, cambiar este ajuste no modifica la selección del servidor: bajar render no evita descargas, generación ni materiales residentes fuera del render. Debe haber un único dueño de `visibleDistance`, con preferencia explícita del usuario y radio efectivo del servidor. [Ajuste:189](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/settings.lua#L189) · [Core:291](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/core.lua#L291) · [Selección servidor:2940](../../server/earthd.py#L2940)

4. **P2: los controles gráficos normales no sustituyen este LOD.** Los tiles generados llevan un único detalle visible `detail2`; el LOD espacial del servidor es el mecanismo que cambia su geometría. BeamNG selecciona entre los detalles que existan en la forma según su tamaño proyectado; no crea simplificaciones nuevas. En modo mesh el TerrainBlock no se dibuja, así que ajustar su terreno no simplifica los tiles. No recomendar elevar `screenError`: la documentación actual lo considera un campo legado. [Forma generada:468](../../server/cdae.py#L468) · [Modo visual](../../server/farfield.py#L135) · [BeamNG TSStatic](https://documentation.beamng.com/modding/levels/level_classes/tsstatic/) · [BeamNG TerrainBlock](https://documentation.beamng.com/modding/levels/level_classes/terrainblock/)

5. **P2: el SSE existente sólo agrega detalle.** `View` sirve para subdividir más allá de la regla de distancia; no puede fusionar los tiles de distancia para mejorar FPS. Su umbral está apagado por defecto. Activarlo globalmente como optimización sería contraproducente. Mantenerlo opcional y acotado, especialmente en cordilleras con grandes errores verticales. [View y SSE](../../server/farfield.py#L310) · [Subdivisión extra:392](../../server/farfield.py#L392)

### Inferences

- El arreglo de la deuda debe medir un baseline del motor en frames que no hayan provocado streaming y cobrar el exceso atribuible a imports en una pequeña ventana posterior. Debe conservar el aislamiento de operaciones pesadas; quitar el límite sin reemplazarlo puede recuperar el patrón de tirones que el governor pretende resolver. Una garantía de progreso limitada para assets cercanos evita starvation mientras se investiga la atribución del motor. [Diseño y constantes del governor](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/governor.lua#L1)
- Un far clip de 100 km con sólo 8–12 km de mundo no aporta geometría nueva, y puede dificultar la precisión de profundidad. BeamNG recomienda elegir la distancia necesaria para la escena y usar niebla para integrar el corte; no se debe prometer una mejora de FPS sólo por cambiar este valor. [BeamNG LevelInfo](https://documentation.beamng.com/modding/levels/level_classes/levelinfo/)

### Gaps

- Falta medir el baseline de `Engine.Debug.getLastPerformanceMetrics().Ticking` en BeamNG real, en distintas PCs, durante conducción, paradas e importaciones. El benchmark anterior usó valores constantes sintéticos.
- Falta confirmar visualmente las interacciones de ajustes/horizonte y el `postApply` de LevelInfo en la versión instalada. El conflicto de escritores está demostrado estáticamente; su frecuencia depende de los mensajes recibidos.

## ¿Qué perfiles reducen carga sin modificar la física cercana?

### Takeaway

Conservar 64 celdas por tile, bloque físico 512 y los radios exactos cercanos resulta prudente. Reducir sólo el radio exterior, sus distancias de subdivisión y las texturas lejanas reduce objetos y triángulos sintéticos sin cambiar los tiles exactos alrededor del jugador. [Layout](../../server/farfield.py#L135) · [Selección](../../server/farfield.py#L344)

### Cited Findings

Benchmark sin red ni construcción de assets: Python del entorno `.venv-review`, cuatro posiciones `(0,0)`, `(123.25,567.5)`, `(-3200,1900)` y `(10000,10000)`; `Layout(64,512,True,tex)`, `min_level=layout.min_level`, sin historial de histéresis. Se invoca la función real `farfield.select`. Son promedios de conjuntos seleccionados, no triángulos que el GPU dibuje después de su frustum culling. [Algoritmo reproducido](../../server/farfield.py#L344)

| Configuración | Tiles medios | Triángulos de assets | Tiles exactos medios |
|---|---:|---:|---:|
| Horizonte mínimo 80 km, K normal | 290.5 | 2,528,512 | 19 |
| Radio fijo 12 km, K normal | 197 | 1,714,688 | 19 |
| Bajo: 8 km, K × 0.70, tex 128/128/128/64 | 129 | 1,122,816 | 19 |
| Equilibrado: 12 km, K × 0.85, tex 256/256/128/128 | 176.5 | 1,536,256 | 19 |
| Escénico: 40 km, K × 1.00, tex 256/256/256/256 | 261 | 2,271,744 | 19 |

Las cifras usan `Layout.tris = 2*cells*cells + 8*cells`. El conjunto exacto cercano, no sólo su cantidad, fue idéntico al de K normal en cada posición para los tres perfiles. Del horizonte mínimo al equilibrado hay 39.2% menos tiles/triángulos de assets, y al bajo 55.6% menos. El radio fijo de 12 km por sí solo reduce 32.2%. [Layout.tris:195](../../server/farfield.py#L195) · [Near radii](../../server/farfield.py#L84)

La ejecución de 120 selecciones por configuración dio medianas de 0.850 ms para horizonte mínimo 80 km, 0.611 ms para 12 km fijo, 0.523 ms para 8 km fijo y 0.753 ms para 40 km fijo, todos con K normal. Son números orientativos de esta ejecución; no del tiempo de carga del mundo ni del frame de juego. [Selección medida](../../server/farfield.py#L344)

Comparación de celdas a iguales radios y factores K:

| Perfil | Tiles con 64 | Tiles con 32 | Triángulos con 64 | Triángulos con 32 |
|---|---:|---:|---:|---:|
| Bajo | 129 | 338.75 | 1,122,816 | 780,480 |
| Equilibrado | 176.5 | 462.5 | 1,536,256 | 1,065,600 |
| Escénico | 261 | 713.5 | 2,271,744 | 1,643,904 |

32 celdas reduce triángulos, pero crea aproximadamente 2.6–2.7 veces más tiles/materiales y tiles exactos más pequeños (media 47 frente a 19). No es una mejora inequívoca: puede desplazar el coste a imports/drawcalls. No cambiarlo por cliente ni automáticamente durante una sesión. [Tablas K y radios según celdas](../../server/farfield.py#L78) · [Fórmulas de layout](../../server/farfield.py#L135)

Código mínimo de reproducción del benchmark de perfiles:

```python
import sys, statistics
sys.path.insert(0, 'server')
import farfield as f
positions = [(0.,0.), (123.25,567.5), (-3200.,1900.), (10000.,10000.)]
for cells in (64,32):
    for name,radius,scale,tex in (
        ('low',8000,.7,(128,128,128,64)),
        ('balanced',12000,.85,(256,256,128,128)),
        ('scenic',40000,1.,(256,256,256,256))):
        layout=f.Layout(cells,512,True,tex)
        counts=[]
        for p in positions:
            base,_=f.select(*p,radius=12000,min_level=layout.min_level,layout=layout)
            out,_=f.select(*p,radius=radius,min_level=layout.min_level,
                           layout=layout,kfun=lambda level:layout.k(level)*scale)
            assert {k for k,t in base.items() if t.level==layout.min_level} == {
                k for k,t in out.items() if t.level==layout.min_level}
            counts.append(len(out))
        n=statistics.mean(counts)
        print(name,cells,n,n*layout.tris)
```

### Inferences

- El perfil equilibrado es una opción inicial razonable para conducir juntos en Sierra Madre/Patagonia; escénico debe ser una elección del usuario. Recortar 80 km a 12 km elimina panoramas lejanos; no es una optimización sin coste visual. [Resultados sintéticos anteriores](#qué-perfiles-reducen-carga-sin-modificar-la-física-cercana)
- No conviene cambiar automáticamente la densidad geométrica de terrenos físicos o degradar la elevación regional para cumplir FPS: la física compartida debe seguir idéntica entre jugadores. Ajustar sólo las decisiones visuales de distancia, texturas y vegetación decorativa mantiene esa separación. [Exactitud respecto a TerrainBlock](../../server/farfield.py#L37)

### Gaps

- No hay FPS, VRAM ni tiempos de carga reales de México/Patagonia en esta investigación. La geometría, nieve, vegetación, agua y calidad de origen cambian el coste y el aspecto.
- Las cifras no incluyen transiciones donde padres e hijos coexisten, ni assets de edificios/vegetación; deben existir contadores aparte para la residencia máxima, imports y materiales.

## ¿Cómo adaptar la carga a PCs y regiones diferentes sin desincronizar jugadores?

### Takeaway

Separar opciones físicas del servidor y calidad visual por cliente permite adaptación conservadora. La prioridad es proteger terreno cercano y peticiones físicas; el horizonte y detalles exteriores se pueden reducir con histéresis y límites declarados. [Near y physics](../../server/farfield.py#L37) · [Governor](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/governor.lua#L1)

### Cited Findings

- BeamNG recomienda medir tiempos y basura antes de optimizar, usar su `luaProfiler` y reutilizar objetos en hooks frecuentes. Para este mod interesa registrar importaciones de geometría/material, coste del motor diferido, p50/p95 de frame, tráfico entrante y tamaño de colas. Una aceleración de Python o del selector no permite deducir FPS. [Guía oficial de rendimiento](https://documentation.beamng.com/modding/programming/performance/)
- El sistema ya informa cámara y pose cada 0.5 s; no hace falta convertir la negociación de calidad en eventos por frame. Se pueden adjuntar los cambios de perfil visual a ese intercambio y devolver radio/calidad efectivos. [POSE_INTERVAL y pose](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/core.lua#L76) · [Mensaje de pose](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/core.lua#L853)
- La carga por dirección de cámara ya está implementada como penalización para tiles fuera de cono. Reimplementarla no sería un arreglo nuevo. El motor ya puede hacer frustum culling de los objetos; reducir descargas según cámara sí puede ayudar, pero eliminar el mundo detrás puede dejar huecos al girar. [Priorización existente](../../server/earthd.py#L3001) · [VIEW_PENALTY](../../server/farfield.py#L406)
- Los geometry clipmaps originales de NVIDIA usan mallas regulares y buffers reutilizables, con actualización incremental; su frustum culling se realiza por bloques con rango vertical. Es una dirección de arquitectura, pero no puede presentarse como un cambio inmediato de Lua: requiere confirmar acceso a geometría/materiales/shaders compatibles con BeamNG. Los resultados históricos de esa implementación no son predicciones para este mod. [NVIDIA GPU Gems 2, capítulo 2](https://developer.nvidia.com/gpugems/gpugems2/part-i-geometric-complexity/chapter-2-terrain-rendering-using-gpu-based-geometry)

### Inferences

- API sugerida: campo opcional `pose.visual={tier='balanced',radiusM=12000,kScale=.85}`. En `Connection`, validar tipos numéricos finitos y rangos (`radiusM` mínimo conservador >=2 km, máximo permitido por host; `kScale` aproximadamente .55–1). Usar una función K por conexión, manteniendo `near_radii`, `min_level`, `cells`, `block`, heightmap, grading y colisiones comunes. Un cliente antiguo sin campo conserva el perfil del host. El servidor devuelve valores efectivos en `status` para diagnóstico. [Lugar de integración](../../server/earthd.py#L2642) · [Selección](../../server/earthd.py#L2933)
- Sólo adaptar la calidad después de calentamiento del frame-time y fuera de teleport/rebase. Un descenso puede requerir varios segundos por encima del objetivo; subir debe requerir un margen mayor y más tiempo de estabilidad. Separar cambios por al menos 10–15 s y usar histéresis evita una sucesión de subdivisiones/fusiones que genere más tráfico que el que ahorra. Mantener un modo manual para usuarios que prefieran panoramas a FPS. [Hysteresis y HOLD_S existentes](../../server/farfield.py#L103) · [Presupuesto de carga](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/governor.lua#L39)
- Una degradación útil puede reducir radio y vegetación decorativa exterior antes de tocar texturas cercanas. Los objetos de colisión no se deben quitar sólo porque baje el FPS. El perfil de compatibilidad multijugador debe excluir opciones estrictamente visuales y seguir incluyendo los parámetros que cambian la física. [Invariantes geométricos](../../server/farfield.py#L37) · [Perfil MP](../../server/mpprofile.py)
- Pruebas necesarias: mismo conjunto exacto cercano para cada tier; terrenos/colisiones iguales entre clientes con calidad distinta; payload inválido no provoca radio infinito; radio de horizonte no supera la cota del host; el governor progresa con Ticking base alto y aún amortiza picos después de imports. Los benchmarks anteriores dan un punto de partida de selección, no validan todos estos casos. [Algoritmo de selección](../../server/farfield.py#L344) · [Governor](../../mod/beamng_earth/lua/ge/extensions/beamngEarth/governor.lua)

### Gaps

- No se verificó una API pública del engine para instanciar geometry clipmaps con displacement por shader desde Lua. No comprometer una reescritura GPU sin una prueba mínima dentro del juego.
- Falta observar juego real con ocho clientes, mala latencia, red limitada y mezcla de GPUs. Tampoco se garantiza cobertura de datos fina en todo el planeta: ajustar LOD no inventa relieve ni caminos ausentes.
