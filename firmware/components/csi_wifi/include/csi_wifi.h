/* Conexión WiFi en modo estación, compartida por el TX y el RX. */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Inicializa NVS, netif, WiFi STA sin ahorro de energía y empieza a conectar (no bloquea). */
void csi_wifi_start(void);

/* Espera hasta `timeout` ticks a tener IP. Devuelve true si está conectado. */
bool csi_wifi_wait_connected(TickType_t timeout);

bool csi_wifi_is_connected(void);

/* IP actual en orden de red (0 si no hay). */
uint32_t csi_wifi_ip(void);

/* IP del router (gateway) en orden de red (0 si no hay). */
uint32_t csi_wifi_gateway(void);

#ifdef __cplusplus
}
#endif
