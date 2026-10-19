# Auxiliar de red para jugadores — alpha.3

El auxiliar es posible como programa externo. No encontramos una API soportada
que permita a un mod ZIP de BeamMP instalar y ejecutar automáticamente un EXE.
El [launcher](https://github.com/BeamMP/BeamMP-Launcher/blob/v2.8.1/src/Network/Resources.cpp)
sincroniza archivos de mods, pero no proporciona un instalador/ejecutor de este
servicio. La investigación del sandbox del juego está en [ARCHITECTURE.md](https://github.com/xXt4xx028/BeamNG.Earth/blob/beammp/earth-sync/docs/ARCHITECTURE.md).

Por tanto, no se entrega un supuesto «mod extra» que se autoejecute. Se entrega
un auxiliar que cada jugador abre antes de entrar, o cuyo inicio puede integrarse
en un launcher personalizado en un trabajo posterior.

Flujo: `mod → localhost:47614 → auxiliar → TLS por Internet → generador del host`.
BeamMP mantiene su conexión normal para coches. Ambas conexiones comparten la
subida de Internet, pero los archivos del mapa tienen su propio socket y límites.
El auxiliar no genera terreno, no ejecuta comandos enviados por el host y no
requiere copiar la caché de 40 GB al jugador.

## Host

Preparar un certificado TLS válido para el nombre del host y su clave privada.
Para pruebas privadas puede usarse una CA propia que se entregue explícitamente
a los jugadores; no hay una opción de omitir la verificación del certificado.
No se ha emitido/instalado un certificado para tu red ni modificado router/firewall.

```powershell
python tools/start_beammp_world.py --beammp-dir "C:\BeamMP-Test" --public-host earth.example.org --listen 0.0.0.0 --tls-cert "C:\certs\fullchain.pem" --tls-key "C:\certs\privatekey.pem"
```

Sustituir dominio y rutas. El puerto TCP Earth es 47613 por defecto y debe ser
alcanzable además de los puertos habituales de BeamMP. La clave privada permanece
en el host. El archivo privado `EarthSync.runtime.json` anuncia `clientBridge: true`;
el mod de alpha.3 pasa entonces a `127.0.0.1:47614`.

## Jugador

Ejecutable Windows de 64 bits, compilado localmente y sin firma digital:

```powershell
.\EarthClientBridge.exe --host earth.example.org --port 47613
```

Dejarlo abierto y entrar por BeamMP al servidor. Para una CA privada añadir
`--ca-file "C:\certs\earth-ca.pem"`. El nombre/IP debe corresponder al certificado.
El servicio escucha sólo en loopback y permite hasta dos conexiones locales para
reconexiones; el límite del generador sigue siendo ocho. El puerto local del mod
está fijado en 47614; no cambiar `--local-port` al usar el mod sin modificaciones.

Alternativa con Python 3.10+ instalado, sin paquetes de terceros:

```powershell
python tools/earth_client_bridge.py --host earth.example.org --port 47613
```

Para reconstruir el EXE desde el código en Windows:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --onefile --console --name EarthClientBridge tools/earth_client_bridge.py
```

El token se transmite dentro del protocolo Earth; no se pide en argumentos ni
se escribe en logs del auxiliar. TLS autentica al host y cifra ese segundo canal.

## Validación

Las pruebas automatizadas ejecutan una conexión TCP local real al auxiliar,
una conexión TLS real al servicio headless, el handshake Earth y un roundtrip
binario de 1 MiB. También comprueban que un certificado no confiable se rechaza.
No son pruebas de Internet real, FPS ni colisiones de dos/ocho juegos abiertos.
