/*
 * Detector de movimiento: port a C de host/csi_tools/dsp.py y host/csi_tools/detector.py.
 *
 * Mismo algoritmo, mismos parámetros por defecto y mismos resultados (dentro del error de
 * redondeo de float): lo verifica host/tests/test_csi_dsp.py compilando test/host_runner.c.
 * Cualquier cambio de algoritmo va en los dos lados.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CSI_DSP_NSC 51          /* subportadoras útiles de LLTF: -26..-1, +2..+26 */
#define CSI_DSP_MAX_WINDOW 100 /* ~1 s a 100 Hz; 3 búferes de 100x51 floats = 61 KB */
#define CSI_DSP_MAX_CALIB 64

typedef struct {
    float variance;       /* V */
    float decorrelation;  /* C */
    float band_1_3;
    float band_3_10;
    float band_10_40;
    float rssi_mean;
    float rssi_std;
    float rate_hz;
} csi_features_t;

typedef enum {
    CSI_STATE_CALIBRATING = 0,
    CSI_STATE_QUIET = 1,
    CSI_STATE_MOTION = 2,
} csi_state_t;

typedef enum {
    CSI_FEATURE_VARIANCE = 0,
    CSI_FEATURE_DECORRELATION = 1,
} csi_feature_sel_t;

typedef struct {
    int window;          /* paquetes por ventana (<= CSI_DSP_MAX_WINDOW) */
    int hop;             /* paquetes entre decisiones */
    csi_feature_sel_t feature;
    int calib_windows;   /* <= CSI_DSP_MAX_CALIB */
    float k_on, k_off;
    float ratio_on, ratio_off;
    int n_on, n_off;
    float alpha;
    float min_sigma;
    bool compute_bands;  /* energía por bandas (DFT): ~50 ms en la ESP32; el detector no la usa */
} csi_detector_config_t;

typedef struct {
    csi_state_t state;
    float score;
    float threshold_on;
    float threshold_off;
    csi_features_t features;
} csi_decision_t;

typedef struct {
    csi_detector_config_t cfg;
    /* ventana circular de entrada */
    float amps[CSI_DSP_MAX_WINDOW][CSI_DSP_NSC];
    int8_t rssi[CSI_DSP_MAX_WINDOW];
    uint32_t ts_us[CSI_DSP_MAX_WINDOW];
    int count;   /* paquetes en la ventana (hasta cfg.window) */
    int head;    /* próxima posición a escribir */
    int since_hop;
    /* trabajo */
    float x[CSI_DSP_MAX_WINDOW][CSI_DSP_NSC];
    float y[CSI_DSP_MAX_WINDOW][CSI_DSP_NSC];
    float cos_tab[CSI_DSP_MAX_WINDOW];
    float sin_tab[CSI_DSP_MAX_WINDOW];
    /* máquina de estados */
    csi_state_t state;
    float calib[CSI_DSP_MAX_CALIB];
    int n_calib;
    float base, sigma;
    int above, below;
    csi_decision_t last;
} csi_detector_t;

/* Valores por defecto: iguales a DetectorConfig de Python. */
csi_detector_config_t csi_detector_default_config(void);

/* Amplitud de las 51 subportadoras útiles a partir del CSI crudo LLTF (128 bytes, pares imag, real). */
bool csi_dsp_amplitude(const int8_t *raw, int len, bool first_word_invalid, float out[CSI_DSP_NSC]);

/*
 * Features de una ventana de n paquetes guardada como búfer circular: el paquete más antiguo
 * está en la fila `start` de `amps`, `rssi` y `ts_us` (usar start = 0 si ya está en orden).
 * `x` y `y` son búferes de trabajo de n filas; las entradas no se modifican.
 * `cos_tab`/`sin_tab` tienen n entradas: cos/sin(2*pi*i/n). Con `bands` = false las energías
 * por banda quedan en 0 (es la parte más costosa).
 */
void csi_dsp_window_features(const float (*amps)[CSI_DSP_NSC], int n, int start, const int8_t *rssi,
                             const uint32_t *ts_us, float (*x)[CSI_DSP_NSC], float (*y)[CSI_DSP_NSC],
                             const float *cos_tab, const float *sin_tab, bool bands, csi_features_t *out);

void csi_detector_init(csi_detector_t *det, const csi_detector_config_t *cfg);
void csi_detector_recalibrate(csi_detector_t *det);

/* Agrega un paquete; devuelve true cuando hay una decisión nueva en det->last. */
bool csi_detector_push(csi_detector_t *det, const float amp[CSI_DSP_NSC], int8_t rssi, uint32_t ts_us);

/* Avanza la máquina de estados con el score de una ventana (lo usa push; expuesto para tests). */
void csi_detector_step(csi_detector_t *det, float score);

void csi_detector_thresholds(const csi_detector_t *det, float *on, float *off);

const char *csi_state_name(csi_state_t state);

#ifdef __cplusplus
}
#endif
