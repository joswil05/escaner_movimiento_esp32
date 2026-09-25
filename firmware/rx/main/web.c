/*
 * Página web del receptor: estado en vivo, mapa de actividad, gráfica del índice y ajustes.
 *
 *   GET  /               página (web/index.html, embebida en el firmware)
 *   GET  /api/state      estado actual en JSON (la página lo consulta ~4 veces por segundo)
 *   POST /api/recalibrate
 *   GET  /api/config     umbrales del detector
 *   POST /api/config     cambia y guarda los umbrales (JSON)
 *   GET  /api/room       plano del cuarto (JSON guardado tal cual en NVS)
 *   POST /api/room       guarda el plano
 *
 * La web solo lee el último resultado: si un navegador se cuelga, la detección sigue igual.
 */
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "cJSON.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif_ip_addr.h"
#include "nvs.h"
#include "rx_status.h"

static const char *TAG = "web";

extern const char index_html_start[] asm("_binary_index_html_start");
extern const char index_html_end[] asm("_binary_index_html_end");

#define NVS_NS "csi_rx"
#define ROOM_MAX 600
static const char *DEFAULT_ROOM =
    "{\"width\":4.0,\"depth\":4.0,\"tx\":[0.5,2.0],\"rx\":[3.5,2.0],\"router\":[0.3,0.3]}";

static esp_err_t send_json(httpd_req_t *req, const char *json)
{
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_sendstr(req, json);
}

static int read_body(httpd_req_t *req, char *buf, size_t size)
{
    if (req->content_len <= 0 || req->content_len >= size) {
        return -1;
    }
    int got = 0;
    while (got < req->content_len) {
        int n = httpd_req_recv(req, buf + got, req->content_len - got);
        if (n == HTTPD_SOCK_ERR_TIMEOUT) {
            continue;
        }
        if (n <= 0) {
            return -1;
        }
        got += n;
    }
    buf[got] = '\0';
    return got;
}

static esp_err_t index_get(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    return httpd_resp_send(req, index_html_start, index_html_end - index_html_start);
}

static esp_err_t state_get(httpd_req_t *req)
{
    rx_status_t s;
    rx_get_status(&s);
    char ip[16] = "";
    if (s.have_tx) {
        esp_ip4_addr_t a = {.addr = s.tx_ip};
        snprintf(ip, sizeof(ip), IPSTR, IP2STR(&a));
    }
    const csi_features_t *f = &s.features;
    char buf[640];
    snprintf(buf, sizeof(buf),
             "{\"state\":\"%s\",\"score\":%.5f,\"on\":%.5f,\"off\":%.5f,\"base\":%.5f,\"proc_us\":%u,\"decisions\":%" PRIu32 ","
             "\"features\":{\"variance\":%.5f,\"decorrelation\":%.5f,\"band_1_3\":%.4f,\"band_3_10\":%.4f,"
             "\"band_10_40\":%.4f,\"rate_hz\":%.1f},"
             "\"uptime_ms\":%" PRIu32 ",\"rate\":%u,\"dropped\":%" PRIu32 ",\"lost\":%" PRIu32 ",\"rssi\":%d,"
             "\"channel\":%u,\"source\":\"%s\",\"heap\":%" PRIu32 ",\"tx\":{\"ok\":%s,\"ip\":\"%s\",\"fw\":\"%s\"}}",
             csi_state_name(s.state), s.score, s.threshold_on, s.threshold_off, s.base, s.proc_us, s.decisions, f->variance,
             f->decorrelation, f->band_1_3, f->band_3_10, f->band_10_40, f->rate_hz, s.uptime_ms, s.rx_last_s,
             s.dropped_total, s.tx_lost_total, s.rssi, s.channel, s.source ? "tx" : "router", s.free_heap,
             s.have_tx ? "true" : "false", ip, s.tx_fw);
    return send_json(req, buf);
}

static esp_err_t recalibrate_post(httpd_req_t *req)
{
    rx_request_recalibrate();
    return send_json(req, "{\"ok\":true}");
}

static esp_err_t config_get(httpd_req_t *req)
{
    csi_detector_config_t c;
    rx_get_detector_config(&c);
    char buf[256];
    snprintf(buf, sizeof(buf),
             "{\"feature\":\"%s\",\"k_on\":%.2f,\"k_off\":%.2f,\"ratio_on\":%.2f,\"ratio_off\":%.2f,"
             "\"n_on\":%d,\"n_off\":%d}",
             c.feature == CSI_FEATURE_DECORRELATION ? "decorrelation" : "variance", c.k_on, c.k_off, c.ratio_on,
             c.ratio_off, c.n_on, c.n_off);
    return send_json(req, buf);
}

