/*
 * Memoria de actividad del receptor, para la web:
 *   - Eventos de movimiento: los últimos ACTIVITY_MAX_EVENTS (inicio, duración, índice máximo).
 *   - Historial: bloques de 10 s de los últimos 30 min (índice máximo y medio, fracción en MOVIMIENTO).
 * Los tiempos son milisegundos desde el arranque; la página los convierte a hora local.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "csi_dsp.h"

#define ACTIVITY_MAX_EVENTS 50
#define ACTIVITY_BIN_MS 10000
#define ACTIVITY_MAX_BINS 180

typedef struct {
    uint32_t start_ms;
    uint32_t dur_ms;
    float peak;       /* índice máximo durante el evento */
    float base;       /* línea base y umbral en el momento del máximo (para expresarlo en %) */
    float on;
} activity_event_t;

typedef struct {
    uint32_t end_ms;
    float max_score;
    float mean_score;
    float motion_frac;  /* 0..1: fracción de decisiones en MOVIMIENTO dentro del bloque */
} activity_bin_t;

/* Se llama en cada decisión del detector (tarea del detector). */
void activity_on_decision(uint32_t now_ms, csi_state_t state, float score, float base, float on);

/* Copias para la web (tarea HTTP). Devuelven cuántos elementos copiaron, del más viejo al más nuevo. */
int activity_get_events(activity_event_t *out, int max, activity_event_t *active, bool *has_active);
int activity_get_bins(activity_bin_t *out, int max);
