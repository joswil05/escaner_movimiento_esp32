# Guía: programar la ESP32 con el USB quemado (placa B)

Objetivo: cargar el firmware de prueba `firmware/blink` en la placa B usando la **placa A (sana) como puente USB‑serial**. Si funciona, verás el LED parpadear y los mensajes `tick` en el monitor. Con eso se confirma que la placa B sirve como transmisor del proyecto.

Tiempo estimado: 20–30 minutos.

---

## Qué necesitas

- Placa A (USB sano) y placa B (USB quemado).
- Cable USB de **datos** para la placa A. Algunos cables solo cargan: si la PC no detecta ningún puerto, prueba con otro.
- 5 cables dupont hembra‑hembra (o macho‑macho con una protoboard).
- Multímetro (muy recomendable).
- Opcional: un LED y una resistencia de 220 Ω, por si tu placa no trae LED de usuario.

Nombres de pines que vas a usar (vienen serigrafiados en la placa):

| Función | Serigrafía habitual |
|---|---|
| Transmisión UART0 | `TX0`, `TX`, `TXD` o `GPIO1` |
| Recepción UART0 | `RX0`, `RX`, `RXD` o `GPIO3` |
| Reset | `EN` o `RST` (y el botón `EN`/`RST`) |
| Modo descarga | botón `BOOT` o `IO0` (es el GPIO0) |
| Alimentación | `5V` o `VIN`, `3V3` y `GND` |

---

## Paso 1: diagnóstico de la placa B (sin conectarla a la placa A)

El chip que se quemó está conectado a la alimentación. Antes de unir las dos placas, confirma que la placa B no tiene un corto que pueda dañar a la placa A o al USB de tu laptop.

1. **Con todo desconectado**, pon el multímetro en modo continuidad (o resistencia) entre `5V` y `GND` de la placa B.
   - Si pita o marca menos de ~50 Ω, **hay un corto**. **No la alimentes.** Salta a la sección "Si algo falla".
   - Si marca un valor alto (kΩ) o no pita, continúa.
2. Repite la medida entre `3V3` y `GND`. Tiene que dar lo mismo: nada de corto.
3. Alimenta la placa B **sola** desde un cargador USB de celular, por su conector USB o con un cable al pin `5V`/`VIN`.
   - ¿Se enciende el LED rojo de power?
   - Mide `3V3` contra `GND`: tiene que marcar **3.2–3.4 V**.
   - Toca con cuidado el chip USB quemado (el pequeño, cerca del conector) y el regulador (componente de 3 patas, cerca de la entrada de 5 V). Si alguno **se calienta**, desconecta ya.
   - Si la placa tiene un firmware viejo que parpadea o hace algo, es buena señal: el ESP32 está vivo.
4. Desconecta la placa B.

**Si pasó todo:** continúa. **Si falló:** ve a "Si algo falla".

---

## Paso 2: preparar el proyecto en la laptop

Abre la terminal de ESP-IDF:
- **Windows:** "ESP-IDF 5.x CMD" o "ESP-IDF PowerShell", desde el menú de inicio.
- **macOS/Linux:** una terminal normal, y luego `. $HOME/esp/esp-idf/export.sh`, o la ruta donde hayas instalado IDF.

Después:

```bash
cd <ruta>/escaner_movimiento_esp32/firmware/blink
idf.py --version              # anota la versión, la necesitamos para el plan
idf.py set-target esp32
idf.py menuconfig             # opcional: "Blink de prueba" → GPIO del LED (por defecto 2)
idf.py build
```

Si `build` termina con `Project build complete`, el código está listo. Si da error, copia el mensaje completo y me lo pasas.

**Prueba de control (recomendada):** conecta **solo la placa A** por USB y flashéala normal:

```bash
idf.py -p <PUERTO> flash monitor
```

(Sal del monitor con `Ctrl+]`.) Si la placa A parpadea y muestra `tick`, sabes que el código, el cable y el puerto funcionan. Así, si después algo falla con la placa B, el problema está en la placa B o en el cableado.

**Cómo saber el `<PUERTO>`:**
- **Windows:** Administrador de dispositivos → "Puertos (COM y LPT)" → por ejemplo `COM5`. Si no aparece, instala el driver CP210x (Silicon Labs) o CH340, según el chip USB de tu placa A.
- **Linux:** `ls /dev/ttyUSB*` → `/dev/ttyUSB0`. Si da "permission denied": `sudo usermod -aG dialout $USER`, luego cierra sesión y vuelve a entrar.
- **macOS:** `ls /dev/cu.*` → `/dev/cu.usbserial-XXXX` o `/dev/cu.SLAB_USBtoUART`.

---

## Paso 3: convertir la placa A en puente USB‑serial

**Desconecta el USB de la placa A antes de cablear.**

```
        PLACA A (sana, USB a la laptop)             PLACA B (USB quemado)
        ┌─────────────┐                             ┌─────────────┐
        │         EN ─┼──┐                          │             │
        │        GND ─┼──┴──────────────────────────┼─ GND        │
        │        TX0 ─┼─────────────────────────────┼─ TX0        │
        │        RX0 ─┼─────────────────────────────┼─ RX0        │
        │     5V/VIN ─┼─────────────────────────────┼─ 5V/VIN     │
        └──────┬──────┘                             └─────────────┘
               │ USB
            laptop
```

| # | Cable | Desde (placa A) | Hasta |
|---|---|---|---|
| 1 | Negro | `GND` | `GND` de B |
| 2 | Cualquier color | `EN` | `GND` (de A o de B, da igual; usa otro pin GND o la protoboard) |
| 3 | Verde | `TX0` | **`TX0`** de B |
| 4 | Amarillo | `RX0` | **`RX0`** de B |
| 5 | Rojo | `5V`/`VIN` | `5V`/`VIN` de B |

