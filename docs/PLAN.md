# Escáner de movimiento WiFi con ESP32 (CSI): plan del proyecto

> Estado: **v2, alcance cerrado**. Este documento define el alcance, el stack, la arquitectura y el orden de trabajo.
> Código existente: solo `firmware/blink` (prueba de flasheo de la placa B, ver `docs/guia_flashear_placa_b.md`).
>
> **Entorno confirmado:** Windows, ESP-IDF **v5.3.1** (Espressif-IDE + terminal "ESP-IDF 5.3 CMD"), placas ESP32 DevKit V1 de 30 pines (LED en GPIO2).
> **Placa B rescatada:** se flasheó `blink` por UART usando la placa A como puente; el LED parpadea. ✅
> Tipo de proyecto: personal, sin fecha límite. Se avanza por hitos, cada uno con un criterio de "terminado" verificable.

---

## 1. Objetivo

Detectar movimiento humano en una habitación usando el **CSI (Channel State Information)** del WiFi, sin cámara ni sensor PIR, con dos ESP32 clásicas y un router doméstico.

**Resultado mínimo (MVP):** la ESP32 receptora, alimentada por un cargador USB y sin PC, decide sola "hay movimiento / no hay movimiento" y lo muestra en vivo en una página web que se abre desde el celular. Además, se sabe cuántas falsas alarmas por hora tiene, porque se midió.

**Resultado completo:** el MVP más las extensiones E1–E7 (sección 6): índice de actividad con historial, integración con Home Assistant, streaming por WiFi, clasificador de actividades (en PC y en la placa), rechazo de falsos positivos conocidos y, como experimento de investigación, detección de una persona quieta por su respiración.

**Fuera de alcance por decisión:** dirección entrada/salida (E8).

---

## 2. Hardware y roles

| Placa | Estado | Rol | Por qué este rol |
|---|---|---|---|
| **ESP32 A** (clásica) | USB funcionando | **Receptor (RX)** | En las fases 1 y 2 tiene que mandar ~100 paquetes CSI por segundo a la PC por USB. |
| **ESP32 B** (clásica) | Chip USB‑serial quemado | **Transmisor (TX)** | Solo necesita alimentación. Se programa **una vez** por cable (sección 2.1) y después siempre por WiFi (OTA). |
| **Router** | — | Punto de acceso. También sirve de transmisor alternativo (modo "ping") | Con él se puede empezar aunque la placa B no reviva. |

**Geometría inicial:** TX y RX separados 3–4 m, a ~1 m de altura y con línea de vista. La zona por donde camina la persona queda entre los dos. Las posiciones se anotan en cada grabación, porque moverlas cambia los datos.

### 2.1 Cómo programar la placa B sin su USB

El ESP32 trae en ROM un cargador de arranque que acepta firmware por **UART0** (GPIO1 = TX0, GPIO3 = RX0). El chip que se quemó solo traducía USB a UART, así que se reemplaza con otro traductor: **el chip USB de la placa A**. Para eso se mantiene el ESP32 de A en reset (EN a GND) y se conecta TX0→TX0 y RX0→RX0 (directo, no cruzado). Si eso no funciona, se usa un conversor CP2102/CH340 (~2–3 USD).

Procedimiento completo, con diagnóstico previo y solución de problemas: **[`guia_flashear_placa_b.md`](guia_flashear_placa_b.md)**. El firmware de prueba es `firmware/blink`.

**Clave:** el primer firmware *real* que se grabe en B (el TX de la fase 1) tiene que incluir **OTA** y una tabla de particiones con dos slots OTA. Así, después de esa única vez, todas las actualizaciones se hacen por WiFi.

---

## 3. Arquitectura

```
                        ESP-NOW broadcast, 100 Hz, tasa OFDM fija
  ┌────────────────┐  ─────────────────────────────────────────▶  ┌────────────────┐   USB serial (binario)   ┌──────────────┐
  │ ESP32 B  (TX)  │                                               │ ESP32 A  (RX)  │ ───────────────────────▶ │  PC (Python) │
  │ seq + timestamp│                                               │ CSI → detector │                          │ ver / grabar │
  └───────┬────────┘                                               └───┬───────┬────┘                          │ analizar     │
          │ WiFi STA (sigue el canal del router + OTA)                 │       │ WebSocket                     └──────────────┘
          └──────────────────────────▶ [ Router 2.4 GHz ] ◀────────────┘       ▼
                                                                          Navegador / celular
```

