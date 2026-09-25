# Escáner de movimiento WiFi con ESP32 (CSI): plan del proyecto

> Estado: **borrador v1**. Todavía no hay código. Este documento define el alcance, el stack y el orden de trabajo.
> Tipo de proyecto: personal, sin fecha límite. Se avanza por hitos, cada uno con un criterio de "terminado" verificable.

---

## 1. Objetivo

Detectar movimiento humano en una habitación usando el **CSI (Channel State Information)** del WiFi, sin cámara ni sensor PIR, con dos ESP32 clásicas y un router doméstico.

**Resultado mínimo (MVP):** la ESP32 receptora, alimentada por un cargador USB y sin PC, decide sola "hay movimiento / no hay movimiento" y lo muestra en vivo en una página web que se abre desde el celular. Además, se sabe cuántas falsas alarmas por hora tiene, porque se midió.

Todo lo que va más allá del MVP (clasificar actividades, detectar a una persona quieta, domótica) es una **extensión opcional**. La sección 6 las lista con su dificultad.

---

## 2. Hardware y roles

| Placa | Estado | Rol | Por qué este rol |
|---|---|---|---|
| **ESP32 A** (clásica) | USB funcionando | **Receptor (RX)** | En las fases 1 y 2 tiene que mandar ~100 paquetes CSI por segundo a la PC por USB. |
| **ESP32 B** (clásica) | Chip USB‑serial quemado | **Transmisor (TX)** | Solo necesita alimentación. Se programa **una vez** por cable (sección 2.1) y después siempre por WiFi (OTA). |
| **Router** | — | Punto de acceso. También sirve de transmisor alternativo (modo "ping") | Con él se puede empezar aunque la placa B no reviva. |

**Geometría inicial:** TX y RX separados 3–4 m, a ~1 m de altura y con línea de vista. La zona por donde camina la persona queda entre los dos. Las posiciones se anotan en cada grabación, porque moverlas cambia los datos.

### 2.1 Cómo programar la placa B sin su USB

El ESP32 tiene un cargador de arranque (bootloader) grabado en ROM que acepta firmware por **UART0** (GPIO1 = TX0, GPIO3 = RX0). El chip USB que se quemó solo convierte USB a UART, así que se puede reemplazar con otro conversor.

**Paso 0: diagnóstico (antes de conectar nada a otra placa)**
- Alimenta la placa B por su USB con un cargador de celular, o por el pin 5V/VIN. ¿Enciende el LED de power?
- Con un multímetro, mide el pin 3V3: tiene que marcar ~3.3 V.
- Si algo se calienta o el 3V3 está en 0 V, desconecta. Puede que el daño alcance al regulador o a la línea de 5 V. En ese caso conviene comprar otra ESP32 (~5 USD) y seguir en modo router mientras llega.

**Opción A: usar la placa A como puente (no hay que comprar nada)**

| Placa A (buena) | Placa B (dañada) |
|---|---|
| EN → **GND** (mantiene el ESP32 de A en reset, así su chip USB queda libre) | — |
| TX0 | **TX0** (directo, *no* cruzado) |
| RX0 | **RX0** (directo, *no* cruzado) |
| GND | GND |
| 5V/VIN | 5V/VIN (A alimenta a B) |

Los cables van directos (TX con TX) porque en el header de la placa A el pin "TX0" está conectado a la entrada RX del chip USB de A.

**Opción B: conversor USB‑UART de 3.3 V** (CP2102, CH340 o FT232, ~2–3 USD)
Adaptador TX → RX0 de B, adaptador RX → TX0 de B, GND con GND, 5V con VIN. Aquí los cables sí van cruzados.

**Modo descarga (en ambas opciones):** no hay reinicio automático porque DTR/RTS no están conectados. Mantén presionado **BOOT** (GPIO0 a GND), pulsa y suelta **EN**, y luego suelta BOOT. Después:

```
idf.py -p <PUERTO> -b 115200 flash
```

Al terminar, pulsa EN para que arranque.

**Posible problema:** si el chip quemado quedó en corto sobre las líneas TX0/RX0, puede impedir que el puente las maneje. En ese caso hay que desoldar el chip o las resistencias que lo unen a GPIO1/GPIO3.

**Clave:** el primer firmware que se grabe en B tiene que incluir **OTA** y una tabla de particiones con dos slots OTA. Así, después de esa única vez, todas las actualizaciones se hacen por WiFi y no hay que volver a cablear.

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
| Config | — | NVS: umbrales, modo, MAC del TX, WiFi. Se edita desde la web. |

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
6. **Decisión:** umbral con **histéresis** más persistencia (por ejemplo 2 de 3 ventanas), con estados `QUIETO` / `MOVIMIENTO`.
7. **Línea base adaptativa:** umbral = μ_ruido + k·σ_ruido. μ y σ se actualizan con un promedio exponencial lento **solo mientras el estado es QUIETO**. También hay un botón "recalibrar" en la web.

