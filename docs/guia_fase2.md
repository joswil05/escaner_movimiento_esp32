# Guía fase 2: detector de movimiento en la PC

El visor ya incluye el **detector**: además de las gráficas, decide en vivo **QUIETO / MOVIMIENTO**.

## Cómo funciona

1. **Preprocesado por paquete:** amplitud de las 51 subportadoras útiles, dividida por su media (así se cancela la ganancia automática del chip).
2. **Filtro Hampel** en el tiempo, por subportadora: reemplaza picos sueltos por la mediana de sus 7 vecinos.
3. **Features** de la última ventana de 1 s, recalculadas cada 0.2 s (`host/csi_tools/dsp.py`):

   | Feature | Qué mide |
   |---|---|
   | `variance` (V) | Cuánto varía cada subportadora en el tiempo (promedio). Es el índice de la fase 0, ahora con Hampel |
   | `decorrelation` (C) | 1 − correlación entre paquetes consecutivos: cuánto cambia la "forma" del canal |
   | `band_1_3`, `band_3_10`, `band_10_40` | Reparto de la energía por velocidad del cambio (Hz). Servirán para el clasificador |
   | `rssi_mean`, `rssi_std`, `rate_hz` | Calidad del enlace |

4. **Decisión** (`host/csi_tools/detector.py`):
   - **Calibración:** los primeros ~5 s fijan la línea base. **Quédate quieto o sal del cuarto** mientras el cartel dice `CALIBRANDO`.
   - **Umbral de activación** (línea roja punteada) = línea base + 6 σ, y como mínimo 1.6 veces la línea base.
   - **Umbral de liberación** (verde) = línea base + 3 σ, y como mínimo 1.3 veces la línea base.
   - **Histéresis y persistencia:** pasa a MOVIMIENTO tras 2 ventanas seguidas (0.4 s) sobre el umbral rojo, y vuelve a QUIETO tras 5 ventanas (1 s) bajo el verde.
   - **Recalibración automática:** mientras está QUIETO y el índice queda bajo la línea verde, la línea base se ajusta lentamente (~70 s) a los cambios del ambiente.
   - **Tecla `R`:** recalibrar a mano (por ejemplo, después de mover un mueble). Quédate quieto 5 s.

## En el visor

- **Cartel de estado** arriba a la izquierda: verde `QUIETO`, rojo `● MOVIMIENTO`, amarillo `CALIBRANDO… quieto`.
- **Gráfica del detector:** el índice en naranja, los dos umbrales punteados y los tramos en MOVIMIENTO sombreados en rojo. Las etiquetas del teclado se dibujan encima, así se compara lo que marcaste con lo que decidió el detector.

## Medir qué tan bien funciona

Con grabaciones **etiquetadas** (las de la fase 1):

```
python apps\evaluate.py ..\data\e1_tx.csirec ..\data\e3_vacio_10min.csirec
```

Muestra por archivo y en total:
- **% de movimientos detectados**: los marcados con `Espacio`.
- **Latencia**: cuánto tarda en detectar desde que marcaste el inicio.
- **Falsas alarmas por hora**: en tiempo tranquilo (escenarios S0 y S4), fuera de los movimientos marcados.

Para probar otros umbrales y la feature C:

```
python apps\evaluate.py ..\data\*.csirec --sweep
```

Prueba 54 combinaciones y muestra las mejores, ordenadas por: detectar casi todo → menos falsas alarmas → menor latencia.

Con grabaciones **sin etiquetas** (por ejemplo, la de la fase 0) muestra una línea de tiempo:

```
python apps\evaluate.py ..\data\samples\fase0_prueba1.csv
  ccccc..#######.#####................#####...###....##########...............
```

(`c` calibrando, `#` movimiento, `.` quieto; 1 carácter = 1 s.)

## Metas (sección 8 del plan)

≥ 95 % de caminatas detectadas, ≤ 1 falsa alarma por hora con el cuarto vacío, latencia < 1 s. Los umbrales por defecto son un punto de partida razonable. Se ajustarán con `--sweep` usando grabaciones de **un día** y se verificarán con grabaciones de **otro día**.
