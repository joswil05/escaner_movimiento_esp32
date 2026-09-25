# Escáner de movimiento WiFi con ESP32 (CSI)

Detección de movimiento humano usando el Channel State Information (CSI) del WiFi, sin cámara ni PIR, con dos ESP32 y un router.

## Documentación
- [docs/ESTADO.md](docs/ESTADO.md): **estado actual y qué falta** (empezar por aquí).
- [docs/investigacion.md](docs/investigacion.md): proyectos y herramientas externas para detección y ubicación.
- [docs/PLAN.md](docs/PLAN.md): alcance, stack, arquitectura, fases y catálogo de funcionalidades.
- [docs/guia_flashear_placa_b.md](docs/guia_flashear_placa_b.md): programar la ESP32 sin USB usando la otra placa como puente.
- [docs/guia_fase0_csi.md](docs/guia_fase0_csi.md): ver CSI real en vivo (firmware + visor).
- [docs/guia_fase1.md](docs/guia_fase1.md): transmisor dedicado, receptor binario y grabaciones etiquetadas.
- [docs/guia_fase2.md](docs/guia_fase2.md): detector de movimiento (visor en vivo y evaluación con métricas).
- [docs/guia_fase3.md](docs/guia_fase3.md): el detector corriendo dentro de la ESP32.
- [docs/experimentos.md](docs/experimentos.md): bitácora de experimentos y resultados.

## Contenido
| Carpeta | Qué es |
|---|---|
| `firmware/blink` | Prueba de flasheo: LED + info del chip por serial |
| `firmware/csi_router_test` | Fase 0: la placa hace ping al router y envía el CSI por serial (texto `CSI_DATA`) |
| `firmware/tx` | Transmisor (placa B): beacons ESP-NOW a 100 Hz, actualización OTA por WiFi con rollback |
| `firmware/rx` | Receptor (placa A): CSI del transmisor o del router → PC en tramas binarias con CRC, más el detector de movimiento en la placa y una página web (estado, mapa de actividad, ajustes) |
| `firmware/components` | `csi_proto` (protocolo compartido), `csi_wifi` (conexión WiFi) y `csi_dsp` (detector en C) |
| `host/` | Python: `apps/live_view.py` (ver, grabar, etiquetar, detector en vivo), `apps/link_stats.py`, `apps/evaluate.py` (métricas del detector), `csi_tools/` |

Estado: fase 0 completa; fase 1 con el enlace TX→RX validado (faltan los experimentos a distancia); fase 2 con el detector listo, pendiente de ajustar con datos etiquetados; fase 3 con el detector y la página web (incluido el mapa de actividad) corriendo en la ESP32, pendiente de probar en la placa (~38 % del total).