**Modo alternativo, una sola placa ("modo router"):** el RX le hace ping al router a 100 Hz y extrae el CSI de sus respuestas. Sirve para arrancar sin la placa B. Hay que comparar los dos modos: es el primer experimento (fase 1).

### 3.1 Firmware del receptor (RX)

| Tarea | Núcleo | Qué hace |
|---|---|---|
| Stack WiFi (IDF) | 0 | Lo gestiona el sistema. |
| **Callback CSI** | (contexto WiFi) | Filtra por MAC de origen, copia el CSI y los metadatos a un **pool de buffers fijos** y encola el índice. Si la cola está llena, suma 1 a un contador de descartes. **Nada más**: ni cálculos ni `printf`. |
| `proc` | 1 | Parsea I/Q, calcula amplitudes, normaliza, filtra, extrae features y ejecuta el detector (pipeline de la sección 3.4). |
| `out` | 1 | Manda las tramas binarias por serial a la PC. Más adelante, opcionalmente por UDP. |
| `web` | 0/1 | `esp_http_server` con WebSocket. Publica el estado y las features a 5–10 Hz. |
| `ping` | 0 | Solo en modo router: genera pings a tasa fija. |
| `hist` | 1 | *(E1)* Guarda el índice de actividad por minuto en un buffer circular (24 h = 1440 valores) y hace un volcado periódico a NVS. |
| `mqtt` | 0 | *(E2)* Publica el estado y el índice; anuncia la placa a Home Assistant con MQTT Discovery. |
| `slow` | 1 | *(E7)* Pipeline lento para la respiración: recibe muestras decimadas a 10 Hz y analiza ventanas de 30 s cada 2 s. |
| Config | — | NVS: umbrales, modo, MAC del TX, WiFi, broker MQTT, destino UDP. Se edita desde la web. |

Configuración obligatoria: `CONFIG_ESP_WIFI_CSI_ENABLED=y`, `esp_wifi_set_ps(WIFI_PS_NONE)` y ancho de banda HT20.

### 3.2 Firmware del transmisor (TX)

- Se conecta al router en modo STA. Así queda automáticamente en el mismo canal que el RX y además tiene WiFi para OTA.
- Un `esp_timer` a 100 Hz llama a `esp_now_send` en broadcast con la carga `{magic, seq, t_us}`.
- **Tasa ESP-NOW fija y OFDM** (por ejemplo MCS0 HT20). Los paquetes 802.11b (la tasa por defecto, 1 Mbps) no tienen subportadoras OFDM, así que no dan CSI útil.
- `WIFI_PS_NONE` para que la tasa de envío sea estable.
- No tiene logs por serial (la placa no tiene USB). Su salud se ve desde el RX: los números de secuencia (`seq`) revelan pérdidas y jitter. Opcionalmente también publica un "latido" por UDP.
- OTA: un endpoint HTTP para subir firmware nuevo desde la PC.

### 3.3 Protocolo RX → PC (binario)

Una trama por paquete CSI:

| Campo | Tipo | Nota |
|---|---|---|
| magic | u16 | `0xC51A`, para resincronizar el flujo |
| versión, tipo | u8, u8 | Permite cambiar el formato sin romper grabaciones viejas |
| longitud | u16 | Largo de la carga |
| seq_rx | u32 | Contador del RX: detecta tramas perdidas en el serial |
| seq_tx | u32 | Secuencia del TX: detecta paquetes perdidos por el aire |
| t_us | u64 | `esp_timer_get_time()` al recibir |
| rssi, noise_floor | i8, i8 | |
| rate, sig_mode, mcs, cwb, stbc, canal | u8 × 6 | Metadatos `rx_ctrl`; sirven para descartar paquetes con otra modulación |
| csi_len | u16 | |
| csi | i8 × csi_len | Pares (imaginario, real) tal como los entrega el chip |
| crc16 | u16 | |

Presupuesto de ancho de banda: 100 Hz × (~40 B de cabecera + 128–384 B de CSI) ≈ 17–42 KB/s. Cabe con holgura en **921600 baudios** en binario. Como texto no cabría (ocupa 3–4 veces más).

### 3.4 Procesamiento de señal

