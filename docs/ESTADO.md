# Estado del proyecto (2026-09-25)

Resumen para retomar el trabajo. El detalle está en [`PLAN.md`](PLAN.md) y los resultados medidos en [`experimentos.md`](experimentos.md).

**Avance total: ~42 %**

| Fase | Avance | Estado |
|---|---|---|
| 0. Preparación | 100 % | ✅ Placa B rescatada, router con canal fijo, primer CSI grabado |
| 1. Captura y visualización | ~60 % | Enlace TX→RX funcionando; faltan los experimentos con las placas separadas |
| 2. Detector en la PC | ~60 % | Detector completo; falta ajustar umbrales con grabaciones etiquetadas |
| 3. Detector en la ESP32 (MVP) | ~65 % | Corre en la placa y coincide con la PC; faltan placas separadas y la prueba de 24 h |
| 4. Uso diario (UDP, historial, ntfy, mapa) | ~25 % | Mapa, eventos e historial de 30 min hechos; faltan ntfy, UDP e historial de 24 h |
| 5. Clasificador (con mascota) | 0 % | Necesita el dataset |
| 6. Respiración (experimento) | 0 % | Al final |

## Lo que funciona hoy (probado en tu hardware)

| Pieza | Qué hace |
|---|---|
| **Placa B (transmisor)** `firmware/tx` | 100 paquetes ESP-NOW/s, página de estado en su IP, actualización por WiFi con vuelta atrás automática. Se alimenta **por VIN** (su entrada USB no aguanta el WiFi) |
| **Placa A (receptor)** `firmware/rx` | Capta el CSI del transmisor (o del router), lo envía a la PC en binario con CRC, **detecta movimiento en la placa** y sirve la **página web** |
| **Página web** (IP de la placa A) | Estado en vivo, mapa del plano con zona sensible, editor de plano (paredes con material, muebles), eventos, historial de 30 min, umbrales |
| **Visor de PC** `host/apps/live_view.py` | Mapa de colores del CSI, detector de la PC y de la ESP32 lado a lado, grabación con etiquetas por teclado |
| **Análisis** `link_stats.py`, `evaluate.py` | Calidad del enlace; % de detección, falsas alarmas/h y latencia; barrido de umbrales |
| **Pruebas automáticas** | 22 tests, incluida la comparación del detector en C con el de Python |

Mediciones reales: ~100 paquetes/s, ~0.5 % de pérdida en el aire, 87 KB de memoria libre, detectores PC y ESP32 con el mismo índice.

## Problemas abiertos

1. **No detecta al caminar cerca con las placas juntas.** Es física, no un fallo: a centímetros, la zona sensible mide ~5 cm. Hay que separarlas 2–5 m.
2. **El mapa no muestra dónde está la persona.** Con un solo enlace no se puede. Opciones:
   - **A.** Usar el router como tercer nodo (3 enlaces en triángulo): ubicación gruesa por zonas, solo software.
   - **B.** Comprar 2–4 ESP32 más: tomografía de radio con posición de ~0.5–1 m.
3. **Tiempo de cálculo por decisión:** medía ~61 ms. Ya se desactivó la parte costosa (energía por bandas); falta verificar el valor nuevo en la placa.
4. **Espacio del firmware del receptor:** 87 % de su partición. Si crece, ampliar la partición o comprimir la página.

## Para retomar mañana

1. `git pull`, luego cargar el receptor (`firmware\rx`: `idf.py build`, `idf.py -p COM5 flash`) y mirar "Cálculo por decisión" en la web.
2. **Prueba rápida de detección a distancia usando el router:** en `menuconfig` → `CSI receptor` → *Fuente = Router (ping)*. Luego caminar entre la laptop y el router, y al terminar volver a *Transmisor dedicado*.
3. **Responder:**
   - ¿dónde está el router respecto a tu cuarto?
   - ¿te interesa comprar más placas?

   Con eso se decide cómo hacer que el mapa ubique el movimiento (opción A o B).
4. Cuando puedas: alimentación propia para la placa B (cable USB cortado → VIN/GND), separar las placas, dibujar el cuarto en el editor y grabar los experimentos de [`guia_fase1.md`](guia_fase1.md).

## Guías

| Guía | Para qué |
|---|---|
| [`guia_flashear_placa_b.md`](guia_flashear_placa_b.md) | Programar la placa sin USB usando la otra como puente |
| [`guia_fase0_csi.md`](guia_fase0_csi.md) | Primer CSI en modo router |
| [`guia_fase1.md`](guia_fase1.md) | Transmisor, receptor, grabaciones etiquetadas y experimentos |
| [`guia_fase2.md`](guia_fase2.md) | Detector en la PC y evaluación |
| [`guia_fase3.md`](guia_fase3.md) | Detector en la ESP32 y página web |
