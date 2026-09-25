#include "csi_dsp.h"

#include <math.h>
#include <string.h>

#define HAMPEL_HALF 3
#define HAMPEL_NSIGMA 3.0f
#define MAD_SCALE 1.4826f
#define TWO_PI 6.283185307179586

static const float BANDS[3][2] = {{1.0f, 3.0f}, {3.0f, 10.0f}, {10.0f, 40.0f}};

csi_detector_config_t csi_detector_default_config(void)
{
    csi_detector_config_t c = {
        .window = 100,
        .hop = 20,
        .feature = CSI_FEATURE_VARIANCE,
        .calib_windows = 25,
        .k_on = 6.0f,
        .k_off = 3.0f,
        .ratio_on = 1.6f,
        .ratio_off = 1.3f,
        .n_on = 2,
        .n_off = 5,
        .alpha = 0.003f,
        .min_sigma = 1e-4f,
        .compute_bands = true, /* igual que la versión de Python */
    };
    return c;
}

const char *csi_state_name(csi_state_t state)
{
    switch (state) {
    case CSI_STATE_QUIET:
        return "QUIETO";
    case CSI_STATE_MOTION:
        return "MOVIMIENTO";
    default:
        return "CALIBRANDO";
    }
}

/* ---------- amplitud ---------- */

bool csi_dsp_amplitude(const int8_t *raw, int len, bool first_word_invalid, float out[CSI_DSP_NSC])
{
    if (len < 128) {
        return false;
    }
    int k = 0;
    /* -26..-1 = índices 38..63, luego +2..+26 = índices 2..26 (0 = DC, +1 inválida en ESP32) */
    for (int pass = 0; pass < 2; pass++) {
        int from = pass == 0 ? 38 : 2;
        int to = pass == 0 ? 64 : 27;
        for (int i = from; i < to; i++) {
            float im = raw[2 * i];
            float re = raw[2 * i + 1];
            if (first_word_invalid && i < 2) {
                im = re = 0.0f;
            }
            out[k++] = sqrtf(re * re + im * im);
        }
    }
    return true;
}

/* ---------- utilidades ---------- */

/* Mediana de n <= 2*HAMPEL_HALF+1 valores (o de la calibración); ordena `v` en el lugar. */
static float median_inplace(float *v, int n)
{
    for (int i = 1; i < n; i++) {
        float key = v[i];
        int j = i - 1;
        while (j >= 0 && v[j] > key) {
            v[j + 1] = v[j];
            j--;
        }
        v[j + 1] = key;
    }
    return (n % 2) ? v[n / 2] : 0.5f * (v[n / 2 - 1] + v[n / 2]);
}

/* ---------- features ---------- */

