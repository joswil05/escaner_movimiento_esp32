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
