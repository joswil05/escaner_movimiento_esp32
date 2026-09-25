# Escáner de movimiento WiFi con ESP32 (CSI)

Detección de movimiento humano usando el Channel State Information (CSI) del WiFi, sin cámara ni PIR, con dos ESP32 y un router.

## Documentación
- [docs/PLAN.md](docs/PLAN.md): alcance, stack, arquitectura, fases y catálogo de funcionalidades.
- [docs/guia_flashear_placa_b.md](docs/guia_flashear_placa_b.md): programar la ESP32 sin USB usando la otra placa como puente.
- [docs/guia_fase0_csi.md](docs/guia_fase0_csi.md): ver CSI real en vivo (firmware + visor).

## Contenido
| Carpeta | Qué es |
|---|---|
| `firmware/blink` | Prueba de flasheo: LED + info del chip por serial |
| `firmware/csi_router_test` | Fase 0: la placa hace ping al router y envía el CSI por serial (texto `CSI_DATA`) |
| `host/` | Herramientas de PC en Python: `apps/live_view.py` (ver, grabar, reproducir) y `csi_tools/` (parser y cálculos) |

Estado: fase 0 (preparación): placa B rescatada, router configurado; falta ver el CSI real.