Los pasos 2–7 se implementan **primero en Python** (referencia) y después en **C portable** (sección 5). Ambas versiones se comparan sobre las mismas grabaciones.

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
│   ├── rx/                  # proyecto ESP-IDF del receptor
│   ├── tx/                  # proyecto ESP-IDF del transmisor (con OTA desde v0)
│   └── components/
│       ├── csi_proto/       # formato de trama compartido RX ↔ PC
│       └── csi_dsp/         # detector en C puro (sin dependencias de IDF)
│           └── test/        # tests en PC: compara con la referencia Python
├── host/                    # Python
│   ├── csi_tools/           # lector serial, parser, carga de grabaciones, DSP de referencia
│   ├── apps/                # live_view.py, record.py, replay.py, evaluate.py
│   ├── notebooks/           # exploración y figuras
│   └── tests/
├── data/                    # grabaciones (ignoradas por git salvo muestras pequeñas)
└── docs/
    ├── PLAN.md              # este documento
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
| F2 | Visor en vivo (mapa de calor subportadora × tiempo, amplitud, tasa de paquetes, RSSI) | Ves literalmente cómo "tiembla" la señal al caminar | ★★ | Bajo |
| F3 | Grabador con etiquetas por teclado + metadatos | Tu propio dataset, reproducible | ★★ | Bajo |
| F4 | Enlace dedicado TX→RX por ESP-NOW + medición de pérdida y jitter | Datos más limpios y tasa controlada | ★★★ | Medio (depende de revivir la placa B) |
| F5 | Detector de referencia en Python (varianza / correlación, Hampel, histéresis) | "Movimiento sí/no" sobre grabaciones | ★★★ | Bajo |
| F6 | Script de evaluación con métricas | Números reales: % detectado, falsas alarmas/hora, latencia | ★★ | Bajo |
| F7 | Detector en C portable + tests contra Python | Mismo resultado en PC y en placa | ★★★ | Bajo |
| F8 | Detector en la ESP32 (tareas FreeRTOS + cola) | La placa decide sola, sin PC | ★★★ | Bajo |
| F9 | Línea base adaptativa / recalibración automática | Sobrevive a cambios lentos del ambiente | ★★★ | **Medio**: el ajuste fino es lo difícil |
| F10 | Página web en la ESP32 con WebSocket + config en NVS | Estado en vivo desde el celular; umbrales ajustables | ★★ | Bajo |
| F11 | OTA en ambas placas | No vuelves a cablear la placa B | ★★ | Bajo |

### Extensiones (se eligen después del MVP)

| # | Funcionalidad | Qué obtienes | Dificultad | Riesgo |
|---|---|---|---|---|
| E1 | Índice de actividad continuo (0–100) + historial | Gráfica de "cuánto movimiento hubo" en el día | ★★ | Bajo |
| E2 | MQTT → Home Assistant / notificaciones | Encender luces o recibir alertas | ★★ | Bajo |
| E3 | Streaming por WiFi (UDP) en vez de USB | RX sin cable a la PC mientras grabas | ★★ | Bajo |
| E4 | Clasificador de actividades en PC (vacío / caminar / sentado moviéndose) con random forest | Más que sí/no: *qué* está pasando | ★★★ | Medio: depende de la cantidad y variedad de datos |
| E5 | Ese clasificador corriendo en la ESP32 (emlearn) | Clasificación sin PC | ★★★★ | Medio |
| E6 | Detección de puerta, ventilador o mascota (rechazo de falsos positivos) | Menos falsas alarmas por causas conocidas | ★★★★ | Alto |
| E7 | **Presencia estática** (persona quieta, por respiración a 0.2–0.5 Hz) | Distinguir "persona quieta" de "cuarto vacío" | ★★★★★ | **Alto**: con una antena y un solo enlace es frágil; tómalo como experimento |
| E8 | Dirección entrada/salida | Saber si alguien entra o sale | ★★★★★ | Alto con 2 placas; necesita ≥3 |

### Fuera de alcance con el hardware actual

Localización por zonas, conteo de personas y sensado a través de varias paredes. Todas requieren más enlaces (≥3 placas) o antenas múltiples.

---

## 7. Fases e hitos

Cada fase termina con un **criterio verificable**. No se pasa a la siguiente sin cumplirlo.

### Fase 0: preparación ★
- Anotar la versión de IDF (`idf.py --version`) y el sistema operativo de la laptop.
- Configurar el router: banda de **2.4 GHz** con **canal fijo** (1, 6 u 11) y **ancho de 20 MHz**; desactivar el cambio automático de canal si se puede. Anotar su MAC.
- Compilar y flashear el ejemplo de recepción desde router de **esp-csi, tal cual**, en la placa A. Es la forma más rápida de ver CSI real antes de escribir código propio.
- Rescatar la placa B (sección 2.1) y grabarle un blink.
- Crear el esqueleto del repositorio.

**Terminado cuando:** la placa A imprime CSI con el ejemplo oficial, la placa B parpadea (o se decidió comprar otra) y el canal del router está fijo.

