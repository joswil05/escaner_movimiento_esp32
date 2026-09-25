#include "csi_proto.h"

#include <string.h>

uint16_t csi_proto_crc16(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

size_t csi_proto_build(uint8_t type, const void *part1, size_t len1, const void *part2, size_t len2,
                       uint8_t *out, size_t out_size)
{
    size_t len = len1 + len2;
    if (len > CSI_FRAME_MAX_PAYLOAD || out_size < len + CSI_FRAME_OVERHEAD) {
        return 0;
    }
    out[0] = (uint8_t)(CSI_FRAME_MAGIC & 0xFF);
    out[1] = (uint8_t)(CSI_FRAME_MAGIC >> 8);
    out[2] = CSI_FRAME_VERSION;
    out[3] = type;
    out[4] = (uint8_t)(len & 0xFF);
    out[5] = (uint8_t)(len >> 8);
    if (len1) {
        memcpy(out + CSI_FRAME_HEADER_LEN, part1, len1);
    }
    if (len2) {
        memcpy(out + CSI_FRAME_HEADER_LEN + len1, part2, len2);
    }
    uint16_t crc = csi_proto_crc16(out + 2, 4 + len);
    out[CSI_FRAME_HEADER_LEN + len] = (uint8_t)(crc & 0xFF);
    out[CSI_FRAME_HEADER_LEN + len + 1] = (uint8_t)(crc >> 8);
    return len + CSI_FRAME_OVERHEAD;
}