**Por qué TX va con TX (no cruzado):** con `EN` a GND, el ESP32 de la placa A queda en reset permanente y sus pines TX0/RX0 quedan libres. Lo que "habla" por esos pines es el chip USB de la placa A, y ese chip ya está cableado de forma cruzada: su salida va al pin RX0 del header y su entrada al TX0. Por eso, desde la placa B se conecta directo.

**Si el puente no funciona**, un conversor USB‑serial CP2102 o CH340 de 3.3 V (~2–3 USD) hace lo mismo. Con él los cables **sí** se cruzan: TX del adaptador → RX0 de B, RX del adaptador → TX0 de B, más GND y 5V.

Revisa todo dos veces. Luego conecta el USB de la placa A a la laptop. El LED de power de las **dos** placas debe encenderse (la placa B recibe corriente por el cable 5).

---

## Paso 4: poner la placa B en modo descarga

Sin DTR/RTS conectados, la placa B no entra sola en modo descarga; hay que hacerlo con sus botones.

1. Mantén presionado **BOOT** en la placa B.
2. Sin soltar BOOT, pulsa y suelta **EN** de la placa B.
3. Suelta **BOOT**.

La placa B queda esperando firmware. Todavía no ves nada, es normal.

(Si la placa B no tiene botón BOOT: conecta un cable de `GPIO0` a `GND`, pulsa EN y quita el cable después de flashear.)

---

## Paso 5: flashear

En la terminal de IDF, dentro de `firmware/blink`:

```bash
idf.py -p <PUERTO> -b 115200 flash
```

- Se usa 115200 baudios (más lento) porque por cables dupont es más confiable. Tarda ~30 s.
- Si funciona, verás algo así:
  ```
  Connecting....
  Chip is ESP32-D0WD-V3 (revision v3.0)
  ...
  Writing at 0x00010000... (100 %)
  Hash of data verified.
  Hard resetting via RTS pin...
  ```
- El "Hard resetting" no llega a la placa B porque RTS no está conectado a ella. Por eso, **pulsa EN en la placa B** para que arranque el firmware nuevo.

Si se queda en `Connecting........_____....` y falla:
- Repite el paso 4 y vuelve a ejecutar el comando.
- O prueba así: mantén BOOT, ejecuta el comando y, cuando aparezca `Connecting...`, pulsa y suelta EN, y luego suelta BOOT.
- Revisa los cables TX/RX. Si ya probaste así 3 veces, prueba intercambiándolos (TX0↔RX0): no pasa nada si están al revés.

---

## Paso 6: verificar

```bash
idf.py -p <PUERTO> monitor
```

Pulsa EN en la placa B. Debes ver:

```
I (xxx) blink: Chip: ESP32 rev v3.0, 2 nucleos, flash 4 MB
I (xxx) blink: MAC WiFi STA: 24:0A:C4:XX:XX:XX
I (xxx) blink: Causa del ultimo reinicio: 1
I (xxx) blink: LED en GPIO2, periodo 500 ms
I (xxx) blink: tick 1 (heap libre: ...)
I (xxx) blink: tick 2 (heap libre: ...)
```

- **Anota la MAC**: será la MAC del transmisor en el proyecto.
- Si tu placa tiene LED en GPIO2, debe parpadear cada 0.5 s.
- Si no trae LED (por ejemplo la DevKitC), los `tick` son suficiente prueba. También puedes conectar un LED + 220 Ω entre `GPIO2` y `GND`.

Sal del monitor con `Ctrl+]`.

**Prueba final de independencia:** desconecta los 5 cables y alimenta la placa B sola con un cargador. Si el LED parpadea, la placa B funciona sin la placa A. 🎉

---

## Paso 7: dejar la placa A como estaba

Quita todos los cables. La placa A vuelve a funcionar normal: su firmware no se tocó.

---

## Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Corto entre 5V y GND en el paso 1 | El chip USB o el diodo de entrada quemado está en corto | Desoldar el chip USB quemado, o alimentar por `3V3` desde una fuente de 3.3 V externa (**nunca** 5 V en el pin 3V3). Si no, conviene comprar otra ESP32 |
| 3V3 en 0 V o algo se calienta | Regulador dañado | Igual que arriba: alimentar por 3V3 con una fuente externa, o comprar otra placa |
| `Connecting...` nunca conecta | La placa B no está en modo descarga, TX/RX mal conectados, o el chip quemado está "sujetando" las líneas TX0/RX0 | Repetir el paso 4; revisar/intercambiar TX/RX. Si el chip quemado sujeta las líneas, hay que desoldarlo o cortar las pistas/resistencias entre él y GPIO1/GPIO3 |
| `A fatal error occurred: Invalid head of packet` o errores intermitentes | Ruido en los cables | Cables más cortos, bajar a `-b 57600`, GND firme |
| Flashea bien pero el monitor no muestra nada | Faltó pulsar EN, o el monitor abrió a otra velocidad | Pulsar EN con el monitor abierto; la consola está a 115200 |
| Reinicios con `Brownout detector was triggered` | La alimentación por el cable de 5V es débil | Cable USB más corto a la placa A o alimentar B aparte (manteniendo GND común) |
| La PC no detecta ningún puerto | Cable solo de carga o falta el driver | Otro cable; instalar CP210x/CH340 |

Si nada funciona, la alternativa es seguir con **una sola placa en modo router** (el plan lo contempla) y comprar otra ESP32 para el transmisor.

---

## Qué sigue

Si esto funciona, en la fase 1 le grabaremos a la placa B (por este mismo método, **una última vez**) el firmware del transmisor con **OTA**. Desde ese momento se actualizará por WiFi y no habrá que volver a cablearla.