1. **Filtrar paquetes:** MAC de origen = TX (o router), misma modulación y `csi_len` esperado.
2. **Amplitud:** |H| = √(I² + Q²) por subportadora. Se descartan las de guarda, la DC y opcionalmente los pilotos; en LLTF quedan ~52 útiles. Si `first_word_invalid` está activo, se descartan los primeros 4 bytes.
3. **Normalizar por paquete (AGC):** dividir por la amplitud media del paquete. Así se elimina el efecto del control automático de ganancia. Además se evalúan las utilidades de ganancia de esp-csi.
4. **Filtro Hampel** temporal por subportadora (ventana de 5–7 muestras) para quitar picos.
5. **Features por ventana deslizante** de 1 s (100 muestras), con salto de 0.1–0.2 s:
   - **V**: varianza temporal promediada sobre subportadoras.
   - **C**: 1 − correlación media entre paquetes consecutivos. Es robusta a cambios de escala.
   - Opcional: energía en la banda de 0.3–3 Hz (movimiento humano) o la primera componente PCA.
6. **Decisión:** umbral con **histéresis** más persistencia (por ejemplo 2 de 3 ventanas), con estados `QUIETO` / `MOVIMIENTO` (el estado `PRESENCIA_QUIETA` se añade en E7, ver 3.5).
7. **Línea base adaptativa:** umbral = μ_ruido + k·σ_ruido. μ y σ se actualizan con un promedio exponencial lento **solo mientras el estado es QUIETO**. También hay un botón "recalibrar" en la web.

Los pasos 2–7 se implementan **primero en Python** (referencia) y después en **C portable** (sección 5). Ambas versiones se comparan sobre las mismas grabaciones.

### 3.5 Decisiones de diseño para que las extensiones encajen sin rehacer nada

Como E1–E7 están dentro del alcance, estas decisiones se toman desde la fase 1:

- **Vector de features único** (`csi_features_t`) calculado en `csi_dsp`: V, C, energía por bandas (0.1–0.6 Hz, 0.6–3 Hz, 3–10 Hz), media/desviación/curtosis de la amplitud, RSSI medio y tasa de paquetes. Lo usan el detector (MVP), el índice de actividad (E1), el clasificador (E4/E5) y el rechazo de falsos positivos (E6). Python y C calculan **exactamente el mismo vector**, y un test lo verifica.
- **Máquina de estados extensible:** `VACIO` → `MOVIMIENTO` → `PRESENCIA_QUIETA` (E7). El MVP usa solo los dos primeros, pero la API, la web y MQTT ya reportan el estado como texto y no como booleano.
- **Protocolo con campo `tipo`:** además de `CSI_RAW` hay tramas `FEATURES` (1 por ventana), `STATE` y `LOG`. La PC puede grabar las features calculadas por la placa y compararlas con las de Python.
- **Transporte abstracto:** en la PC, `csi_tools` lee de una "fuente" (serial, UDP o archivo). E3 solo agrega una fuente más, y `replay` reutiliza el mismo código.
- **Presupuesto de memoria** (ESP32 clásica: ~520 KB de SRAM, ~250–300 KB libres con WiFi activo):

  | Bloque | Tamaño aprox. |
  |---|---|
  | Pool de buffers CSI (32 × 400 B) | 13 KB |
  | Ventana rápida: 1 s × 100 Hz × 52 subportadoras × `int16` | 10 KB |
  | Ventana lenta E7: 30 s × 10 Hz × 52 × `int16` | 31 KB |
  | Historial E1 (1440 × 2 B) | 3 KB |
  | Modelo E5 (random forest pequeño, en flash) | < 50 KB de flash, ~0 de RAM |
  | Servidor HTTP + WebSocket + MQTT | ~40 KB |

  Total: ~100 KB, así que cabe con margen. **Regla:** nunca guardar ventanas en `float` sin decimar. 30 s a 100 Hz en `float` serían 624 KB y no caben.
- **Rendimiento:** el detector de la ventana rápida debe tardar <2 ms por salto (medido con `esp_timer`), para que el núcleo 1 quede libre para E5 y E7.

---

## 4. Stack tecnológico

