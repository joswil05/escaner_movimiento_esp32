idf_component_register(SRCS "rx_main.c" "web.c"
                       INCLUDE_DIRS "."
                       EMBED_TXTFILES "web/index.html"
                       PRIV_REQUIRES csi_proto csi_wifi csi_dsp esp_wifi esp_timer driver lwip nvs_flash
                                     esp_http_server json esp_netif)
