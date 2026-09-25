# Guía fase 1: transmisor dedicado, receptor y grabaciones etiquetadas

Al terminar esta guía tendrás:

- La **placa rescatada (B)** como **transmisor**: 100 beacons por segundo y actualizable por WiFi. **Es la última vez que la cableas.**
- La **placa buena (A)** como **receptor**: recibe esos beacons, mide el CSI y lo manda a la PC en formato binario, con control de errores.
- **Grabaciones etiquetadas** con el teclado, para comparar el transmisor con el modo router y armar el primer dataset.

Todo se hace desde `C:\esp\escaner_movimiento_esp32`. Antes de empezar, actualiza el código:

```
cd C:\esp\escaner_movimiento_esp32
git pull
```

---

## Parte A: transmisor en la placa B (por cable, una sola vez)

### A1. Configurar y compilar

En la terminal **"ESP-IDF 5.3 CMD"**:

```
cd C:\esp\escaner_movimiento_esp32\firmware\tx
idf.py set-target esp32
idf.py menuconfig
```

- Entra en **`Component config` → `CSI WiFi`** (es la **última opción** de "Component config": baja hasta el final con la tecla Fin o buscala con `/` y `CSI_WIFI_SSID`) y escribe el **nombre** y la **contraseña** de tu red de 2.4 GHz, igual que en la fase 0.
- `CSI transmisor` ya viene bien configurado (100 beacons/s, LED en GPIO2). No hace falta tocarlo.
- Pulsa **S** para guardar y **Q** para salir.

```
idf.py build
```

> **Revisa bien el nombre y la contraseña del WiFi.** Si están mal, el transmisor no se conecta y la única forma de corregirlo es volver a cablearlo.

### A2. Cargar por el puente (igual que con blink)

Sigue los pasos 3 a 5 de [`guia_flashear_placa_b.md`](guia_flashear_placa_b.md):

1. Con **todo desconectado**, pon los 5 cables del puente: **EN→GND** en la placa A, **TX0→TX0**, **RX0→RX0**, **GND→GND** y **VIN→VIN**.
2. Conecta el USB de la placa A.
3. Pon la placa B en **modo descarga**: mantén BOOT, pulsa y suelta EN, suelta BOOT.
4. Carga el firmware:
   ```
   idf.py -p COM5 -b 115200 flash
   ```
   Debe terminar en `Hash of data verified`. Esta vez también se graba una tabla de particiones nueva, con espacio para las actualizaciones por WiFi.

### A3. Dejar el transmisor funcionando

1. **Quita los 5 cables** y desconecta el USB.
2. Alimenta la placa B con un **cargador de celular**.
3. Mira el LED azul:

| LED | Significa |
|---|---|
| Parpadeo rápido (5 veces por segundo) | Conectándose al WiFi. Debe durar unos segundos |
| **Un destello corto cada segundo** | ✅ Conectado y enviando beacons |
| Parpadeo rápido por más de 1 minuto | No logra conectarse: nombre o contraseña del WiFi incorrectos. Se reinicia solo e intenta de nuevo; hay que corregirlo en `menuconfig` y volver a cablearlo |

---

## Parte B: receptor en la placa A

### B1. Configurar, compilar y cargar

Con la placa A conectada por USB (**sin** cables del puente):

```
cd C:\esp\escaner_movimiento_esp32\firmware\rx
idf.py set-target esp32
idf.py menuconfig
```

- **`Component config` → `CSI WiFi`** (la última opción de la lista): el mismo nombre y contraseña.
- **`CSI receptor`**:
  - **Fuente de CSI** = `Transmisor dedicado (ESP-NOW)`. Es la opción por defecto.
  - **MAC del transmisor** = `F4:2D:C9:6B:26:C0`. Ya viene escrita.
- **S** para guardar y **Q** para salir.

```
idf.py build
idf.py -p COM5 flash
```

Como en la fase 0, **no uses `idf.py monitor`**. Todo se ve con el visor.

### B2. Ver el CSI del transmisor

En una **terminal normal** (CMD):

```
cd C:\esp\escaner_movimiento_esp32\host
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest -q tests
python apps\live_view.py --port COM5
```

- `pytest` debe terminar en **`11 passed`** (o `10 passed, 1 skipped`, porque una prueba necesita un compilador de C que en Windows no hace falta tener).
- En la **terminal** verás:
  ```
  I (xxx) csi_rx: csi_rx, MAC de esta placa XX:XX:...
  I (xxx) csi_wifi: Conectado, IP 192.168.1.xx
  I (xxx) csi_rx: Router 98:77:e7:2d:f8:74, canal 1, RSSI -45
  I (xxx) csi_rx: Fuente: transmisor f4:2d:c9:6b:26:c0
  [stats] 100 paq/s, descartados 0, perdidos en el aire 0, RSSI -40 dBm
  ```
- En la **barra de abajo del visor** debe aparecer **`TX 192.168.1.xx (tx-1.0.0)`**. **Anota esa IP**: es la del transmisor.

Opcional: abre `http://<IP del TX>/` en el navegador de la laptop o del celular. Verás el estado del transmisor: versión, canal, beacons enviados y tiempo encendido.

---

## Parte C: actualizar el transmisor por WiFi (para el futuro)

Cuando haya una versión nueva del transmisor, ya no hace falta cablearlo:

```
cd C:\esp\escaner_movimiento_esp32\firmware\tx
idf.py build
curl -X POST --data-binary @build\csi_tx.bin http://<IP del TX>/ota
```

