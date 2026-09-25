# Guía fase 0: ver CSI real con la placa buena

Objetivo: cargar `firmware/csi_router_test` en la **placa buena**, verla conectarse al router y ver su CSI en vivo en la laptop con el visor `host/apps/live_view.py`. Al terminar sabremos:

1. Que tu placa y tu router entregan CSI.
2. **Cuántos paquetes por segundo** responde tu router de verdad (queremos ~100).
3. Si el CSI cambia cuando alguien camina (debería).

Tiempo estimado: 30–45 minutos la primera vez.

> **Solo la placa buena, sin cables extra.** Si todavía tienes los cables del puente (sobre todo EN→GND), quítalos: con EN a GND la placa buena no arranca.

---

## Paso 1: bajar el código con Git

Usar Git en vez del ZIP tiene una ventaja: cuando haya código nuevo, lo actualizas con un solo comando.

Abre la terminal **"ESP-IDF 5.3 CMD"** y escribe:

```
cd C:\esp
git clone -b claude/esp32-csi-motion-detection-r7kbmc https://github.com/joswil05/escaner_movimiento_esp32.git
```

- Si se abre una ventana pidiendo iniciar sesión en GitHub, acepta con tu cuenta.
- Queda todo en `C:\esp\escaner_movimiento_esp32`.
- **Para actualizar en el futuro:** `cd C:\esp\escaner_movimiento_esp32` y luego `git pull`.

(Si `git` da error, baja el ZIP como la vez anterior y descomprímelo en `C:\esp\escaner_movimiento_esp32`.)

---

## Paso 2: poner los datos de tu WiFi

En la misma terminal:

```
cd C:\esp\escaner_movimiento_esp32\firmware\csi_router_test
idf.py set-target esp32
idf.py menuconfig
```

Se abre un menú azul que se maneja con el teclado:

1. Con las flechas baja hasta **`CSI router test`** y pulsa **Enter**.
2. Selecciona **`Nombre de la red WiFi (SSID)`**, pulsa Enter, borra `mi_red`, escribe el nombre exacto de tu red **de 2.4 GHz** y pulsa Enter.
3. Haz lo mismo con **`Contrasena del WiFi`**.
4. Deja **`Pings por segundo al router`** en `100`.
5. Pulsa **S** para guardar (Enter para confirmar) y luego **Q** para salir.

La contraseña queda guardada en el archivo `sdkconfig`, que git **no** sube al repositorio.

---

## Paso 3: compilar y cargar

1. Conecta la **placa buena** por USB.
2. Busca su puerto en el Administrador de dispositivos (por ejemplo `COM3`).
3. En la terminal:

```
idf.py build
idf.py -p COM3 flash monitor
```

La placa buena tiene USB sano, así que **no hace falta tocar BOOT ni EN**: entra sola en modo descarga.

### Qué debes ver en el monitor

```
I (xxx) csi_router: MAC de esta placa: XX:XX:XX:XX:XX:XX
I (xxx) csi_router: Conectando a "tu_red"...
I (xxx) csi_router: Router 98:77:e7:2d:f8:74, canal 1, RSSI -45
I (xxx) csi_router: IP 192.168.1.xx, router 192.168.1.1, ping a 100 Hz
CSI_DATA,0,98:77:e7:2d:f8:74,-45,11,1,0,0,...,128,0,"[0,0,3,-12,5,...]"
CSI_DATA,1,...
...
CSI_STATS,5012,104,0,-45
```

- Las líneas `CSI_DATA` pasan muy rápido: son ~100 por segundo, y eso es lo esperado.
- **Lo importante son las líneas `CSI_STATS`**, que salen una vez por segundo: `CSI_STATS,<tiempo_ms>,<paquetes en el último segundo>,<descartados>,<RSSI>`.
  - El **segundo número** debería rondar **100–110**. Pasa de 100 porque también cuenta los beacons del router.
  - El **tercero** (descartados) debería quedarse en **0** o subir muy poco.

Anota un par de líneas `CSI_STATS` y la línea con la **MAC de esta placa**.

Sal del monitor con **`Ctrl + ]`**. **Importante:** el monitor ocupa el puerto, así que ciérralo antes de abrir el visor.

---

## Paso 4: preparar Python (una sola vez)

