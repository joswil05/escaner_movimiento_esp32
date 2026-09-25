# Bitácora de experimentos

## E0-1 — Primera captura en modo router (fase 0)

- **Fecha:** 2026-09-24
- **Montaje:** placa A con `firmware/csi_router_test` (ping al router a 100 Hz, solo LLTF, `WIFI_PS_NONE`), router Kaon en canal 1 / 20 MHz. **Protocolo real (según el usuario):** no se siguió el 30/30/30. El usuario, sentado junto a la laptop, alternó ratos quieto con ratos **moviendo los brazos**, mirando el visor en tiempo real. No hubo caminatas.
- **Datos:** `data/samples/fase0_prueba1.csv` (76.6 s, 7695 paquetes CSI, 76 líneas `CSI_STATS`).

### Resultados

| Métrica | Valor | Lectura |
|---|---|---|
| Tasa media en la PC | **100.4 paquetes/s** | El router responde bien a 100 pings/s ✅ |
| Intervalo entre paquetes (reloj de la ESP32) | mediana 10.0 ms, p5 2.1 ms, p95 14.3 ms, máx. 1010 ms | Hay **ráfagas** (respuestas que llegan juntas) y algún hueco de ~1 s |
| `CSI_STATS` recibidos/s | normalmente 100–102; mín. 18, máx. 181 | Los huecos se compensan con ráfagas: jitter del router |
| Descartados en la ESP32 (cola llena) | 36 en total (0.5 %) | Coinciden con las ráfagas; aceptable, se revisa en el firmware RX de la fase 1 |
| Líneas perdidas/malas en el serial | 0 malas; 36 saltos de `id` = los mismos descartes | El enlace serial a 921600 baudios alcanza ✅ |
| Modulación | 100 % `sig_mode=1` (HT, 802.11n), `rate=11`, 128 bytes de CSI | Formato estable ✅ |
| `first_word_invalid` | **activo en el 100 % de los paquetes** | Las subportadoras 0 y **+1** son inválidas → se usan 51 útiles (explica la "línea oscura" del visor) |
| RSSI | −50 a −55 dBm | Señal buena |
| Perfil de amplitud | Valles profundos en −22, −6 y +10 | Desvanecimiento selectivo por multitrayecto; normal en interiores |

**Índice de movimiento** (desviación estándar temporal media, amplitud normalizada, ventanas de 1 s):

- Tramos tranquilos: ~0.05–0.06; el más quieto (27–30 s): **~0.03**.
- Tramos con actividad (7–26 s y 31–59 s, movimiento de brazos): **~0.08–0.14**.
- Separación de ~2× entre quietud y movimiento **de brazos**. Es un movimiento pequeño (escenario S3), así que es un buen punto de partida. Una caminata entre placa y router (S1) debería separarse bastante más.
- La "quietud" de ~0.05–0.06 frente a los ~0.03 de 27–30 s sugiere microgestos (teclado, mouse, postura) en los tramos considerados quietos: con la persona pegada al montaje, la quietud total casi no existe.

### Conclusiones y siguientes pasos

1. El modo router es viable como respaldo: tasa media correcta, pero con jitter y ráfagas. El transmisor dedicado (fase 1) debería dar intervalos más regulares; hay que compararlo con estas mismas métricas.
2. Descartar la subportadora +1 (y la 0) siempre en la ESP32 clásica. Ya está hecho en `csi_tools`.
3. El índice simple distingue movimiento de quietud, pero con poco margen. En la fase 2 se prueban el filtro Hampel, la correlación entre paquetes (C) y la energía por bandas. Para evaluarlos hacen falta etiquetas precisas: el grabador de la fase 1 permitirá marcar con el teclado cuándo empieza y termina cada movimiento.
4. Próxima grabación: con etiquetas por teclado, incluir S0 (cuarto vacío, sin la persona cerca), S1 (caminar entre placa y transmisor) y S3 (brazos), para medir la separación en cada caso.

## E1-0: Alimentación del transmisor (placa B)

- **Fecha:** 2026-09-25
- **Síntoma:** con `firmware/tx` cargado y alimentada **por su conector USB** con un cargador de celular, la placa B entra en bucle: LED rojo encendido, LED azul parpadeando rápido y, a los pocos segundos, **los dos LEDs se apagan** y vuelve a arrancar.
- **Diagnóstico:** alimentada por el **pin VIN** desde la placa A (conectada a la laptop), con `EN→GND` en la placa A, funciona bien: se conecta al WiFi y envía beacons.
- **Conclusión:** el ESP32 de la placa B está sano. El blink (~50 mA) funcionaba porque apenas consume; con WiFi (picos de 400–500 mA) la entrada USB no aguanta. Lo más probable es un diodo de entrada dañado junto al chip USB quemado, o un cargador o cable débil (pendiente de confirmar probando ese cargador con la placa A).
- **Solución:** alimentar la placa B **por VIN** (5 V) y GND, sin pasar por su conector USB: cable USB cortado o adaptador USB a pines, con cargador o power bank. Nunca 5 V en el pin 3V3.

## E1-1: Primer enlace TX → RX (placas juntas)

- **Fecha:** 2026-09-25
- **Montaje:** placas A y B a pocos centímetros; B alimentada por VIN desde A; A por USB a la laptop. `firmware/rx` en modo transmisor, `firmware/tx` v1.0.0.
- **Resultado (captura del visor, ~37 s):** ✅ el enlace funciona.

| Métrica | Valor | Lectura |
|---|---|---|
| Paquetes/s en la PC | ~99–100, **curva plana** | Mucho más regular que el modo router (E0-1, con ráfagas y huecos) |
| Descartados en el RX | 0 | La cola y el envío binario alcanzan |
| Perdidos en el aire | 92 de ~3700 (**~2.5 %**) | Los broadcast ESP-NOW no tienen reintentos: colisionan con el tráfico del canal 1. Aceptable; volver a medir a 3–4 m |
| RSSI | −43 a −50 dBm | Normal a esta distancia (depende de la orientación de las antenas) |
| TX | IP 192.168.1.30, `tx-1.0.0` | La información del transmisor llega por los beacons |
| Índice de movimiento | ~0.03–0.05 en calma; picos de 0.12 y 0.21 | Responde a movimientos cercanos |

**Pendiente:** alimentación propia para B y los experimentos 1–3 de `guia_fase1.md` a 3–4 m.
