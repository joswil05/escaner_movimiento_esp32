# Escáner de movimiento WiFi con ESP32 (CSI)

Detección de movimiento humano usando el Channel State Information (CSI) del WiFi, sin cámara ni PIR, con dos ESP32 y un router.

## Documentación
- [docs/PLAN.md](docs/PLAN.md): alcance, stack, arquitectura, fases y catálogo de funcionalidades.
- [docs/guia_flashear_placa_b.md](docs/guia_flashear_placa_b.md): programar la ESP32 sin USB usando la otra placa como puente.
- [docs/guia_fase0_csi.md](docs/guia_fase0_csi.md): ver CSI real en vivo (firmware + visor).
- [docs/guia_fase1.md](docs/guia_fase1.md): transmisor dedicado, receptor binario y grabaciones etiquetadas.
- [docs/experimentos.md](docs/experimentos.md): bitácora de experimentos y resultados.

## Contenido
| Carpeta | Qué es |
|---|---|
| `firmware/blink` | Prueba de flasheo: LED + info del chip por serial |
| `firmware/csi_router_test` | Fase 0: la placa hace ping al router y envía el CSI por serial (texto `CSI_DATA`) |
| `firmware/tx` | Transmisor (placa B): beacons ESP-NOW a 100 Hz, actualización OTA por WiFi con rollback |
| `firmware/rx` | Receptor (placa A): CSI del transmisor o del router → PC en tramas binarias con CRC |
| `firmware/components` | `csi_proto` (protocolo compartido) y `csi_wifi` (conexión WiFi) |
| `host/` | Python: `apps/live_view.py` (ver, grabar, etiquetar, reproducir), `apps/link_stats.py` (estadísticas), `csi_tools/` |

Estado: fase 0 completa; fase 1 con firmware y herramientas listos, pendiente de validar en el hardware (~15 % del total).
