/*
 * Receptor (placa A, con USB).
 *
 * Fuente de CSI (menuconfig):
 *   - Transmisor dedicado: acepta solo los beacons ESP-NOW de CONFIG_CSI_RX_TX_MAC y usa su
 *     número de secuencia para contar los que se perdieron en el aire.
 *   - Router: le hace ping al router y usa sus respuestas (igual que csi_router_test).
 *
 * Toda la salida por UART0 va en tramas binarias (csi_proto.h), incluidos los logs:
 *   CSI (una por paquete), STATS (1/s), TX_INFO (1/s) y LOG.
 * El callback de CSI solo filtra, copia y encola; el armado de tramas se hace en otra tarea.
 */
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "csi_proto.h"
#include "csi_wifi.h"
#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_now.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "ping/ping_sock.h"

#define CSI_MAX_LEN 384
#if CONFIG_CSI_RX_SOURCE_TX
#define CSI_SOURCE CSI_SOURCE_TX
#else
#define CSI_SOURCE CSI_SOURCE_ROUTER
#endif
#define UART_PORT UART_NUM_0
/* Offset de los datos del usuario dentro del cuerpo de una trama ESP-NOW (acción vendor). */
#define ESPNOW_DATA_OFFSET 15

typedef struct {
    csi_frame_csi_t hdr;
    int8_t buf[CSI_MAX_LEN];
} csi_item_t;

static const char *TAG = "csi_rx";

static QueueHandle_t s_queue;
static SemaphoreHandle_t s_uart_lock;
static SemaphoreHandle_t s_log_lock;
static uint8_t s_filter_mac[6];

static volatile uint32_t s_rx_count;
static volatile uint32_t s_dropped;
static volatile uint32_t s_tx_lost;
static volatile int8_t s_last_rssi;
static volatile bool s_have_tx_info;
static csi_frame_tx_info_t s_tx_info;

/* ---------- Salida en tramas ---------- */

static void send_frame(uint8_t type, const void *p1, size_t l1, const void *p2, size_t l2)
{
    static uint8_t frame[CSI_FRAME_MAX_PAYLOAD + CSI_FRAME_OVERHEAD];
    xSemaphoreTake(s_uart_lock, portMAX_DELAY);
    size_t n = csi_proto_build(type, p1, l1, p2, l2, frame, sizeof(frame));
    if (n) {
        uart_write_bytes(UART_PORT, frame, n);
    }
    xSemaphoreGive(s_uart_lock);
}

/*
 * ESP_LOG pasa por aquí: cada línea de log sale como una trama LOG. Algunos componentes
 * (la librería WiFi) escriben una línea en varias llamadas, así que se acumula hasta el '\n'.
 */
static int log_to_frame(const char *fmt, va_list args)
{
    static char line[200];
    static size_t len;
    char part[200];
    int n = vsnprintf(part, sizeof(part), fmt, args);
    if (n <= 0) {
        return n;
    }
    xSemaphoreTake(s_log_lock, portMAX_DELAY);
    size_t plen = strnlen(part, sizeof(part));
    size_t room = sizeof(line) - len;
    size_t take = plen < room ? plen : room;
    memcpy(line + len, part, take);
    len += take;
    bool complete = (plen && part[plen - 1] == '\n') || len == sizeof(line);
    if (complete) {
        while (len && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
            len--;
        }
        if (len) {
            send_frame(CSI_FRAME_LOG, line, len, NULL, 0);
        }
        len = 0;
    }
    xSemaphoreGive(s_log_lock);
    return n;
}

static void uart_init(void)
{
    /* Driver con buffer de salida grande: las escrituras no bloquean al ritmo de 100 paquetes/s. */
    ESP_ERROR_CHECK(uart_driver_install(UART_PORT, 256, 16384, 0, NULL, 0));
    /* printf() de otros componentes también pasa por el driver: no puede cortar una trama a la mitad. */
    uart_vfs_dev_use_driver(UART_PORT);
    s_uart_lock = xSemaphoreCreateMutex();
    s_log_lock = xSemaphoreCreateMutex();
    esp_log_set_vprintf(log_to_frame);
}

/* ---------- Captura de CSI ---------- */

static void csi_cb(void *ctx, wifi_csi_info_t *info)
{
    if (info == NULL || info->buf == NULL || memcmp(info->mac, s_filter_mac, 6) != 0) {
        return;
    }

    static csi_item_t item; /* el callback nunca corre en paralelo consigo mismo */
    uint32_t tx_seq = 0;

#if CONFIG_CSI_RX_SOURCE_TX
    /* Solo beacons del TX: descarta sus otras tramas (ARP, DHCP, HTTP...). */
    csi_tx_beacon_t beacon;
    if (info->payload == NULL || info->payload_len < ESPNOW_DATA_OFFSET + sizeof(beacon)) {
        return;
    }
    memcpy(&beacon, info->payload + ESPNOW_DATA_OFFSET, sizeof(beacon));
    if (beacon.magic != CSI_TX_BEACON_MAGIC) {
        return;
    }
    static bool s_seen;
    static uint32_t s_prev_seq;
    if (s_seen && beacon.seq > s_prev_seq + 1) {
        s_tx_lost += beacon.seq - s_prev_seq - 1;
    }
    s_seen = true;
    s_prev_seq = beacon.seq;
    tx_seq = beacon.seq;
    if ((beacon.seq % 100) == 0) {
        memcpy(s_tx_info.mac, info->mac, 6);
        s_tx_info.beacon = beacon;
        s_have_tx_info = true;
    }
#endif

    const wifi_pkt_rx_ctrl_t *rx = &info->rx_ctrl;
    csi_frame_csi_t *h = &item.hdr;
    h->rx_count = s_rx_count;
    h->tx_seq = tx_seq;
    h->rx_seq = info->rx_seq;
    h->local_ts = rx->timestamp;
    h->rssi = rx->rssi;
    h->noise_floor = rx->noise_floor;
    h->rate = rx->rate;
    h->sig_mode = rx->sig_mode;
    h->mcs = rx->mcs;
    h->cwb = rx->cwb;
    h->stbc = rx->stbc;
    h->channel = rx->channel;
    h->secondary_channel = rx->secondary_channel;
    h->first_word_invalid = info->first_word_invalid;
    memcpy(h->mac, info->mac, 6);
    h->csi_len = info->len > CSI_MAX_LEN ? CSI_MAX_LEN : info->len;
    memcpy(item.buf, info->buf, h->csi_len);

    s_rx_count++;
    s_last_rssi = rx->rssi;
    if (xQueueSend(s_queue, &item, 0) != pdTRUE) {
        s_dropped++;
    }
}

