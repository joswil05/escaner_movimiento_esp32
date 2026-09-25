/*
 * Fase 0: captura de CSI en "modo router".
 *
 * La placa se conecta al router, le hace ping CONFIG_CSI_PING_HZ veces por
 * segundo y, de cada respuesta, obtiene el CSI. El CSI se imprime por serial
 * con el mismo formato de texto que usan los ejemplos de esp-csi:
 *
 *   CSI_DATA,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,
 *   aggregation,stbc,fec_coding,sgi,noise_floor,ampdu_cnt,channel,
 *   secondary_channel,local_timestamp,ant,sig_len,rx_state,len,first_word,"[...]"
 *
 * Una vez por segundo imprime además una línea de estadísticas:
 *
 *   CSI_STATS,uptime_ms,recibidos_1s,descartados_total,rssi
 *
 * El callback de CSI solo copia el paquete a una cola; la impresión se hace en
 * otra tarea para no bloquear el stack WiFi.
 */
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lwip/ip4_addr.h"
#include "nvs_flash.h"
#include "ping/ping_sock.h"

#define CSI_MAX_LEN 384 /* LLTF + HT-LTF + STBC en ESP32; con solo LLTF son 128 */
#define WIFI_CONNECTED_BIT BIT0

typedef struct {
    uint32_t id;
    uint8_t mac[6];
    int8_t rssi;
    uint8_t rate;
    uint8_t sig_mode;
    uint8_t mcs;
    uint8_t cwb;
    uint8_t smoothing;
    uint8_t not_sounding;
    uint8_t aggregation;
    uint8_t stbc;
    uint8_t fec_coding;
    uint8_t sgi;
    int8_t noise_floor;
    uint8_t ampdu_cnt;
    uint8_t channel;
    uint8_t secondary_channel;
    uint32_t timestamp;
    uint8_t ant;
    uint16_t sig_len;
    uint8_t rx_state;
    uint16_t len;
    bool first_word_invalid;
    int8_t buf[CSI_MAX_LEN];
} csi_packet_t;

static const char *TAG = "csi_router";

static EventGroupHandle_t s_wifi_events;
static QueueHandle_t s_csi_queue;
static uint8_t s_ap_bssid[6];

static volatile uint32_t s_rx_count;      /* paquetes CSI aceptados (total) */
static volatile uint32_t s_dropped_count; /* descartados por cola llena */
static volatile int8_t s_last_rssi;

/* Corre en el contexto de la tarea WiFi: solo filtrar, copiar y encolar. */
static void wifi_csi_rx_cb(void *ctx, wifi_csi_info_t *info)
{
    if (info == NULL || info->buf == NULL || memcmp(info->mac, s_ap_bssid, 6) != 0) {
        return;
    }

    static csi_packet_t pkt; /* el callback nunca corre en paralelo consigo mismo */
    const wifi_pkt_rx_ctrl_t *rx = &info->rx_ctrl;

    pkt.id = s_rx_count;
    memcpy(pkt.mac, info->mac, 6);
    pkt.rssi = rx->rssi;
    pkt.rate = rx->rate;
    pkt.sig_mode = rx->sig_mode;
    pkt.mcs = rx->mcs;
    pkt.cwb = rx->cwb;
    pkt.smoothing = rx->smoothing;
    pkt.not_sounding = rx->not_sounding;
    pkt.aggregation = rx->aggregation;
    pkt.stbc = rx->stbc;
    pkt.fec_coding = rx->fec_coding;
    pkt.sgi = rx->sgi;
    pkt.noise_floor = rx->noise_floor;
    pkt.ampdu_cnt = rx->ampdu_cnt;
    pkt.channel = rx->channel;
    pkt.secondary_channel = rx->secondary_channel;
    pkt.timestamp = rx->timestamp;
    pkt.ant = rx->ant;
    pkt.sig_len = rx->sig_len;
    pkt.rx_state = rx->rx_state;
    pkt.len = info->len > CSI_MAX_LEN ? CSI_MAX_LEN : info->len;
    pkt.first_word_invalid = info->first_word_invalid;
    memcpy(pkt.buf, info->buf, pkt.len);

    s_rx_count++;
    s_last_rssi = rx->rssi;
    if (xQueueSend(s_csi_queue, &pkt, 0) != pdTRUE) {
        s_dropped_count++;
    }
}