void csi_dsp_window_features(const float (*amps)[CSI_DSP_NSC], int n, int start, const int8_t *rssi,
                             const uint32_t *ts_us, float (*x)[CSI_DSP_NSC], float (*y)[CSI_DSP_NSC],
                             const float *cos_tab, const float *sin_tab, bool bands, csi_features_t *out)
{
    memset(out, 0, sizeof(*out));
    if (n <= 0) {
        return;
    }
#define ROW(t) (((start) + (t)) % n)

    /* 1. normalización por paquete (x queda en orden temporal) */
    for (int t = 0; t < n; t++) {
        const float *a = amps[ROW(t)];
        float mean = 0.0f;
        for (int s = 0; s < CSI_DSP_NSC; s++) {
            mean += a[s];
        }
        mean /= CSI_DSP_NSC;
        float div = mean > 0.0f ? mean : 1.0f;
        for (int s = 0; s < CSI_DSP_NSC; s++) {
            x[t][s] = a[s] / div;
        }
    }

    /* 2. Hampel temporal por subportadora: x -> y */
    float seg[2 * HAMPEL_HALF + 1];
    float dev[2 * HAMPEL_HALF + 1];
    for (int s = 0; s < CSI_DSP_NSC; s++) {
        for (int t = 0; t < n; t++) {
            int lo = t - HAMPEL_HALF < 0 ? 0 : t - HAMPEL_HALF;
            int hi = t + HAMPEL_HALF + 1 > n ? n : t + HAMPEL_HALF + 1;
            int m = hi - lo;
            for (int i = 0; i < m; i++) {
                seg[i] = x[lo + i][s];
            }
            float med = median_inplace(seg, m);
            for (int i = 0; i < m; i++) {
                dev[i] = fabsf(x[lo + i][s] - med);
            }
            float mad = MAD_SCALE * median_inplace(dev, m);
            y[t][s] = fabsf(x[t][s] - med) > HAMPEL_NSIGMA * mad ? med : x[t][s];
        }
    }

    /* 3a. V: desviación estándar temporal (poblacional) media sobre subportadoras */
    if (n > 1) {
        float acc = 0.0f;
        for (int s = 0; s < CSI_DSP_NSC; s++) {
            float mean = 0.0f;
            for (int t = 0; t < n; t++) {
                mean += y[t][s];
            }
            mean /= n;
            float var = 0.0f;
            for (int t = 0; t < n; t++) {
                float d = y[t][s] - mean;
                var += d * d;
            }
            acc += sqrtf(var / n);
        }
        out->variance = acc / CSI_DSP_NSC;
    }

    /* 3b. C: 1 - correlación media entre paquetes consecutivos */
    if (n > 1) {
        float acc = 0.0f;
        for (int t = 1; t < n; t++) {
            float ma = 0.0f, mb = 0.0f;
            for (int s = 0; s < CSI_DSP_NSC; s++) {
                ma += y[t - 1][s];
                mb += y[t][s];
            }
            ma /= CSI_DSP_NSC;
            mb /= CSI_DSP_NSC;
            float ab = 0.0f, aa = 0.0f, bb = 0.0f;
            for (int s = 0; s < CSI_DSP_NSC; s++) {
                float a = y[t - 1][s] - ma;
                float b = y[t][s] - mb;
                ab += a * b;
                aa += a * a;
                bb += b * b;
            }
            float den = sqrtf(aa * bb);
            acc += den > 0.0f ? ab / den : 1.0f;
        }
        out->decorrelation = 1.0f - acc / (n - 1);
    }

    /* 3c. tasa y RSSI */
    double span = 0.0;
    float rs = 0.0f;
    for (int t = 0; t < n; t++) {
        rs += rssi[ROW(t)];
        if (t > 0) {
            span += (double)(uint32_t)(ts_us[ROW(t)] - ts_us[ROW(t - 1)]) / 1e6;
        }
    }
    out->rssi_mean = rs / n;
    float rv = 0.0f;
    for (int t = 0; t < n; t++) {
        float d = rssi[ROW(t)] - out->rssi_mean;
        rv += d * d;
    }
    out->rssi_std = sqrtf(rv / n);
    out->rate_hz = span > 0.0 ? (float)((n - 1) / span) : 0.0f;

    /* 3d. energía por bandas: DFT real (bins 1..n/2), potencia media sobre subportadoras */
    if (bands && n >= 8 && out->rate_hz > 0.0f) {
        /* x ya no se necesita: se reutiliza para guardar y - media de cada subportadora */
        for (int s = 0; s < CSI_DSP_NSC; s++) {
            float mean = 0.0f;
            for (int t = 0; t < n; t++) {
                mean += y[t][s];
            }
            mean /= n;
            for (int t = 0; t < n; t++) {
                x[t][s] = y[t][s] - mean;
            }
        }
        float band[3] = {0};
        float total = 0.0f;
        for (int k = 1; k <= n / 2; k++) {
            float power = 0.0f;
            for (int s = 0; s < CSI_DSP_NSC; s++) {
                float re = 0.0f, im = 0.0f;
                int idx = 0;
                for (int t = 0; t < n; t++) {
                    re += x[t][s] * cos_tab[idx];
                    im -= x[t][s] * sin_tab[idx];
                    idx += k;
                    if (idx >= n) {
                        idx -= n;
                    }
                }
                power += re * re + im * im;
            }
            power /= CSI_DSP_NSC;
            total += power;
            float f = k * out->rate_hz / n;
            for (int b = 0; b < 3; b++) {
                if (f >= BANDS[b][0] && f < BANDS[b][1]) {
                    band[b] += power;
                }
            }
        }
        if (total > 0.0f) {
            out->band_1_3 = band[0] / total;
            out->band_3_10 = band[1] / total;
            out->band_10_40 = band[2] / total;
        }
    }
#undef ROW
}

/* ---------- detector ---------- */