Abre una **terminal normal** (CMD de Windows, **no** la de ESP-IDF) y escribe:

```
cd C:\esp\escaner_movimiento_esp32\host
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest -q tests
```

- `venv` crea un entorno aislado para el proyecto, así no se mezcla con otros programas de Python.
- Al activarlo, la línea de la terminal empieza con `(.venv)`.
- El último comando tiene que terminar con **`5 passed`**.

**Las próximas veces** solo necesitas `cd C:\esp\escaner_movimiento_esp32\host` y `.venv\Scripts\activate`.

> Si `pip install` falla con **PyQt6** (Python 3.14 es muy nuevo): instala **Python 3.12** desde python.org (marca "Add to PATH"), borra la carpeta `.venv` y créala de nuevo con `py -3.12 -m venv .venv`.

---

## Paso 5: ver el CSI en vivo

Con el entorno activado:

```
python apps\live_view.py --port COM3
```

Se abre una ventana con tres gráficas:

| Gráfica | Qué muestra | Qué esperar |
|---|---|---|
| **Mapa de calor** | Cada fila es una subportadora (−26 a +26) y cada columna un paquete; el color es la amplitud | Quieto: franjas horizontales parejas. Caminando: la imagen "se revuelve" |
| **Índice de movimiento** | Cuánto varía la señal en el último segundo | Bajo y plano en quietud; sube cuando alguien se mueve |
| **Paquetes/s y RSSI** | Tasa real de CSI (amarillo) e intensidad de señal (celeste) | Amarillo estable cerca de 100 |

En la barra de abajo verás los números exactos.

### El experimento

1. **Ubicación:** la placa a unos **3–4 m del router**, idealmente a la misma altura (~1 m) y con el espacio entre ambos libre para caminar. La placa va con el cable USB a la laptop, así que acércala a ella: una extensión USB ayuda.
2. **Graba una sesión:**
   ```
   python apps\live_view.py --port COM3 --record ..\data\fase0_prueba1.csv
   ```
   (La carpeta `data` se crea sola; git no la sube al repositorio.)
3. **30 s de quietud:** quédate inmóvil y lejos de la línea placa–router. Si puedes, sal del cuarto. Que la mascota tampoco esté cerca.
4. **30 s caminando** de un lado a otro **entre la placa y el router**.
5. **30 s de quietud** otra vez.
6. Cierra la ventana: la grabación se guarda sola.

Para volver a ver la grabación sin la placa:
```
python apps\live_view.py --replay ..\data\fase0_prueba1.csv
```

### Qué mandarme

- Una **captura del visor** mientras caminas o justo después (que se vean quietud y movimiento en el índice).
- Dos o tres líneas **`CSI_STATS`** del monitor.
- La **MAC de la placa buena**.
- El archivo `fase0_prueba1.csv`, si puedes. Me sirve para ajustar el procesamiento a tus datos reales.

---

## Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Se queda en `Conectando a "..."` o repite `WiFi desconectado` | SSID o contraseña mal escritos, o la red es solo de 5 GHz | Repite `idf.py menuconfig`, revisa mayúsculas y espacios; usa la red de 2.4 GHz |
| `CSI_STATS` muestra mucho menos de 100 paquetes/s (por ejemplo 20–50) | El router limita o retrasa las respuestas al ping | Anótalo: es justo lo que queremos medir. La solución es el transmisor dedicado (fase 1) |
| El segundo número de `CSI_STATS` salta mucho (por ejemplo 40 → 110 → 60) | Interferencia o router ocupado | Anótalo y prueba a otra hora; en fase 1 lo comparamos con el transmisor dedicado |
| El visor dice `could not open port` o `Access is denied` | El monitor de IDF sigue abierto | Cierra el monitor (`Ctrl + ]`) u otra ventana que use el COM |
| `líneas malas` sube rápido en el visor | Velocidad del puerto incorrecta o cable malo | Revisa que el visor use 921600 (es el valor por defecto) y prueba otro cable USB |
| El monitor muestra caracteres raros al arrancar | Normal: el arranque de la ROM sale a otra velocidad | Ignóralo; lo que sigue debe verse bien |
| `Guru Meditation Error` o reinicios | Error del firmware o alimentación débil | Copia el texto completo del error y mándamelo |
