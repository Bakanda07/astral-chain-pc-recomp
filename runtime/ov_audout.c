// The audio output service ("audout:u") for Astral Chain 1.0.0.
//
// The intro menu does not need sound, and the host has no audio device. The game must see an output service that
// exists but reports no usable device: ListAudioOuts returns zero names and OpenAudioOut fails with the SDK's
// "device not found" result, which the game already handles by running without audio. Returning a session instead
// makes nn::audio::OpenDefaultAudioOut dereference an object it never finished initializing, so it is not offered
// until the IAudioOut command set is implemented completely.
#include <stdint.h>

#include "host.h"
#include "ipc.h"
#include "ov.h"

void audout_manager_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    (void)s;
    static int logs;
    if (logs < 40) {
        rt_log("audout:u: command %u", rq->cmd);
        logs++;
    }
    switch (rq->cmd) {
    case 0: {   // ListAudioOuts: no device
        uint32_t n = 0;
        IPC_OUT(rs, n);
        return;
    }
    case 1:   // OpenAudioOut: no device
        rs->result = 0xE401;
        return;
    default:
        break;
    }
}
