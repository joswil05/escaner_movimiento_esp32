/*
 * Transmisor dedicado (placa B, sin USB).
 *
 * - Se conecta al router como estación: así queda en el mismo canal que el receptor
 *   y tiene IP para actualizarse por WiFi.
 * - Envía CONFIG_CSI_TX_HZ beacons ESP-NOW por segundo, en broadcast, a tasa fija
 *   HT20 MCS0 (OFDM: el receptor obtiene CSI de cada uno).
 * - Servidor HTTP en el puerto 80:
 *     GET  /     estado en texto
 *     POST /ota  cuerpo = binario del firmware nuevo (build/csi_tx.bin)
 * - Si una versión nueva no consigue conectarse al WiFi en CONFIG_CSI_TX_WIFI_TIMEOUT_S,
 *   reinicia y el bootloader vuelve a la versión anterior (rollback).
 *
 * La placa no tiene USB: el estado se ve en el LED y, desde el receptor, en las tramas TX_INFO.
 */
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "csi_proto.h"
#include "csi_wifi.h"
#include "driver/gpio.h"
#include "esp_app_desc.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_now.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "csi_tx";
static const uint8_t BROADCAST[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

static volatile uint32_t s_seq;
static volatile uint32_t s_send_fail;
static volatile bool s_sending;

/* ---------- LED de estado ---------- */

static void led_task(void *arg)
{
    const int gpio = CONFIG_CSI_TX_LED_GPIO;
    gpio_reset_pin(gpio);
    gpio_set_direction(gpio, GPIO_MODE_OUTPUT);
    while (true) {
        if (s_sending && csi_wifi_is_connected()) {
            gpio_set_level(gpio, 1); /* destello corto cada segundo */
            vTaskDelay(pdMS_TO_TICKS(60));
            gpio_set_level(gpio, 0);
            vTaskDelay(pdMS_TO_TICKS(940));
        } else {
            gpio_set_level(gpio, 1); /* parpadeo rápido: conectando */
            vTaskDelay(pdMS_TO_TICKS(100));
            gpio_set_level(gpio, 0);
            vTaskDelay(pdMS_TO_TICKS(100));
        }
    }
}

/* ---------- Beacons ESP-NOW ---------- */

static void espnow_send_cb(const uint8_t *mac, esp_now_send_status_t status)
{
    if (status != ESP_NOW_SEND_SUCCESS) {
        s_send_fail++;
    }
}

static void espnow_init(void)
{
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_register_send_cb(espnow_send_cb));

    esp_now_peer_info_t peer = {
        .channel = 0, /* canal actual (el del router) */
        .ifidx = WIFI_IF_STA,
        .encrypt = false,
    };
    memcpy(peer.peer_addr, BROADCAST, 6);
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));

    /* Tasa fija OFDM: los paquetes 802.11b (1 Mbps, por defecto) no tienen subportadoras. */
    esp_now_rate_config_t rate = {
        .phymode = WIFI_PHY_MODE_HT20,
        .rate = WIFI_PHY_RATE_MCS0_LGI,
        .ersu = false,
        .dcm = false,
    };
    ESP_ERROR_CHECK(esp_now_set_peer_rate_config(BROADCAST, &rate));
}

static void beacon_task(void *arg)
{
    csi_tx_beacon_t beacon = {
        .magic = CSI_TX_BEACON_MAGIC,
        .version = 1,
        .rate_hz = CONFIG_CSI_TX_HZ,
    };
    strlcpy(beacon.fw_version, esp_app_get_description()->version, sizeof(beacon.fw_version));

    const TickType_t period = pdMS_TO_TICKS(1000 / CONFIG_CSI_TX_HZ);
    TickType_t last = xTaskGetTickCount();
    s_sending = true;
    while (true) {
        xTaskDelayUntil(&last, period);
        if (!csi_wifi_is_connected()) {
            continue; /* sin router no hay canal fijo: esperar */
        }
        beacon.seq = s_seq++;
        beacon.uptime_ms = (uint32_t)(esp_timer_get_time() / 1000);
        beacon.ip = csi_wifi_ip();
        beacon.send_fail = s_send_fail;
        if (esp_now_send(BROADCAST, (const uint8_t *)&beacon, sizeof(beacon)) != ESP_OK) {
            s_send_fail++;
        }
    }
}

/* ---------- HTTP: estado y OTA ---------- */