static bool get_num(const cJSON *root, const char *key, double lo, double hi, double *out)
{
    const cJSON *it = cJSON_GetObjectItemCaseSensitive(root, key);
    if (!cJSON_IsNumber(it)) {
        return true; /* ausente: se deja como está */
    }
    if (it->valuedouble < lo || it->valuedouble > hi) {
        return false;
    }
    *out = it->valuedouble;
    return true;
}

static esp_err_t config_post(httpd_req_t *req)
{
    char body[300];
    if (read_body(req, body, sizeof(body)) < 0) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "cuerpo invalido");
    }
    cJSON *root = cJSON_Parse(body);
    if (root == NULL) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "JSON invalido");
    }
    csi_detector_config_t c;
    rx_get_detector_config(&c);
    double k_on = c.k_on, k_off = c.k_off, r_on = c.ratio_on, r_off = c.ratio_off, n_on = c.n_on, n_off = c.n_off;
    bool ok = get_num(root, "k_on", 1, 50, &k_on) && get_num(root, "k_off", 0.5, 50, &k_off) &&
              get_num(root, "ratio_on", 1.0, 10, &r_on) && get_num(root, "ratio_off", 1.0, 10, &r_off) &&
              get_num(root, "n_on", 1, 25, &n_on) && get_num(root, "n_off", 1, 50, &n_off);
    const cJSON *feat = cJSON_GetObjectItemCaseSensitive(root, "feature");
    if (cJSON_IsString(feat)) {
        c.feature = strcmp(feat->valuestring, "decorrelation") == 0 ? CSI_FEATURE_DECORRELATION
                                                                    : CSI_FEATURE_VARIANCE;
    }
    cJSON_Delete(root);
    if (!ok || k_off > k_on || r_off > r_on) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST,
                                   "valores fuera de rango (el umbral de liberacion no puede superar al de activacion)");
    }
    c.k_on = k_on;
    c.k_off = k_off;
    c.ratio_on = r_on;
    c.ratio_off = r_off;
    c.n_on = (int)n_on;
    c.n_off = (int)n_off;
    if (!rx_set_detector_config(&c)) {
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "no se pudo guardar");
    }
    return config_get(req);
}

static esp_err_t room_get(httpd_req_t *req)
{
    char buf[ROOM_MAX];
    size_t len = sizeof(buf);
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) == ESP_OK) {
        esp_err_t err = nvs_get_str(h, "room", buf, &len);
        nvs_close(h);
        if (err == ESP_OK) {
            return send_json(req, buf);
        }
    }
    return send_json(req, DEFAULT_ROOM);
}

static esp_err_t room_post(httpd_req_t *req)
{
    char body[ROOM_MAX];
    if (read_body(req, body, sizeof(body)) < 0) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "cuerpo invalido o demasiado largo");
    }
    cJSON *root = cJSON_Parse(body);
    bool valid = root && cJSON_IsNumber(cJSON_GetObjectItem(root, "width")) &&
                 cJSON_IsNumber(cJSON_GetObjectItem(root, "depth")) &&
                 cJSON_IsArray(cJSON_GetObjectItem(root, "tx")) && cJSON_IsArray(cJSON_GetObjectItem(root, "rx"));
    cJSON_Delete(root);
    if (!valid) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "faltan width, depth, tx o rx");
    }
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NS, NVS_READWRITE, &h);
    if (err == ESP_OK) {
        err = nvs_set_str(h, "room", body);
        if (err == ESP_OK) {
            err = nvs_commit(h);
        }
        nvs_close(h);
    }
    if (err != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, esp_err_to_name(err));
    }
    return send_json(req, body);
}

void web_start(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_open_sockets = 5;       /* pocos navegadores a la vez */
    config.lru_purge_enable = true;    /* si se llena, cierra la conexión más vieja */
    config.task_priority = 3;          /* por debajo de la captura y del detector */
    config.core_id = 0;
    config.stack_size = 6144;
    httpd_handle_t server;
    if (httpd_start(&server, &config) != ESP_OK) {
        ESP_LOGE(TAG, "No se pudo iniciar el servidor web");
        return;
    }
    const httpd_uri_t uris[] = {
        {.uri = "/", .method = HTTP_GET, .handler = index_get},
        {.uri = "/api/state", .method = HTTP_GET, .handler = state_get},
        {.uri = "/api/recalibrate", .method = HTTP_POST, .handler = recalibrate_post},
        {.uri = "/api/config", .method = HTTP_GET, .handler = config_get},
        {.uri = "/api/config", .method = HTTP_POST, .handler = config_post},
        {.uri = "/api/room", .method = HTTP_GET, .handler = room_get},
        {.uri = "/api/room", .method = HTTP_POST, .handler = room_post},
    };
    for (size_t i = 0; i < sizeof(uris) / sizeof(uris[0]); i++) {
        httpd_register_uri_handler(server, &uris[i]);
    }
}
