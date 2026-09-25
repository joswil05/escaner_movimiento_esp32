# Guía fase 3: el detector corriendo dentro de la ESP32

La fase 3 pasa el detector de la PC a la placa. Se hace en partes:

| Parte | Qué | Estado |
|---|---|---|
| **3a** | Detector en C (`firmware/components/csi_dsp`), comparado automáticamente con la versión de Python | ✅ Listo: da los mismos resultados con datos sintéticos y con la grabación real de la fase 0 (`host/tests/test_csi_dsp.py`) |
| **3b** | El receptor corre el detector y envía cada decisión a la PC; el visor muestra PC y ESP32 lado a lado | ✅ Firmware listo, falta probarlo en la placa (esta guía) |
| **3c** | Página web servida por la placa (laptop o celular): estado en vivo, **mapa de actividad**, gráfica del índice, recalibrar y ajustes guardados en la placa | ✅ Firmware listo, falta probarlo en la placa (sección 3c abajo) |
| 3d | Prueba de 24 h con la placa sola, alimentada por un cargador | Pendiente |

## ¿Le alcanza a la ESP32?

Sí. Cada decisión (cada 0.2 s) procesa 100 paquetes × 51 subportadoras: filtro Hampel, varianza, correlación y espectro. La placa mide el tiempo que le lleva y lo envía a la PC, así se puede verificar en vivo (se espera del orden de pocos milisegundos, frente a los 200 ms disponibles). En memoria, el detector ocupa ~61 KB.

## Probar la parte 3b

1. Baja el código y carga el receptor en la placa buena:
   ```
   cd C:\esp\escaner_movimiento_esp32
   git pull
   cd firmware\rx
   idf.py build
   idf.py -p COM5 flash
   ```
   La configuración del WiFi se mantiene (está en tu `sdkconfig`), no hace falta repetir `menuconfig`.

2. Con el transmisor encendido, abre el visor:
   ```
   cd C:\esp\escaner_movimiento_esp32\host
   .venv\Scripts\activate
   python -m pytest -q tests
   python apps\live_view.py --port COM5
   ```
   - `pytest` debe decir **`22 passed`** (o alguno `skipped` si Windows no tiene compilador de C).
   - En la terminal verás `Detector: ventana 100, decision cada 20 paquetes...` y, cada vez que cambie el estado, líneas como `Detector: MOVIMIENTO (indice 0.142, umbral 0.095, 3100 us)`.
   - El número en **us** es el tiempo que tardó la ESP32 en decidir (en microsegundos).
   - Las líneas `[stats]` ahora muestran también la **memoria libre** de la placa.

3. En el visor aparecen **dos carteles**: **`PC: …`** y **`ESP32: …`**. Los dos detectores reciben los mismos datos, así que deberían coincidir casi siempre. Puede haber diferencias de una fracción de segundo porque arrancan su calibración en momentos distintos.
   - Pasa el mouse sobre el cartel `ESP32` para ver su índice, su umbral y el tiempo de cálculo.
   - La barra de abajo muestra `detector ESP32: índice …, … ms`.

4. **Tecla `R`:** recalibra **los dos** detectores, el de la PC y el de la placa. Quédate quieto unos 5 s mientras dicen `CALIBRANDO…`.

## Medir la placa con tus grabaciones

Las grabaciones hechas con este firmware incluyen las decisiones de la ESP32. Para compararlas con las de la PC:

```
python apps\evaluate.py ..\data\e1_tx.csirec --source esp
python apps\evaluate.py ..\data\e1_tx.csirec --source pc
```

El objetivo de la fase 3 es que la placa, sola, logre las mismas métricas que la PC.

## Qué mandarme

- Una captura del visor con los dos carteles y un par de movimientos.
- Una línea de la terminal con `Detector: MOVIMIENTO (...)`, donde se ve el tiempo de cálculo.
- Una línea `[stats]` con la memoria libre.

## Parte 3c: la página web de la placa

El receptor sirve una página propia, que se abre desde **cualquier navegador conectado a tu WiFi**: la laptop, el celular o una tablet. No hace falta el visor de Python ni el cable USB (solo que la placa tenga corriente).

### Abrirla

1. Carga el receptor como en la parte 3b (`git pull`, `idf.py build`, `idf.py -p COM5 flash`).
2. En la terminal del visor, al arrancar aparece: `Pagina web: http://192.168.1.29/` (tu IP puede ser otra).
3. Abre esa dirección en el navegador de la laptop o del celular (**conectado al mismo WiFi**).

> **Consejo:** en el router Kaon, reserva esa IP para la placa (*Red → DHCP → reserva por MAC*, con la MAC `f4:2d:c9:6b:2d:20`). Así la dirección no cambia y puedes guardarla como favorito en el celular.

### Qué tiene

| Parte | Qué muestra |
|---|---|
| **Cartel de estado** | ✓ QUIETO (verde), ● MOVIMIENTO (rojo) o ◌ CALIBRANDO (amarillo). Si la placa deja de responder: "Sin conexión con la placa" |
| **Datos del enlace** | Paquetes/s, perdidos en el aire, RSSI, IP y versión del transmisor, tiempo de cálculo por decisión, memoria libre |
| **Mapa** | Tu cuarto visto desde arriba, con router, TX y RX. La **zona sensible** entre TX y RX (zonas de Fresnel, calculadas con el canal real) se colorea según la intensidad del movimiento medido. Las ondas que salen del TX son **decorativas** y se pueden apagar |
| **Índice** | Gráfica de los últimos 60 s: índice, umbrales y tramos de MOVIMIENTO. Pasa el mouse o el dedo para ver los valores |
| **Ajustes** | Medidas del cuarto y posición (en metros) de TX, RX y router; umbrales del detector. Todo se guarda **en la placa** y se mantiene tras reiniciarla |
| **Recalibrar** | Igual que la tecla `R` del visor |

### Cómo leer el mapa

- **Intensidad 0 %**: el índice está en la línea base (calma). **50 %**: justo en el umbral de activación. **100 %**: el doble o más.
- **Límite físico:** con dos placas se mide **cuánto** movimiento hay en la zona sensible, **no dónde** está la persona. La página lo dice en la leyenda. Con 4 o más placas el mismo mapa podría mostrar la zona real.
- **Cuando separes las placas**, mide el cuarto y la posición de cada equipo (desde la esquina que quieras usar como origen) y cárgalos en **Ajustes → Cuarto**.

### Estabilidad

- La página consulta el estado **4 veces por segundo** (~600 bytes cada vez). La placa capta 100 paquetes por segundo, así que es poco tráfico.
- El servidor web corre en el núcleo 0 con prioridad baja, y la captura y el detector en el núcleo 1. Si un navegador se cuelga, la detección sigue igual.
- **Verifícalo:** mira los paquetes/s y los perdidos con la página **abierta y cerrada**. No deberían cambiar.
