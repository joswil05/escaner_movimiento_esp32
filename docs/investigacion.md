# Investigación: herramientas y proyectos para detección y mapeo sin más placas

Fecha: 2026-09-25. Pregunta: ¿hay software o proyectos de código abierto que permitan detectar mejor y **ubicar** el movimiento con las 2 ESP32 actuales, sin comprar más placas ni antenas?

## Respuesta corta

- **Detección:** sí. Hay proyectos maduros cuyas ideas mejoran nuestro detector. El principal es **ESPectre**.
- **Ubicación con un solo enlace y una antena:** ningún proyecto serio la logra. El único enfoque de software con resultados publicados es el de **huellas (fingerprinting) con aprendizaje automático**: se entrena por zonas del cuarto, da precisión gruesa y hay que reentrenarlo si cambia el ambiente.
- **Sin comprar nada, la vía más prometedora** es sumar enlaces con equipos que ya existen: el **router** y otros dispositivos fijos del WiFi. Luego se combina con huellas.
- **Mapeo real (x, y) de verdad** requiere otro hardware: un radar mmWave de ~10 USD, una tarjeta WiFi Intel AX210 o más ESP32.

## Proyectos revisados

| Proyecto | Qué es | ¿Ubica? | Utilidad para nosotros |
|---|---|---|---|
| **ESPectre** (francescopace/espectre, GPLv3) | Detector de movimiento maduro para ESP32 (incluida la clásica), con router + 1 placa, integración con Home Assistant | **No.** Su documentación dice explícitamente que no localiza ni cuenta personas, y su hoja de ruta habla de "vistas aproximadas de un cuarto a otro, sin afirmar localización precisa" | **Alta para la detección.** Ideas adoptables (abajo) |
| **esp-csi** (Espressif) | Ejemplos oficiales y el componente esp-radar | No con un enlace | Referencia (ya lo usamos en la fase 0) |
| **ESP32-CSI-Tool** / proyecto de jonathanmuller | Herramientas de captura, incluido el **modo pasivo/promiscuo**: CSI de tramas ajenas que se escuchan en el canal | No | Base para capturar CSI de **otros equipos** de la casa |
| **RuView / "WiFi DensePose"** (ruvnet) | Promete poses, signos vitales y "ver a través de paredes" con ESP32 | Lo afirma | **No recomendado.** Hay issues abiertos de usuarios que no obtienen resultados, críticas de que usa datos simulados, y la investigación que cita usó hardware MIMO con varias antenas, no ESP32 de una antena |
| **ESPARGOS** (Univ. de Stuttgart) | Arreglo de 8 ESP32 sincronizadas en fase: mide ángulo de llegada y "ve" el WiFi | **Sí** | Es justamente "más placas y antenas", en una placa especial y cara |
| **FeitCSI / PicoScenes** | CSI desde tarjetas **Intel AX200/AX210** (2 antenas, hasta 160 MHz) en Linux | Posible (tiempo de vuelo y ángulo) | Tu laptop usa **MediaTek MT7922**, que ninguna de las dos soporta. Haría falta cambiar la tarjeta WiFi (~20 USD) y usar Linux |
| **MtkCSIdump** | CSI en routers MediaTek con OpenWrt (MT7981) | — | No aplica: tu router es un Kaon de Claro |
| **HLK-LD2450** (radar mmWave de 24 GHz, ~7–12 USD) | Da **coordenadas x, y de hasta 3 personas** en tiempo real; componente oficial en ESPHome | **Sí**, de verdad | No es WiFi, pero se conecta a una ESP32 por UART y respeta la privacidad (sin cámara) |

## Por qué el software solo no alcanza para ubicar

Ubicar requiere separar los caminos de la señal por **distancia** (mucho ancho de banda), por **ángulo** (varias antenas) o por **varios enlaces** que crucen el cuarto. La ESP32 clásica tiene 20 MHz y una antena, y hoy tenemos un solo enlace. Los estudios con ESP32 que sí ubican usan varios enlaces: por ejemplo, un trabajo de 2026 con **3 ESP32** en un laboratorio de 6 × 4 m logra un error mediano de **0.45 m** con huellas y 35 puntos de entrenamiento.

## Qué podemos hacer sin comprar nada

### 1. Mejorar la detección con ideas de ESPectre