void csi_detector_recalibrate(csi_detector_t *det)
{
    det->state = CSI_STATE_CALIBRATING;
    det->n_calib = 0;
    det->base = 0.0f;
    det->sigma = 0.0f;
    det->above = 0;
    det->below = 0;
}

void csi_detector_init(csi_detector_t *det, const csi_detector_config_t *cfg)
{
    memset(det, 0, sizeof(*det));
    det->cfg = cfg ? *cfg : csi_detector_default_config();
    if (det->cfg.window > CSI_DSP_MAX_WINDOW) {
        det->cfg.window = CSI_DSP_MAX_WINDOW;
    }
    if (det->cfg.calib_windows > CSI_DSP_MAX_CALIB) {
        det->cfg.calib_windows = CSI_DSP_MAX_CALIB;
    }
    int n = det->cfg.window;
    for (int i = 0; i < n; i++) {
        det->cos_tab[i] = (float)cos(TWO_PI * i / n);
        det->sin_tab[i] = (float)sin(TWO_PI * i / n);
    }
    csi_detector_recalibrate(det);
}

void csi_detector_thresholds(const csi_detector_t *det, float *on, float *off)
{
    const csi_detector_config_t *c = &det->cfg;
    float a = c->k_on * det->sigma, b = (c->ratio_on - 1.0f) * det->base;
    *on = det->base + (a > b ? a : b);
    a = c->k_off * det->sigma;
    b = (c->ratio_off - 1.0f) * det->base;
    *off = det->base + (a > b ? a : b);
}

void csi_detector_step(csi_detector_t *det, float score)
{
    const csi_detector_config_t *c = &det->cfg;
    if (det->state == CSI_STATE_CALIBRATING) {
        det->calib[det->n_calib++] = score;
        if (det->n_calib >= c->calib_windows) {
            float v[CSI_DSP_MAX_CALIB];
            memcpy(v, det->calib, sizeof(float) * det->n_calib);
            det->base = median_inplace(v, det->n_calib);
            for (int i = 0; i < det->n_calib; i++) {
                v[i] = fabsf(det->calib[i] - det->base);
            }
            float sigma = MAD_SCALE * median_inplace(v, det->n_calib);
            det->sigma = sigma > c->min_sigma ? sigma : c->min_sigma;
            det->state = CSI_STATE_QUIET;
        }
        return;
    }

    float on, off;
    csi_detector_thresholds(det, &on, &off);
    if (det->state == CSI_STATE_QUIET) {
        det->above = score > on ? det->above + 1 : 0;
        if (det->above >= c->n_on) {
            det->state = CSI_STATE_MOTION;
            det->below = 0;
        } else if (score <= off) {
            /* solo se aprende de ventanas claramente tranquilas */
            float dev = fabsf(score - det->base);
            det->base += c->alpha * (score - det->base);
            float sigma = det->sigma + c->alpha * (1.2533f * dev - det->sigma);
            det->sigma = sigma > c->min_sigma ? sigma : c->min_sigma;
        }
    } else {
        det->below = score < off ? det->below + 1 : 0;
        if (det->below >= c->n_off) {
            det->state = CSI_STATE_QUIET;
            det->above = 0;
        }
    }
}

bool csi_detector_push(csi_detector_t *det, const float amp[CSI_DSP_NSC], int8_t rssi, uint32_t ts_us)
{
    const int w = det->cfg.window;
    memcpy(det->amps[det->head], amp, sizeof(float) * CSI_DSP_NSC);
    det->rssi[det->head] = rssi;
    det->ts_us[det->head] = ts_us;
    det->head = (det->head + 1) % w;
    if (det->count < w) {
        det->count++;
    }
    det->since_hop++;
    if (det->count < w || det->since_hop < det->cfg.hop) {
        return false;
    }
    det->since_hop = 0;

    /* det->head apunta al paquete más antiguo de la ventana circular */
    csi_features_t f;
    csi_dsp_window_features((const float (*)[CSI_DSP_NSC])det->amps, w, det->head, det->rssi, det->ts_us, det->x,
                            det->y, det->cos_tab, det->sin_tab, det->cfg.compute_bands, &f);
    float score = det->cfg.feature == CSI_FEATURE_DECORRELATION ? f.decorrelation : f.variance;
    csi_detector_step(det, score);

    det->last.state = det->state;
    det->last.score = score;
    det->last.features = f;
    csi_detector_thresholds(det, &det->last.threshold_on, &det->last.threshold_off);
    return true;
}