| Capa | Tecnología | Notas |
|---|---|---|
| Firmware | **ESP-IDF v5.x** (el que ya tienes instalado), **C**, FreeRTOS | Hay que verificar con `idf.py --version` que la versión es compatible con esp-csi. |
| APIs de WiFi | `esp_wifi_set_csi_rx_cb`, `esp_wifi_set_csi_config`, ESP-NOW, `esp_ping` | |
| Servicios en la placa | `esp_http_server` + WebSocket, mDNS (`http://csi-radar.local`), NVS, `app_update`/OTA | Todo viene incluido en ESP-IDF. |
| Referencia | [espressif/esp-csi](https://github.com/espressif/esp-csi): ejemplos de envío/recepción y componente `esp-radar` | Se usa como punto de partida y como **línea base con la que comparar** el detector propio, no como dependencia central. |
| Algoritmo portable | `csi_dsp` en **C99 puro** (sin IDF), compilable en la PC con CMake y tests con Unity | Permite probar el detector del firmware en la PC con datos reales. |
| PC | **Python 3.11+**: pyserial, numpy, scipy, pandas, **pyqtgraph** (gráficas en vivo), matplotlib (figuras), Jupyter, pytest | pyqtgraph aguanta 100 Hz en vivo; matplotlib no. |
| ML (extensión) | scikit-learn; **emlearn** para exportar el modelo a C y correrlo en la ESP32 | emlearn es más simple que TFLite Micro para modelos de árboles. |
| Web en la ESP32 | HTML + JS vanilla, gráfica en `<canvas>`, sin librerías externas, embebida en el firmware (`EMBED_FILES`) | Pesa menos de 30 KB y funciona sin internet. |
| Datos | Grabación cruda `.bin` más un `.json` de metadatos (etiquetas, posiciones, fecha) → conversión a `.npz` | La grabación cruda permite reprocesar todo si cambia el algoritmo. |
| Integración (extensión) | MQTT (`esp-mqtt`) → Home Assistant | |
| Repo / CI | Git monorepo. GitHub Actions opcional: compilar firmware con la imagen `espressif/idf`, más pytest y tests en C | |

**Por qué no Arduino ni MicroPython:** la configuración de CSI y el menuconfig se manejan mejor en ESP-IDF, y MicroPython no alcanza para procesar 100 paquetes por segundo.

---

## 5. Estructura del repositorio

```
escaner_movimiento_esp32/
├── firmware/
│   ├── blink/               # prueba de flasheo (placa B) — ya existe
│   ├── rx/                  # proyecto ESP-IDF del receptor
│   │   └── main/web/        # index.html + app.js embebidos (EMBED_FILES)
│   ├── tx/                  # proyecto ESP-IDF del transmisor (con OTA desde v0)
│   └── components/
│       ├── csi_proto/       # formato de trama compartido RX ↔ PC
│       ├── csi_dsp/         # features + detector + respiración, en C99 puro (sin IDF)
│       │   └── test/        # tests en PC: compara con la referencia Python
│       └── csi_model/       # (E5) modelo exportado con emlearn
├── host/                    # Python
│   ├── csi_tools/           # fuentes (serial/UDP/archivo), parser, DSP de referencia, features
│   ├── apps/                # live_view.py, record.py, replay.py, evaluate.py, train.py
│   ├── notebooks/           # exploración, figuras, experimentos
│   └── tests/
├── data/                    # grabaciones (ignoradas por git salvo data/samples/)
└── docs/
    ├── PLAN.md              # este documento
    ├── guia_flashear_placa_b.md
    ├── protocolo.md         # formato de trama
    └── experimentos.md      # bitácora: qué se probó, resultados, conclusiones
```

---

## 6. Catálogo de funcionalidades

**Dificultad:** ★ trivial · ★★ fácil · ★★★ media · ★★★★ difícil · ★★★★★ nivel investigación
**Riesgo** = probabilidad de que no funcione bien aunque se implemente correctamente.

### Núcleo (MVP)

| # | Funcionalidad | Qué obtienes | Dificultad | Riesgo |
|---|---|---|---|---|
| F1 | Captura de CSI + streaming binario por serial | Datos crudos a 100 Hz en la PC | ★★ | Bajo |
| F2 | Visor en vivo (mapa de calor subportadora × tiempo, amplitud, tasa de paquetes, RSSI) | Ves cómo "tiembla" la señal al caminar | ★★ | Bajo |
| F3 | Grabador con etiquetas por teclado + metadatos | Tu propio dataset, reproducible | ★★ | Bajo |
| F4 | Enlace dedicado TX→RX por ESP-NOW + medición de pérdida y jitter | Datos más limpios y tasa controlada | ★★★ | Medio (depende de la placa B) |
| F5 | Detector de referencia en Python (varianza / correlación, Hampel, histéresis) | "Movimiento sí/no" sobre grabaciones | ★★★ | Bajo |
| F6 | Script de evaluación con métricas | % detectado, falsas alarmas/hora, latencia | ★★ | Bajo |
| F7 | Features + detector en C portable + tests contra Python | Mismo resultado en PC y en placa | ★★★ | Bajo |
| F8 | Detector en la ESP32 (tareas FreeRTOS + cola) | La placa decide sola, sin PC | ★★★ | Bajo |
| F9 | Línea base adaptativa / recalibración automática | Sobrevive a cambios lentos del ambiente | ★★★ | Medio: el ajuste fino es lo difícil |
| F10 | Página web en la ESP32 con WebSocket + config en NVS | Estado en vivo desde el celular; umbrales ajustables | ★★ | Bajo |
| F11 | OTA en ambas placas | No vuelves a cablear la placa B | ★★ | Bajo |

### Extensiones (todas dentro del alcance, salvo E8)

| # | Funcionalidad | Qué obtienes | Cómo se hace | Dificultad | Riesgo |
|---|---|---|---|---|---|
| E1 | Índice de actividad (0–100) + historial 24 h | Gráfica de "cuánto movimiento hubo" a lo largo del día, en la web | Feature V/C normalizada con la línea base, agregada por minuto en un buffer circular | ★★ | Bajo |
| E2 | MQTT → Home Assistant | Sensor de movimiento en HA: encender luces, alertas al celular | `esp-mqtt` + MQTT Discovery (`binary_sensor` movimiento, `sensor` actividad, `sensor` estado) | ★★ | Bajo |
| E3 | Streaming por WiFi (UDP) | Grabar con la placa RX lejos de la laptop, en cualquier lugar de la casa | Las mismas tramas binarias en datagramas UDP; nueva "fuente" en `csi_tools` | ★★ | Bajo (vigilar que no interfiera con la captura) |
| E4 | Clasificador de actividades en PC | Saber *qué* pasa: vacío / caminar / movimiento sentado / ventilador… | Features de la sección 3.5 → random forest (scikit-learn), validación separada por sesión | ★★★ | Medio: depende de la cantidad y variedad de datos |
| E5 | Clasificador en la ESP32 | Lo mismo sin PC, en la web y en MQTT | Exportar con emlearn a C (`csi_model`); verificar que PC y placa dan la misma predicción | ★★★★ | Medio |
| E6 | Rechazo de falsos positivos conocidos (ventilador, puerta, mascota) | Menos falsas alarmas | Ventilador: pico periódico estable en el espectro. Puerta: transitorio único y corto. Mascota: clase propia en E4. Se combinan reglas y clasificador | ★★★★ | Alto (sobre todo mascota) |
| E7 | Presencia quieta (respiración) | Distinguir "persona quieta" de "cuarto vacío"; estimar respiraciones por minuto | Ventana de 30 s decimada a 10 Hz, filtro pasa‑banda de 0.1–0.6 Hz, elegir las subportadoras más periódicas, pico espectral + autocorrelación | ★★★★★ | **Alto**: se trata como experimento con criterio de éxito propio |

### Fuera de alcance

- **E8, dirección entrada/salida:** descartada por decisión.
- **Por hardware:** localización por zonas, conteo de personas y sensado a través de varias paredes. Requieren más enlaces (≥3 placas) o antenas múltiples.

---

## 7. Fases e hitos

Cada fase termina con un **criterio verificable**. No se pasa a la siguiente sin cumplirlo. Al no haber fecha, las fases no tienen duración asignada.

### Fase 0: preparación ★
- Anotar la versión de IDF (`idf.py --version`) y el sistema operativo de la laptop.
- **Rescatar la placa B con `firmware/blink`** siguiendo `guia_flashear_placa_b.md`, y anotar su MAC.
- Configurar el router: banda de **2.4 GHz** con **canal fijo** (1, 6 u 11) y **ancho de 20 MHz**; desactivar el cambio automático de canal si se puede. Anotar su MAC.
- Compilar y flashear el ejemplo de recepción desde router de **esp-csi, tal cual**, en la placa A. Es la forma más rápida de ver CSI real antes de escribir código propio.

**Terminado cuando:** la placa B parpadea sola con un cargador (o se decidió comprar otra), la placa A imprime CSI con el ejemplo oficial y el canal del router está fijo.

### Fase 1: captura y visualización (F1–F4, F11 en TX)
- **1a. Modo router:** firmware RX propio con ping a 100 Hz, protocolo binario, `csi_proto`. En la PC: lector con "fuentes" intercambiables, `live_view.py` y `record.py`.
- **1b. Modo TX dedicado:** firmware TX con ESP-NOW y **OTA desde v0**. Se graba en la placa B por UART una última vez. El RX filtra por MAC.
- **Experimentos** (se registran en `experimentos.md`):
  1. Tasa efectiva, jitter y pérdida: modo router vs modo TX.
  2. Estabilidad con el cuarto vacío durante 10 minutos.
  3. Caminar entre las placas vs fuera de la línea directa.
  4. Distancia TX–RX: 2, 3.5 y 5 m.
- Primer dataset: ~10 sesiones de 2–5 minutos (escenarios S0–S3).

**Terminado cuando:** se mantienen ≥95 paquetes/s con <1 % de pérdida durante 10 minutos, se ve claramente la diferencia vacío/caminar en el visor, la placa B se actualiza por OTA y el primer dataset está guardado.

### Fase 2: features y detector de referencia en PC (F5, F6)
- Pipeline de la sección 3.4 y el vector de features completo de la sección 3.5, en `csi_tools`.
- `evaluate.py`: métricas por evento y por ventana.
- Comparar las features V y C con el detector de `esp-radar`.
- Elegir los parámetros (ventana, k, histéresis) con datos de *entrenamiento* y medir con datos de *prueba de otro día*.

**Terminado cuando:** se cumplen las metas de la sección 8 sobre datos de prueba que no se usaron para ajustar.

### Fase 3: detector embebido (F7–F11) → **MVP**
- **3a.** Portar las features y el detector a `csi_dsp` en C y hacer `replay`: correr las grabaciones por la versión en C en la PC. La salida debe coincidir con la de Python (dentro de una tolerancia).
- **3b.** Integrarlo en el firmware RX (tareas, cola, pool de buffers). Medir el uso de CPU, el tiempo por ventana y la memoria libre.
- **3c.** Web con WebSocket, mDNS, configuración en NVS y botón de recalibrar; OTA en el RX.
- **3d.** Prueba de resistencia: 24 h encendida sin reinicios, con conteo de falsas alarmas.

**Terminado cuando:** la placa A, alimentada por un cargador, muestra el estado en el celular, pasa la prueba de 24 h y sus métricas coinciden con las de la fase 2.

### Fase 4: conectividad y uso diario (E1, E2, E3)
- **E3 primero**, porque facilita todo lo que sigue: grabar sin la laptop al lado → más datos y más variados.
- **E1:** índice de actividad y gráfica de 24 h en la web.
- **E2:** MQTT con Discovery. Probarlo con Home Assistant (o, si no tienes HA, con Mosquitto + MQTT Explorer).

**Terminado cuando:** grabas una sesión por UDP sin perder >1 % de paquetes; la web muestra el historial del día; aparece en HA una entidad de movimiento que cambia en <2 s.

### Fase 5: aprendizaje automático (E4, E5, E6)
- **Dataset ampliado:** escenarios S0–S6 en al menos 3 días distintos, con ≥30 min por clase en total.
- **E4:** `train.py` con random forest; validación dejando un día fuera; matriz de confusión. Comparar con el detector por umbral: el clasificador tiene que justificar su complejidad.
- **E6:** medir las falsas alarmas por ventilador, puerta y mascota **antes** y **después** (reglas + clase en el clasificador).
- **E5:** exportar con emlearn y verificar en `replay` que la predicción en C = la predicción en Python. Luego medir en la placa el tiempo de inferencia y la flash usada.

**Terminado cuando:** E4 supera el 85 % de exactitud balanceada en el día de prueba; E6 reduce las falsas alarmas de S5 al menos a la mitad; E5 da las mismas predicciones que la PC en ≥99 % de las ventanas y tarda <5 ms por inferencia.

### Fase 6: investigación, presencia quieta (E7)
- Grabaciones largas de S4 (5–10 min sentado o acostado quieto, a 1–3 m de la línea TX–RX) **con referencia**: contar respiraciones a mano o con una app de respiración del celular.
- Primero en Python/notebooks: comprobar si hay un pico visible a 0.1–0.6 Hz. Probar la selección de subportadoras, PCA y la distancia a la línea directa.
- Solo si funciona en PC: portar a `csi_dsp` (pipeline lento, sección 3.5) y activar el estado `PRESENCIA_QUIETA` en la máquina de estados.

**Criterio de éxito (experimento):** a ≤2 m de la línea TX–RX, se distingue persona quieta vs cuarto vacío en ≥80 % de las ventanas de 30 s, y la frecuencia respiratoria se estima con un error ≤3 respiraciones/min. **Si no se alcanza, el resultado igual se documenta** (qué se probó y por qué no alcanzó) y el proyecto se considera completo con E1–E6.

---

## 8. Datos y evaluación

**Escenarios de grabación**

| Código | Escenario | Para qué |
|---|---|---|
| S0 | Cuarto vacío (de día, de noche, puerta cerrada) | Ruido de base y falsas alarmas |
| S1 | Caminar entre TX y RX | Caso fácil |
| S2 | Caminar fuera de la línea directa | Cobertura |
| S3 | Sentado moviendo los brazos / usando la laptop | Movimiento pequeño; clase de E4 |
| S4 | Sentado o acostado quieto (con referencia de respiraciones) | E7 |
| S5 | Perturbaciones: ventilador, puerta, mascota, alguien en el cuarto vecino | Robustez y E6 |
| S6 | Mover un mueble y dejarlo | Deriva de la línea base |

**Etiquetado:** mientras `record.py` graba, se marcan eventos con el teclado (por ejemplo `m` = empieza/termina un movimiento, `1…6` = cambio de escenario, `n` = nota libre). Todo queda en el `.json` de la sesión.

**División de datos:** por **sesión o día**, nunca por ventanas al azar. Si se mezclan ventanas de la misma sesión en entrenamiento y prueba, los resultados salen inflados.

**Métricas:**
- Detector: tasa de detección por evento, falsas alarmas por hora (S0 y S5), latencia de detección y tiempo de liberación.
- Clasificador: exactitud balanceada, matriz de confusión y F1 por clase.
- Respiración: error absoluto medio en respiraciones/min y exactitud quieto/vacío.

**Metas del MVP** (se revisan después de la fase 1): ≥95 % de caminatas detectadas, ≤1 falsa alarma por hora con el cuarto vacío, latencia <1 s.

---

## 9. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| La placa B no revive | Sin TX dedicado | Modo router (funciona con una placa) o comprar otra ESP32 (~5 USD) |
| El router limita los pings o responde irregular | Varianza falsa | Medir la tasa desde la fase 1; pasar al modo TX |
| El router cambia de canal o de ancho de banda | Se corta el flujo / cambia el formato del CSI | Canal fijo, HT20; el TX sigue al router en modo STA |
| Control automático de ganancia (AGC) | Saltos de amplitud sin movimiento | Normalizar por paquete; feature de correlación |
| Deriva del ambiente | Falsas alarmas o sordera | Línea base adaptativa; grabaciones de varios días; escenario S6 |
| Serial saturado | Paquetes perdidos | Formato binario, 921600 baudios, contadores `seq` |
| UDP/MQTT compiten con la captura por el radio | Baja la tasa de CSI | Medir la tasa con y sin E2/E3; limitar la frecuencia de publicación |
| Pocos datos para ML | El clasificador no generaliza | Grabar en varios días; validar dejando un día fuera; comparar siempre con el detector por umbral |
| E7 no alcanza el criterio | Frustración | Está planteado como experimento; el proyecto está completo sin él |

---

## 10. Preguntas abiertas

1. ~~Versión de IDF y sistema operativo~~ → v5.3.1 en Windows.
2. ~~Modelo de placa~~ → DevKit V1 de 30 pines.
3. MAC de la placa B (sale en el monitor serial de `blink`).
4. ¿Tienes acceso a la configuración del router para fijar el canal y el ancho de banda de 2.4 GHz?
5. ¿Usas Home Assistant (para E2) o lo probamos con un broker MQTT genérico?
6. ¿Tienes mascota? Define si "mascota" es una clase real en E6.
7. ¿Te sientes cómodo con Python para la parte de la PC?
