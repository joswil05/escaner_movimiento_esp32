idf_component_register(SRCS "rx_main.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES csi_proto csi_wifi csi_dsp esp_wifi esp_timer driver lwip)