| Idea | Qué es | Por qué ayuda |
|---|---|---|
| **Separar las placas 3–8 m** | ESPectre recomienda 3–8 m entre el router y el sensor | Es la causa de que hoy no detecte al caminar (placas a centímetros) |
| **Capturar HT-LTF** (56 subportadoras) además de LLTF (52) | ESPectre valida su detector con HT-LTF en HT20 | Más y mejores subportadoras |
| **"Turbulencia" espacial** | Por paquete, `desvío / media` entre subportadoras; luego su autocorrelación y su rango intercuartílico en el tiempo | Inmune a la ganancia automática por construcción y más sensible a movimientos pequeños |
| **Subportadoras separadas** | 12 subportadoras espaciadas en lugar de todas | El movimiento es coherente en ~10 subportadoras vecinas, y el ruido no |
| **Persistencia por tiempo**, no por paquetes | 4 evaluaciones de 250 ms para activar y 3 para liberar | Robusto a ráfagas y pérdidas |

**Licencia:** ESPectre es GPLv3. Copiar su código obligaría a publicar el nuestro bajo GPL. Tomar las **ideas** (publicadas en su documentación y en la literatura) y escribir nuestra versión no tiene ese problema.

### 2. Más enlaces con equipos que ya existen

- **Router ↔ receptor:** el receptor le hace ping al router mientras recibe al transmisor. Es el modo router que ya existe, pero corriendo **al mismo tiempo**.
- **Router ↔ transmisor:** la placa rescatada también mide el CSI del router y envía su índice dentro de sus paquetes.
- **Otros equipos fijos** (TV, PC de escritorio, parlante inteligente, laptop quieta): en modo promiscuo, las placas pueden medir el CSI de las tramas que esos equipos envían al router, si usan 802.11n en 2.4 GHz. Esto **es una hipótesis que hay que probar** en tu red: los equipos en ahorro de energía transmiten poco e irregular.

Con 3 nodos (TX, RX, router) hay 3 enlaces en triángulo. Con cada equipo fijo que responda, se suman enlaces.

### 3. Huellas por zonas (aprendizaje automático)

Se divide el cuarto en 3–6 zonas y se graba el movimiento en cada una con el grabador etiquetado (se agregan etiquetas de zona). Luego se entrena un clasificador con las medidas de **todos** los enlaces disponibles.

- **Resultado esperado:** "hay movimiento en la zona 2", no un punto que te siga.
- **Limitación:** hay que reentrenar si se mueven muebles o placas.

## Recomendación

1. **Primero la detección:** separar las placas y adoptar las ideas de ESPectre. Es la base de todo lo demás.
2. **Después, la ubicación gruesa sin comprar nada:** enlaces extra (router + equipos fijos) y huellas por zonas. Encaja en la fase 5 (clasificador) y usa el grabador etiquetado que ya existe.
3. **Si se quiere un punto que siga a la persona (x, y):** lo más barato y confiable es un **radar HLK-LD2450** (~10 USD) conectado a una de las ESP32, combinado con el CSI. Alternativa: 2–4 ESP32 más (~5 USD c/u) para tomografía con CSI puro.

## Fuentes

- ESPectre: https://github.com/francescopace/espectre (docs/ALGORITHMS.md, docs/SETUP.md, docs/ROADMAP.md)
- esp-csi: https://github.com/espressif/esp-csi
- ESP32-CSI-Tool: https://github.com/StevenMHernandez/ESP32-CSI-Tool
- CSI en modo promiscuo (ESP32): https://github.com/jonathanmuller/ESP32-gather-channel-state-information-CSI-
- RuView: https://github.com/ruvnet/RuView, issues #37, #299, #323, #1725; análisis en TechTimes y CNX Software
- ESPARGOS: https://espargos.net/ y https://arxiv.org/pdf/2408.16377
- Localización con ESP32 por huellas (3 enlaces, 0.45 m): https://www.researchgate.net/publication/400251069
- FeitCSI: https://feitcsi.kuskosoft.com/ · PicoScenes: https://ps.zpj.io/manual/scenarios.html
- MtkCSIdump: https://github.com/MtkWifiRev/MtkCSIdump
- HLK-LD2450 en ESPHome: https://esphome.io/components/sensor/ld2450/
