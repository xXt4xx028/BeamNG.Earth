# Revisión del puente por eventos de BeamMP

Actualización alpha.3: el relay por eventos sigue sin implementarse. Se añadió
en cambio un [auxiliar TLS con conexión separada](BEAMMP-CLIENT-BRIDGE.md), para
evitar transportar los archivos del terreno por los eventos del juego.

Revisión de código: 2026-10-18. Estado: viable para un prototipo; no implementado
en alpha.2 ni validado con jugadores reales. No se ha medido rendimiento.

## Resultado

El generador puede permanecer en la PC del anfitrión, con su caché compartida de
40 GB y ocho sesiones independientes. Es posible plantear que los clientes pidan
y reciban terreno a través del transporte de BeamMP. Eso evita que el Lua del
juego tenga que abrir una conexión directa a una IP pública.

No hay evidencia suficiente para afirmar que los eventos soporten el volumen de
terreno de ocho jugadores explorando zonas diferentes sin afectar al juego.
La existencia de la API confirma el camino funcional, no su capacidad práctica.

## Evidencia y límites

Se revisaron BeamMP-Server **v3.9.3**, Launcher **v2.8.1** y el mod cliente en
commit **3b15cdd17635aa3bb00f04d73a98db87dacb5fd5**. Las versiones instaladas
deben verificarse antes de probar. Los snapshots de consulta están en
`dist/transport-review/`, fuera del paquete distribuido.

| Parte | Hallazgo | Consecuencia |
|---|---|---|
| [Servidor: `InternalTriggerClientEvent`](https://github.com/BeamMP/BeamMP-Server/blob/v3.9.3/src/LuaAPI.cpp#L139) | Construye `E:nombre:datos` y envía al jugador indicado mediante `Respond(..., true)` | Permite entregar fragmentos privados a cada jugador; no usar broadcast para terreno de destinos distintos. |
| [Servidor: `Respond`](https://github.com/BeamMP/BeamMP-Server/blob/v3.9.3/src/TNetwork.cpp#L1206) | Los eventos `E` van por TCP. Los mensajes grandes pasan por compresión. | Comparten conexión fiable con otros mensajes del juego. La compresión no crea un canal independiente. |
| [Servidor: `TCPSend`](https://github.com/BeamMP/BeamMP-Server/blob/v3.9.3/src/TNetwork.cpp#L565) | Usa `boost::asio::write` síncrono | Un envío bajo contrapresión puede retener el manejador Lua; un límite de bytes por segundo no garantiza por sí solo ausencia de bloqueos. |
| [Cliente: `MPGameNetwork`](https://github.com/BeamMP/BeamMP/blob/3b15cdd17635aa3bb00f04d73a98db87dacb5fd5/lua/ge/extensions/MPGameNetwork.lua) | `TriggerServerEvent` usa la conexión al launcher local. `onUpdate` procesa los eventos recibidos durante el frame. | Las peticiones pueden viajar por Internet a través del launcher; deserializar o escribir muchos fragmentos en un frame puede causar tirones. |
| [Launcher: `GameSend` y `ServerSend`](https://github.com/BeamMP/BeamMP-Launcher/blob/v2.8.1/src/Network/GlobalHandler.cpp) | Reenvía los eventos y serializa los envíos al juego con un mutex. `ServerSend` contiene además un `abort()` para datos de más de 500 bytes que contengan `Zp`. | Mantener las peticiones y confirmaciones pequeñas, con formato controlado. No tratar el camino de subida como un transporte binario arbitrario. |
| [Servidor: `TCPRcv`](https://github.com/BeamMP/BeamMP-Server/blob/v3.9.3/src/TNetwork.cpp#L603) | Tiene un límite de cabecera de `100 * MB` para clientes autenticados; 4096 para no autenticados. | Es un límite de recepción del servidor, no una garantía de tamaño de evento en toda la cadena ni una recomendación para enviar archivos enormes. |
| [Servidor: `Lua_HttpCreateConnection`](https://github.com/BeamMP/BeamMP-Server/blob/v3.9.3/src/TLuaEngine.cpp#L750) | El `Get` observado ejecuta la petición pero no devuelve su cuerpo a Lua. | No basta usar esta API para leer las respuestas del generador. Hace falta implementar también el puente local Python/Lua. |

Las posiciones pequeñas suelen usar UDP, pero el tráfico del terreno competiría
por el mismo enlace de Internet y por el procesamiento del launcher/juego.
Por eso no sería correcto garantizar que los coches no se verán afectados.

## Diseño que merece una prueba

Flujo propuesto:

`mod del jugador → eventos BeamMP → recurso del servidor → generador local`

`generador local → recurso del servidor → eventos BeamMP → archivos temporales del jugador`

- Mantener el generador accesible sólo localmente. El identificador del jugador
  viene de BeamMP, nunca de un campo confiado al cliente.
- Implementar el enlace local entre el recurso Lua y Python. Una cola de archivos
  con publicación atómica es una opción sin dependencias nativas adicionales;
  un socket requiere comprobar e instalar un módulo compatible en el servidor.
  Ninguna de las dos opciones existe actualmente en alpha.2.
- Reutilizar el receptor de archivos existente, su orden de dependencias y sus
  versiones de contenido. En alpha.2 está conectado al socket Earth directo;
  todavía debe adaptarse a eventos, no sólo cambiar la IP configurada.
- Empezar con fragmentos de 8–16 KiB, ventana pequeña de confirmaciones, colas
  limitadas por **bytes**, caducidad de sesiones y límite global de subida.
  Son valores iniciales de ensayo, no límites oficiales ni rendimiento validado.
- Confirmar recepción después de consumir el fragmento en el cliente; que
  `TriggerClientEvent` devuelva éxito no significa que el juego ya lo procesó.
- Repartir turnos entre jugadores y priorizar terreno próximo y colisiones sobre
  imágenes lejanas. Cancelar trabajo obsoleto cuando cambie el origen.
- Encolar la recepción y limitar deserialización/escritura por frame. Evitar
  ejecutar el ensamblaje pesado directamente en el callback de BeamMP.

## Cómo decidir si sirve para ocho jugadores

Primero probar dos clientes reales: petición, generación, recepción binaria,
colisiones, desplazamiento de origen, desconexión y reconexión. Después comparar
ocho jugadores juntos y ocho destinos separados, con caché fría y caliente.

Medir subida real, tamaño de las colas, latencia de confirmación, tiempo de llegada
del terreno, frames lentos y retraso de mensajes de vehículos. Simular un jugador
con conexión lenta y comprobar que no frena a los demás.

Ejemplo aritmético, **no benchmark**: limitar el transporte a 256 KiB/s por jugador
supone aproximadamente 16.8 Mbit/s agregados para ocho jugadores. Un archivo de
10 MiB requiere unos 53 segundos a ese límite si viaja en base64, antes de contar
metadatos y sin considerar la compresión de BeamMP. El consumo real depende de
los datos y del ritmo de exploración; la caché de 40 GB no determina la subida.

Si el puente no entrega el terreno a tiempo o bloquea el juego, la alternativa
es separar la transferencia de archivos mediante una VPN compatible o un pequeño
puente local en el cliente. Eso mantiene la generación en el host, pero añade
un requisito en las PCs de los jugadores. No se necesita trasladar el generador
completo a cada jugador para usar esa alternativa.

## Estado del paquete actual

Alpha.2 sigue usando el socket Earth directo y requiere LAN/VPN/túnel compatible.
Esta revisión no convierte ese paquete en una versión de relay por Internet.
El resultado permite construir una prueba acotada del relay, sin prometer aún
streaming fluido para ocho exploradores independientes.
