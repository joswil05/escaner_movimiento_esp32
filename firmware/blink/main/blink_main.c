/*
 * Firmware de prueba para la placa sin USB.
 *
 * Si ves el LED parpadear o los mensajes "tick" en el monitor serial,
 * la placa se puede programar por UART0 y el chip está sano.
 * Anota la MAC que imprime: en el proyecto será la MAC del transmisor.
 */
#include <inttypes.h>
#include <stdio.h>

#include "driver/gpio.h"
#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "blink";

static void print_board_info(void)
{
    esp_chip_info_t chip;
    esp_chip_info(&chip);

    uint32_t flash_size = 0;
    esp_flash_get_size(NULL, &flash_size);

    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);

    ESP_LOGI(TAG, "Chip: ESP32 rev v%d.%d, %d nucleos, flash %" PRIu32 " MB",
             chip.revision / 100, chip.revision % 100, chip.cores,
             flash_size / (1024 * 1024));
    ESP_LOGI(TAG, "MAC WiFi STA: %02X:%02X:%02X:%02X:%02X:%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    ESP_LOGI(TAG, "Causa del ultimo reinicio: %d", esp_reset_reason());
    ESP_LOGI(TAG, "LED en GPIO%d, periodo %d ms", CONFIG_BLINK_GPIO, CONFIG_BLINK_PERIOD_MS);
}

void app_main(void)
{
    print_board_info();

    gpio_reset_pin(CONFIG_BLINK_GPIO);
    gpio_set_direction(CONFIG_BLINK_GPIO, GPIO_MODE_OUTPUT);

    uint32_t count = 0;
    bool on = false;
    while (true) {
        on = !on;
        gpio_set_level(CONFIG_BLINK_GPIO, on);
        if (on) {
            ESP_LOGI(TAG, "tick %" PRIu32 " (heap libre: %" PRIu32 " bytes)",
                     ++count, esp_get_free_heap_size());
        }
        vTaskDelay(pdMS_TO_TICKS(CONFIG_BLINK_PERIOD_MS));
    }
}