static esp_err_t status_get(httpd_req_t *req)
{
    char buf[320];
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    const esp_partition_t *running = esp_ota_get_running_partition();
    uint8_t primary;
    wifi_second_chan_t second;
    esp_wifi_get_channel(&primary, &second);
    snprintf(buf, sizeof(buf),
             "csi_tx %s\nMAC " MACSTR "\nparticion %s\ncanal %u\nbeacons enviados %" PRIu32
             "\nfallos de envio %" PRIu32 "\nuptime %" PRIu64 " s\nheap libre %" PRIu32 "\n",
             esp_app_get_description()->version, MAC2STR(mac), running->label, primary, s_seq, s_send_fail,
             esp_timer_get_time() / 1000000, esp_get_free_heap_size());
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_sendstr(req, buf);
}

static esp_err_t ota_post(httpd_req_t *req)
{
    const esp_partition_t *target = esp_ota_get_next_update_partition(NULL);
    if (target == NULL) {
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "sin particion OTA");
    }
    ESP_LOGI(TAG, "OTA: %d bytes hacia %s", req->content_len, target->label);

    s_sending = false; /* el LED deja de destellar mientras se actualiza */
    esp_ota_handle_t ota;
    esp_err_t err = esp_ota_begin(target, OTA_WITH_SEQUENTIAL_WRITES, &ota);
    if (err != ESP_OK) {
        s_sending = true;
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, esp_err_to_name(err));
    }

    static char chunk[2048];
    int remaining = req->content_len;
    while (remaining > 0) {
        int n = httpd_req_recv(req, chunk, remaining < (int)sizeof(chunk) ? remaining : (int)sizeof(chunk));
        if (n == HTTPD_SOCK_ERR_TIMEOUT) {
            continue;
        }
        if (n <= 0 || esp_ota_write(ota, chunk, n) != ESP_OK) {
            esp_ota_abort(ota);
            s_sending = true;
            return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "error recibiendo o escribiendo");
        }
        remaining -= n;
    }

    err = esp_ota_end(ota);
    if (err == ESP_OK) {
        err = esp_ota_set_boot_partition(target);
    }
    if (err != ESP_OK) {
        s_sending = true;
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, esp_err_to_name(err));
    }
    httpd_resp_sendstr(req, "OK: firmware recibido, reiniciando\n");
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
    return ESP_OK;
}

static void http_start(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.recv_wait_timeout = 10;
    httpd_handle_t server;
    ESP_ERROR_CHECK(httpd_start(&server, &config));
    const httpd_uri_t status = {.uri = "/", .method = HTTP_GET, .handler = status_get};
    const httpd_uri_t ota = {.uri = "/ota", .method = HTTP_POST, .handler = ota_post};
    httpd_register_uri_handler(server, &status);
    httpd_register_uri_handler(server, &ota);
}

/* Confirma la versión actual si es una OTA en prueba; si no hay WiFi a tiempo, reinicia. */
static void confirm_or_rollback(void)
{
    esp_ota_img_states_t state;
    const esp_partition_t *running = esp_ota_get_running_partition();
    bool pending = esp_ota_get_state_partition(running, &state) == ESP_OK && state == ESP_OTA_IMG_PENDING_VERIFY;

    if (csi_wifi_wait_connected(pdMS_TO_TICKS(CONFIG_CSI_TX_WIFI_TIMEOUT_S * 1000))) {
        if (pending) {
            esp_ota_mark_app_valid_cancel_rollback();
            ESP_LOGI(TAG, "Version nueva confirmada");
        }
        return;
    }
    ESP_LOGE(TAG, "Sin WiFi tras %d s: reiniciando%s", CONFIG_CSI_TX_WIFI_TIMEOUT_S,
             pending ? " y volviendo a la version anterior" : "");
    esp_restart();
}

void app_main(void)
{
    ESP_LOGI(TAG, "csi_tx %s", esp_app_get_description()->version);
    if (CONFIG_CSI_TX_LED_GPIO >= 0) {
        xTaskCreate(led_task, "led", 2048, NULL, 2, NULL);
    }

    csi_wifi_start();
    confirm_or_rollback();

    espnow_init();
    http_start();
    xTaskCreatePinnedToCore(beacon_task, "beacon", 3072, NULL, 10, NULL, 1);
    ESP_LOGI(TAG, "Enviando %d beacons/s", CONFIG_CSI_TX_HZ);
}