static void out_task(void *arg)
{
    static csi_item_t item;
    while (true) {
        if (xQueueReceive(s_queue, &item, portMAX_DELAY) == pdTRUE) {
            send_frame(CSI_FRAME_CSI, &item.hdr, sizeof(item.hdr), item.buf, item.hdr.csi_len);
        }
    }
}

static void stats_task(void *arg)
{
    uint32_t prev = 0;
    TickType_t last = xTaskGetTickCount();
    while (true) {
        xTaskDelayUntil(&last, pdMS_TO_TICKS(1000));
        uint8_t channel = 0;
        wifi_second_chan_t second;
        esp_wifi_get_channel(&channel, &second);
        uint32_t now = s_rx_count;
        csi_frame_stats_t st = {
            .uptime_ms = (uint32_t)(esp_timer_get_time() / 1000),
            .rx_last_s = (uint16_t)(now - prev),
            .dropped_total = s_dropped,
            .tx_lost_total = s_tx_lost,
            .rssi = s_last_rssi,
            .source = CSI_SOURCE,
            .channel = channel,
            .free_heap = esp_get_free_heap_size(),
        };
        prev = now;
        send_frame(CSI_FRAME_STATS, &st, sizeof(st), NULL, 0);
        if (s_have_tx_info) {
            send_frame(CSI_FRAME_TX_INFO, &s_tx_info, sizeof(s_tx_info), NULL, 0);
        }
    }
}

static void csi_start(void)
{
    /* Solo LLTF (64 subportadoras): igual que en la fase 0, válido para router y TX. */
    wifi_csi_config_t cfg = {
        .lltf_en = true,
        .htltf_en = false,
        .stbc_htltf2_en = false,
        .ltf_merge_en = true,
        .channel_filter_en = true,
        .manu_scale = false,
        .shift = 0,
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

#if CONFIG_CSI_RX_SOURCE_ROUTER
static void ping_router_start(void)
{
    esp_ping_config_t cfg = ESP_PING_DEFAULT_CONFIG();
    cfg.count = ESP_PING_COUNT_INFINITE;
    cfg.interval_ms = 1000 / CONFIG_CSI_RX_PING_HZ;
    cfg.timeout_ms = 1000;
    cfg.data_size = 1;
    cfg.task_stack_size = 3072;
    cfg.target_addr.type = ESP_IPADDR_TYPE_V4;
    cfg.target_addr.u_addr.ip4.addr = csi_wifi_gateway();
    esp_ping_callbacks_t cbs = {0};
    esp_ping_handle_t ping;
    ESP_ERROR_CHECK(esp_ping_new_session(&cfg, &cbs, &ping));
    ESP_ERROR_CHECK(esp_ping_start(ping));
    ESP_LOGI(TAG, "Ping al router a %d Hz", CONFIG_CSI_RX_PING_HZ);
}
#endif

void app_main(void)
{
    uart_init();
    s_queue = xQueueCreate(CONFIG_CSI_RX_QUEUE_LEN, sizeof(csi_item_t));
    configASSERT(s_queue);

    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    ESP_LOGI(TAG, "csi_rx, MAC de esta placa " MACSTR, MAC2STR(mac));

    csi_wifi_start();
    csi_wifi_wait_connected(portMAX_DELAY);

    wifi_ap_record_t ap;
    ESP_ERROR_CHECK(esp_wifi_sta_get_ap_info(&ap));
    ESP_LOGI(TAG, "Router " MACSTR ", canal %d, RSSI %d", MAC2STR(ap.bssid), ap.primary, ap.rssi);

#if CONFIG_CSI_RX_SOURCE_TX
    unsigned m[6];
    if (sscanf(CONFIG_CSI_RX_TX_MAC, "%x:%x:%x:%x:%x:%x", &m[0], &m[1], &m[2], &m[3], &m[4], &m[5]) != 6) {
        ESP_LOGE(TAG, "MAC del transmisor invalida: \"%s\"", CONFIG_CSI_RX_TX_MAC);
        abort();
    }
    for (int i = 0; i < 6; i++) {
        s_filter_mac[i] = (uint8_t)m[i];
    }
    /* ESP-NOW iniciado para que el driver acepte las tramas del TX. */
    ESP_ERROR_CHECK(esp_now_init());
    ESP_LOGI(TAG, "Fuente: transmisor " MACSTR, MAC2STR(s_filter_mac));
#else
    memcpy(s_filter_mac, ap.bssid, 6);
    ESP_LOGI(TAG, "Fuente: router");
#endif

    xTaskCreatePinnedToCore(out_task, "csi_out", 4096, NULL, 5, NULL, 1);
    xTaskCreatePinnedToCore(stats_task, "csi_stats", 3072, NULL, 4, NULL, 1);
    csi_start();
#if CONFIG_CSI_RX_SOURCE_ROUTER
    ping_router_start();
#endif
}