static void csi_print_task(void *arg)
{
    static csi_packet_t pkt;
    static char line[160 + CSI_MAX_LEN * 5];

    while (true) {
        if (xQueueReceive(s_csi_queue, &pkt, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        int n = snprintf(line, sizeof(line),
                         "CSI_DATA,%" PRIu32 "," MACSTR ",%d,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%d,%u,%u,%u,%" PRIu32
                         ",%u,%u,%u,%u,%d,\"[",
                         pkt.id, MAC2STR(pkt.mac), pkt.rssi, pkt.rate, pkt.sig_mode, pkt.mcs, pkt.cwb,
                         pkt.smoothing, pkt.not_sounding, pkt.aggregation, pkt.stbc, pkt.fec_coding, pkt.sgi,
                         pkt.noise_floor, pkt.ampdu_cnt, pkt.channel, pkt.secondary_channel, pkt.timestamp,
                         pkt.ant, pkt.sig_len, pkt.rx_state, pkt.len, pkt.first_word_invalid);
        for (int i = 0; i < pkt.len && n < (int)sizeof(line) - 8; i++) {
            n += snprintf(line + n, sizeof(line) - n, i ? ",%d" : "%d", pkt.buf[i]);
        }
        n += snprintf(line + n, sizeof(line) - n, "]\"\n");
        fwrite(line, 1, n, stdout);
    }
}

static void csi_stats_task(void *arg)
{
    uint32_t prev = 0;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        uint32_t now = s_rx_count;
        printf("CSI_STATS,%" PRIu64 ",%" PRIu32 ",%" PRIu32 ",%d\n",
               esp_timer_get_time() / 1000, now - prev, s_dropped_count, s_last_rssi);
        prev = now;
    }
}

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_wifi_events, WIFI_CONNECTED_BIT);
        ESP_LOGW(TAG, "WiFi desconectado, reintentando...");
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
    }
}

static void wifi_init_sta(void)
{
    s_wifi_events = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL));

    wifi_config_t wifi_config = {0};
    strlcpy((char *)wifi_config.sta.ssid, CONFIG_CSI_WIFI_SSID, sizeof(wifi_config.sta.ssid));
    strlcpy((char *)wifi_config.sta.password, CONFIG_CSI_WIFI_PASSWORD, sizeof(wifi_config.sta.password));

    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    /* Sin ahorro de energía: si no, la radio duerme y se pierden respuestas del router. */
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));

    ESP_LOGI(TAG, "Conectando a \"%s\"...", CONFIG_CSI_WIFI_SSID);
    xEventGroupWaitBits(s_wifi_events, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
}

static void csi_init(void)
{
    wifi_ap_record_t ap_info;
    ESP_ERROR_CHECK(esp_wifi_sta_get_ap_info(&ap_info));
    memcpy(s_ap_bssid, ap_info.bssid, 6);
    ESP_LOGI(TAG, "Router " MACSTR ", canal %d, RSSI %d", MAC2STR(ap_info.bssid), ap_info.primary,
             ap_info.rssi);

    /* Solo LLTF (64 subportadoras = 128 bytes): lo soporta cualquier router. */
    wifi_csi_config_t csi_config = {
        .lltf_en = true,
        .htltf_en = false,
        .stbc_htltf2_en = false,
        .ltf_merge_en = true,
        .channel_filter_en = true,
        .manu_scale = false,
        .shift = 0,
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(wifi_csi_rx_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

static void ping_router_start(void)
{
    esp_netif_ip_info_t ip_info;
    esp_netif_get_ip_info(esp_netif_get_handle_from_ifkey("WIFI_STA_DEF"), &ip_info);
    ESP_LOGI(TAG, "IP " IPSTR ", router " IPSTR ", ping a %d Hz", IP2STR(&ip_info.ip), IP2STR(&ip_info.gw),
             CONFIG_CSI_PING_HZ);

    esp_ping_config_t ping_config = ESP_PING_DEFAULT_CONFIG();
    ping_config.count = ESP_PING_COUNT_INFINITE;
    ping_config.interval_ms = 1000 / CONFIG_CSI_PING_HZ;
    ping_config.timeout_ms = 1000;
    ping_config.data_size = 1;
    ping_config.task_stack_size = 3072;
    ping_config.target_addr.type = ESP_IPADDR_TYPE_V4;
    ping_config.target_addr.u_addr.ip4.addr = ip_info.gw.addr;

    esp_ping_callbacks_t cbs = {0};
    esp_ping_handle_t ping;
    ESP_ERROR_CHECK(esp_ping_new_session(&ping_config, &cbs, &ping));
    ESP_ERROR_CHECK(esp_ping_start(ping));
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    ESP_LOGI(TAG, "MAC de esta placa: " MACSTR, MAC2STR(mac));

    s_csi_queue = xQueueCreate(CONFIG_CSI_QUEUE_LEN, sizeof(csi_packet_t));
    configASSERT(s_csi_queue);

    wifi_init_sta();
    csi_init();

    xTaskCreatePinnedToCore(csi_print_task, "csi_print", 4096, NULL, 5, NULL, 1);
    xTaskCreatePinnedToCore(csi_stats_task, "csi_stats", 3072, NULL, 4, NULL, 1);

    ping_router_start();
}