- Debe responder `OK: firmware recibido, reiniciando`. El LED parpadea rápido unos segundos y vuelve al destello por segundo.
- **Protección:** si la versión nueva no logra conectarse al WiFi en 60 s, la placa **vuelve sola a la versión anterior**. Así un error no te obliga a cablearla de nuevo.
- Si `curl` no se reconoce, escribe `curl.exe` (viene con Windows 10 y 11).

---

## Parte D: experimentos y primeras grabaciones etiquetadas

### Ubicación

- Transmisor y receptor a **3–4 m** de distancia, a **~1 m de altura** (sobre un mueble, por ejemplo), con el espacio entre ellos libre para caminar.
- El receptor va por USB a la laptop: ponlo cerca de ella o usa una extensión USB.
- **Anota** (o saca una foto de) dónde quedó cada cosa: transmisor, receptor, router y muebles principales. Servirá después para el mapa de actividad.
- Mientras grabas **S0 (cuarto vacío)**, la mascota debe estar fuera del cuarto.

### Cómo se etiqueta

El visor se maneja con el teclado mientras graba (con la ventana del visor seleccionada):

| Tecla | Marca |
|---|---|
| `0` … `6` | Escenario actual: **0** vacío, **1** caminar entre las placas, **2** caminar fuera de la línea, **3** brazos / sentado moviéndose, **4** quieto, **5** perturbación (ventilador, puerta, mascota), **6** mover un mueble |
| `Espacio` | Empieza / termina un movimiento |
| `N` | Escribir una nota |

Las marcas aparecen como líneas verticales en la gráfica del índice y se guardan en un `.json` junto a la grabación.

### Experimento 1: transmisor dedicado (~3 min)

```
python apps\live_view.py --port COM5 --record ..\data\e1_tx
```

1. Pulsa **`0`** y **sal del cuarto** durante **~60 s** (deja el visor grabando).
2. Vuelve, pulsa **`1`** y **`Espacio`**, y **camina** de un lado a otro entre las placas durante **~60 s**. Luego pulsa **`Espacio`**.
3. Pulsa **`3`** y **`Espacio`**, siéntate cerca y **mueve los brazos** ~30 s. Luego pulsa **`Espacio`**.
4. Cierra el visor.

### Experimento 2: el mismo, en modo router (~3 min)

Para comparar en igualdad de condiciones, sin mover nada de lugar:

1. En `firmware\rx`: `idf.py menuconfig` → `CSI receptor` → **Fuente de CSI = Router (ping)**. Guarda.
2. `idf.py build` y `idf.py -p COM5 flash`.
3. Graba igual que el experimento 1, pero con otro nombre:
   ```
   python apps\live_view.py --port COM5 --record ..\data\e1_router
   ```
4. Al terminar, **vuelve a poner la fuente en "Transmisor dedicado"** y carga de nuevo el receptor.

### Experimento 3: estabilidad con el cuarto vacío (10 min)

Con la fuente en transmisor:

```
python apps\live_view.py --port COM5 --record ..\data\e3_vacio_10min
```

Pulsa **`0`**, sal del cuarto **10 minutos** y cierra el visor al volver.

### Ver los resultados

```
python apps\link_stats.py ..\data\e1_tx.csirec ..\data\e1_router.csirec ..\data\e3_vacio_10min.csirec
```

Por cada grabación muestra: paquetes por segundo, regularidad, pérdidas en el aire, RSSI y el índice de movimiento por escenario.

### Mandarme las grabaciones

```
cd C:\esp\escaner_movimiento_esp32
copy data\e1_tx.* data\samples\
copy data\e1_router.* data\samples\
copy data\e3_vacio_10min.* data\samples\
git add data\samples
git commit -m "Fase 1: experimentos 1-3"
git push
```

Cada grabación va en **dos archivos**: `.csirec` (los datos) y `.json` (las etiquetas). Sube los dos. Pesan unos 3 MB por cada 3 minutos.

---

## Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| El LED del TX parpadea rápido sin parar | El TX no se conecta al WiFi | Revisa nombre y contraseña en `menuconfig` de `firmware\tx` y vuelve a cablearlo (parte A) |
| El visor muestra `[stats] 0 paq/s` en modo transmisor | El RX no recibe beacons | ¿El LED del TX destella una vez por segundo? ¿La MAC en `CSI receptor` es `F4:2D:C9:6B:26:C0`? ¿Los dos están conectados a la **misma** red? |
| No aparece `TX 192.168.1.xx` en la barra | Todavía no llegó la información del TX (se manda cada segundo) o no hay beacons | Espera unos segundos; si sigue igual, ver la fila anterior |
| `perdidos en el aire` crece rápido (más del 5 %) | Distancia u obstáculos entre las placas | Acércalas o despeja el camino; anota el caso en las notas (`N`) |
| `descartados` crece | El receptor no alcanza a enviar todo a la PC | Anótalo y avísame: se ajusta el tamaño de la cola |
| `tramas malas` sube en la barra | Ruido en el cable USB | Cambia el cable o el puerto USB |
| `curl` responde con error al actualizar | IP equivocada, o laptop y TX en redes distintas | Revisa la IP en la barra del visor o en `http://<IP>/` |
| El visor dice `could not open port` | Otro programa usa el COM5 | Cierra el monitor de IDF, el Espressif-IDE u otro visor |
