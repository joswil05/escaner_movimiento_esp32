/*
 * Protocolo binario RX -> PC y beacon TX -> RX.
 *
 * Trama (little-endian):
 *   magic u16 = 0xC51A | version u8 = 1 | type u8 | len u16 | payload[len] | crc16 u16
 * El CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) cubre version, type, len y payload.
 *
 * Toda la salida del receptor va en tramas (los logs también, como CSI_FRAME_LOG), así que
 * la PC puede resincronizarse buscando el magic y descartar lo que falle el CRC.
 * El formato se replica en host/csi_tools/proto.py; cualquier cambio va en los dos lados.
 */
#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CSI_FRAME_MAGIC 0xC51Au
#define CSI_FRAME_VERSION 1u
#define CSI_FRAME_HEADER_LEN 6u
#define CSI_FRAME_OVERHEAD 8u /* cabecera + CRC */
#define CSI_FRAME_MAX_PAYLOAD 1024u

typedef enum {
    CSI_FRAME_CSI = 1,     /* csi_frame_csi_t + CSI crudo */
    CSI_FRAME_STATS = 2,   /* csi_frame_stats_t, una vez por segundo */
    CSI_FRAME_LOG = 3,     /* texto de log (ESP_LOG), sin terminador */
    CSI_FRAME_TX_INFO = 4, /* csi_frame_tx_info_t, una vez por segundo si hay transmisor */
    CSI_FRAME_DETECT = 5,  /* csi_frame_detect_t, una por decisión del detector de la ESP32 */
} csi_frame_type_t;

/* Comandos de un byte que la PC puede enviar al receptor por el mismo puerto serial. */
#define CSI_CMD_RECALIBRATE 'R'

typedef enum {
    CSI_SOURCE_ROUTER = 0, /* CSI de las respuestas del router al ping */
    CSI_SOURCE_TX = 1,     /* CSI de los beacons ESP-NOW del transmisor dedicado */
} csi_source_t;

/* Cabecera de un paquete CSI; le siguen csi_len bytes int8 (pares imaginario, real). */
typedef struct __attribute__((packed)) {
    uint32_t rx_count;     /* paquetes aceptados por el RX desde el arranque */
    uint32_t tx_seq;       /* secuencia del beacon del TX (0 en modo router) */
    uint16_t rx_seq;       /* número de secuencia 802.11 de la trama recibida */
    uint32_t local_ts;     /* rx_ctrl.timestamp, microsegundos (se desborda cada ~71 min) */
    int8_t rssi;
    int8_t noise_floor;
    uint8_t rate;
    uint8_t sig_mode;
    uint8_t mcs;
    uint8_t cwb;
    uint8_t stbc;
    uint8_t channel;
    uint8_t secondary_channel;
    uint8_t first_word_invalid;
    uint8_t mac[6];
    uint16_t csi_len;
} csi_frame_csi_t;

typedef struct __attribute__((packed)) {
    uint32_t uptime_ms;
    uint16_t rx_last_s;      /* paquetes CSI aceptados en el último segundo */
    uint16_t reserved;
    uint32_t dropped_total;  /* descartados en el RX por cola llena */
    uint32_t tx_lost_total;  /* beacons del TX que no llegaron (huecos en tx_seq) */
    int8_t rssi;
    uint8_t source;          /* csi_source_t */
    uint8_t channel;
    uint8_t reserved2;
    uint32_t free_heap;
} csi_frame_stats_t;

typedef struct __attribute__((packed)) {
    uint32_t uptime_ms;
    uint8_t state;           /* 0 calibrando, 1 quieto, 2 movimiento */
    uint8_t feature;         /* 0 varianza (V), 1 decorrelación (C) */
    uint16_t proc_us;        /* tiempo de cálculo de esta decisión */
    float score;
    float threshold_on;
    float threshold_off;
    float features[8];       /* V, C, banda 1-3, 3-10, 10-40 Hz, RSSI medio, RSSI desvío, tasa */
} csi_frame_detect_t;

/* Beacon que el TX envía por ESP-NOW (va dentro de la trama 802.11). */
#define CSI_TX_BEACON_MAGIC 0x54495343u /* "CSIT" */
typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    uint16_t rate_hz;
    uint32_t seq;
    uint32_t uptime_ms;
    uint32_t ip;             /* IPv4 del TX en orden de red (para la actualización OTA) */
    uint32_t send_fail;
    char fw_version[16];
} csi_tx_beacon_t;

typedef struct __attribute__((packed)) {
    uint8_t mac[6];
    csi_tx_beacon_t beacon;
} csi_frame_tx_info_t;

/* CRC-16/CCITT-FALSE. */
uint16_t csi_proto_crc16(const uint8_t *data, size_t len);

/*
 * Arma una trama completa en `out`. Devuelve el largo total o 0 si no cabe.
 * El payload puede pasarse en dos partes (p. ej. cabecera + CSI) para no copiar.
 */
size_t csi_proto_build(uint8_t type, const void *part1, size_t len1, const void *part2, size_t len2,
                       uint8_t *out, size_t out_size);

#ifdef __cplusplus
}
#endif
