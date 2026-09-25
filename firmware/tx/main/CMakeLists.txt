idf_component_register(SRCS "tx_main.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES csi_proto csi_wifi esp_wifi esp_http_server app_update esp_timer driver)
