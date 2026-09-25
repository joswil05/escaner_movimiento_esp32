#include "activity.h"

#include "freertos/FreeRTOS.h"

static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;

static activity_event_t s_events[ACTIVITY_MAX_EVENTS];
static int s_ev_head, s_ev_count;
static activity_event_t s_active;
static bool s_in_motion;

static activity_bin_t s_bins[ACTIVITY_MAX_BINS];
static int s_bin_head, s_bin_count;
static uint32_t s_bin_start;
static uint32_t s_bin_n, s_bin_motion;
static float s_bin_sum, s_bin_max;

void activity_on_decision(uint32_t now_ms, csi_state_t state, float score, float base, float on)
{
    taskENTER_CRITICAL(&s_lock);

    /* eventos: de QUIETO/CALIBRANDO a MOVIMIENTO abre uno, de MOVIMIENTO a otro estado lo cierra */
    if (state == CSI_STATE_MOTION) {
        if (!s_in_motion) {
            s_in_motion = true;
            s_active = (activity_event_t){.start_ms = now_ms, .peak = score, .base = base, .on = on};
        } else if (score > s_active.peak) {
            s_active.peak = score;
            s_active.base = base;
            s_active.on = on;
        }
        s_active.dur_ms = now_ms - s_active.start_ms;
    } else if (s_in_motion) {
        s_in_motion = false;
        s_active.dur_ms = now_ms - s_active.start_ms;
        s_events[s_ev_head] = s_active;
        s_ev_head = (s_ev_head + 1) % ACTIVITY_MAX_EVENTS;
        if (s_ev_count < ACTIVITY_MAX_EVENTS) {
            s_ev_count++;
        }
    }

    /* historial en bloques de 10 s (las decisiones en calibración no cuentan) */
    if (s_bin_n == 0 && s_bin_start == 0) {
        s_bin_start = now_ms;
    }
    if (state != CSI_STATE_CALIBRATING) {
        s_bin_n++;
        s_bin_sum += score;
        if (score > s_bin_max) {
            s_bin_max = score;
        }
        if (state == CSI_STATE_MOTION) {
            s_bin_motion++;
        }
    }
    if (now_ms - s_bin_start >= ACTIVITY_BIN_MS) {
        if (s_bin_n) {
            s_bins[s_bin_head] = (activity_bin_t){
                .end_ms = now_ms,
                .max_score = s_bin_max,
                .mean_score = s_bin_sum / s_bin_n,
                .motion_frac = (float)s_bin_motion / s_bin_n,
            };
            s_bin_head = (s_bin_head + 1) % ACTIVITY_MAX_BINS;
            if (s_bin_count < ACTIVITY_MAX_BINS) {
                s_bin_count++;
            }
        }
        s_bin_start = now_ms;
        s_bin_n = s_bin_motion = 0;
        s_bin_sum = s_bin_max = 0.0f;
    }

    taskEXIT_CRITICAL(&s_lock);
}

int activity_get_events(activity_event_t *out, int max, activity_event_t *active, bool *has_active)
{
    taskENTER_CRITICAL(&s_lock);
    int n = s_ev_count < max ? s_ev_count : max;
    int first = (s_ev_head - n + ACTIVITY_MAX_EVENTS) % ACTIVITY_MAX_EVENTS;
    for (int i = 0; i < n; i++) {
        out[i] = s_events[(first + i) % ACTIVITY_MAX_EVENTS];
    }
    *has_active = s_in_motion;
    *active = s_active;
    taskEXIT_CRITICAL(&s_lock);
    return n;
}

int activity_get_bins(activity_bin_t *out, int max)
{
    taskENTER_CRITICAL(&s_lock);
    int n = s_bin_count < max ? s_bin_count : max;
    int first = (s_bin_head - n + ACTIVITY_MAX_BINS) % ACTIVITY_MAX_BINS;
    for (int i = 0; i < n; i++) {
        out[i] = s_bins[(first + i) % ACTIVITY_MAX_BINS];
    }
    taskEXIT_CRITICAL(&s_lock);
    return n;
}
