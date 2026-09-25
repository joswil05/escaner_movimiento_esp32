/* Estado del receptor compartido entre la tarea de captura/detector y el servidor web. */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "csi_dsp.h"

typedef struct {
    /* detector */
    csi_state_t state;
    float score;
    float threshold_on;
    float threshold_off;
    float base;               /* línea base del detector (índice típico en calma) */
    uint16_t proc_us;
    uint32_t decisions;       /* cuántas decisiones se tomaron desde el arranque */
    csi_features_t features;
    /* enlace (se actualiza una vez por segundo) */
    uint32_t uptime_ms;
    uint16_t rx_last_s;
    uint32_t dropped_total;
    uint32_t tx_lost_total;
    int8_t rssi;
    uint8_t channel;
    uint8_t source;           /* csi_source_t */
    uint32_t free_heap;
    /* transmisor */
    bool have_tx;
    uint32_t tx_ip;
    char tx_fw[16];
} rx_status_t;

/* Copia consistente del estado actual. */
void rx_get_status(rx_status_t *out);

/* Pide recalibrar el detector (se aplica en la tarea del detector). */
void rx_request_recalibrate(void);

/* Configuración del detector: lectura y cambio (el cambio se aplica en la tarea del detector y se guarda en NVS). */
void rx_get_detector_config(csi_detector_config_t *out);
bool rx_set_detector_config(const csi_detector_config_t *cfg);

/* Servidor web (web.c). */
void web_start(void);
