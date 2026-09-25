/*
 * Corre csi_dsp en la PC para compararlo con la versión de Python (host/tests/test_csi_dsp.py).
 *
 * Entrada (binario, little-endian):  int32 n, int32 feature, luego n paquetes de
 *   int8 raw[128], uint8 first_word_invalid, int8 rssi, uint32 ts_us
 * Salida: por cada decisión  int32 índice_paquete, int32 estado, float score, on, off,
 *   float features[8], y al final float amplitudes[n][51] (para comparar el cálculo de amplitud).
 */
#include <stdio.h>
#include <stdlib.h>

#include "csi_dsp.h"

static csi_detector_t det;

int main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "uso: %s entrada.bin salida.bin\n", argv[0]);
        return 2;
    }
    FILE *in = fopen(argv[1], "rb");
    FILE *out = fopen(argv[2], "wb");
    if (!in || !out) {
        return 1;
    }
    int32_t n, feature;
    if (fread(&n, 4, 1, in) != 1 || fread(&feature, 4, 1, in) != 1) {
        return 1;
    }
    csi_detector_config_t cfg = csi_detector_default_config();
    cfg.feature = (csi_feature_sel_t)feature;
    csi_detector_init(&det, &cfg);

    float(*all)[CSI_DSP_NSC] = malloc(sizeof(float) * CSI_DSP_NSC * (size_t)n);
    for (int32_t i = 0; i < n; i++) {
        int8_t raw[128];
        uint8_t fwi;
        int8_t rssi;
        uint32_t ts;
        if (fread(raw, 1, 128, in) != 128 || fread(&fwi, 1, 1, in) != 1 || fread(&rssi, 1, 1, in) != 1 ||
            fread(&ts, 4, 1, in) != 1) {
            return 1;
        }
        csi_dsp_amplitude(raw, 128, fwi, all[i]);
        if (csi_detector_push(&det, all[i], rssi, ts)) {
            int32_t head[2] = {i, (int32_t)det.last.state};
            float vals[3] = {det.last.score, det.last.threshold_on, det.last.threshold_off};
            fwrite(head, 4, 2, out);
            fwrite(vals, 4, 3, out);
            fwrite(&det.last.features, sizeof(csi_features_t), 1, out);
        }
    }
    fwrite(all, sizeof(float) * CSI_DSP_NSC, (size_t)n, out);
    fclose(out);
    fclose(in);
    free(all);
    return 0;
}