### Fase 1: captura y visualización (F1–F4)
- **1a. Modo router:** firmware RX propio con ping a 100 Hz, protocolo binario, `csi_proto`. En la PC: lector, `live_view.py` y `record.py`.
- **1b. Modo TX dedicado:** firmware TX con ESP-NOW y OTA desde v0, filtro por MAC en el RX.
- **Experimentos** (se registran en `experimentos.md`):
  1. Tasa efectiva, jitter y pérdida: modo router vs modo TX.
  2. Estabilidad con el cuarto vacío durante 10 minutos.
  3. Caminar entre las placas vs fuera de la línea directa.
  4. Distancia TX–RX: 2, 3.5 y 5 m.
- Primer dataset: ~10 sesiones de 2–5 minutos cada una, etiquetadas.

**Terminado cuando:** se mantienen ≥95 paquetes/s con <1 % de pérdida durante 10 minutos, se ve claramente la diferencia vacío/caminar en el visor y el primer dataset está guardado.

### Fase 2: detector de referencia en PC (F5, F6)
- Pipeline de la sección 3.4 en `csi_tools`, explorado en notebooks.
- `evaluate.py`: métricas por evento y por ventana.
- Comparar las features V y C con el detector de `esp-radar`.
- Elegir los parámetros (ventana, k, histéresis) con datos de *entrenamiento* y medir con datos de *prueba de otro día*.

**Terminado cuando:** se cumplen las metas de la sección 8 sobre datos de prueba que no se usaron para ajustar.

### Fase 3: detector embebido (F7–F11)
- **3a.** Portar el detector a `csi_dsp` en C y hacer `replay`: correr las grabaciones por el detector en C en la PC. La salida debe coincidir con la de Python (dentro de una tolerancia).
- **3b.** Integrarlo en el firmware RX (tareas, cola, pool de buffers) y medir el uso de CPU y la memoria libre.
- **3c.** Web con WebSocket, mDNS, configuración en NVS y botón de recalibrar; OTA en el RX.
- **3d.** Prueba de resistencia: 24 h encendida sin reinicios, con conteo de falsas alarmas.

**Terminado cuando:** la placa A, alimentada por un cargador, muestra el estado en el celular, pasa la prueba de 24 h y sus métricas coinciden con las de la fase 2. **= MVP.**

### Fase 4: extensiones
Se eligen del catálogo E1–E8 según el interés y lo que hayan mostrado los datos. Orden sugerido por costo/beneficio: E1 → E2 → E3 → E4 → E5. E6–E8 como experimentos.

---

## 8. Datos y evaluación

**Escenarios de grabación**

| Código | Escenario | Para qué |
|---|---|---|
| S0 | Cuarto vacío (de día, de noche, puerta cerrada) | Ruido de base y falsas alarmas |
| S1 | Caminar entre TX y RX | Caso fácil |
| S2 | Caminar fuera de la línea directa | Cobertura |
| S3 | Sentado moviendo los brazos / usando la laptop | Movimiento pequeño |
| S4 | Sentado quieto | Base para E7; el MVP *no* necesita detectarlo |
| S5 | Perturbaciones: ventilador, puerta, mascota, alguien en el cuarto vecino | Robustez |
| S6 | Mover un mueble y dejarlo | Deriva de la línea base |

**Etiquetado:** mientras `record.py` graba, se marcan eventos con el teclado (por ejemplo `m` = empieza/termina un movimiento, `n` = nota libre). Todo queda en el `.json` de la sesión.

**División de datos:** por **sesión o día**, nunca por ventanas al azar. Si se mezclan ventanas de la misma sesión en entrenamiento y prueba, los resultados salen inflados.

**Métricas:**
- Tasa de detección por evento (% de caminatas detectadas).
- Falsas alarmas por hora (en S0 y S5).
- Latencia de detección (desde el inicio del movimiento hasta el cambio de estado).
- Tiempo de liberación (desde que termina el movimiento hasta volver a QUIETO).

**Metas iniciales** (se revisan después de la fase 1): ≥95 % de caminatas detectadas, ≤1 falsa alarma por hora con el cuarto vacío, latencia <1 s.

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
| Expectativas en E7/E8 | Frustración | Tratarlas como experimentos con criterio de éxito propio |

---

## 10. Preguntas abiertas

1. ¿Qué versión de ESP-IDF tienes (`idf.py --version`)? ¿La laptop usa Windows, macOS o Linux?
2. ¿Qué modelo exacto de placa es? (DevKitC, DOIT DevKit V1, NodeMCU-32S…) ¿La placa B enciende al darle alimentación?
3. ¿Tienes acceso a la configuración del router para fijar el canal y el ancho de banda de 2.4 GHz?
4. ¿Tienes un conversor USB‑UART, o hacemos el puente con la placa A?
5. ¿Te sientes cómodo con Python para la parte de la PC?
6. ¿Qué extensiones del catálogo te interesan más para planificar el diseño con ellas en mente desde ya? (por ejemplo, si quieres E2 Home Assistant o E5 ML en la placa)
