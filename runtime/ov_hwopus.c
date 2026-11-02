// The hardware Opus decoder service ("hwopus").
//
// Astral Chain reaches nn::codec through the SDK's HardwareOpusDecoder C++ class, whose constructor talks to the
// hwopus service over IPC. TotK imported the nn::codec functions directly and the host replaced them in ov_media.c;
// this port's SDK builds its own decoder client, so the service itself has to answer. Commands are added as the boot
// reports them.
#include <stdint.h>
#include <string.h>

#include "host.h"
#include "ipc.h"
#include "ov.h"

// libopus stereo decoder state plus the guest's own work area; the same size ov_media.c hands the direct nn::codec
// callers.
#define HWOPUS_WORK_SIZE 0x9000u

void hwopus_server_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    switch (rq->cmd) {
    case 1: {   // GetWorkBufferSize(NN_sample_rate, channel_count) -> u32 bytes
        uint32_t rate = 0, channels = 0;
        if (rq->data_size >= 8) memcpy(&rate, ipc_arg(rq, 0, 4), 4), memcpy(&channels, ipc_arg(rq, 4, 4), 4);
        rt_log("hwopus: GetWorkBufferSize(%u, %u)", rate, channels);
        uint32_t size = HWOPUS_WORK_SIZE;
        IPC_OUT(rs, size);
        return;
    }
    default: ipc_unimplemented(s, rq);
    }
}
