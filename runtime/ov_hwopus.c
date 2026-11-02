// The hardware Opus decoder service ("hwopus").
//
// Astral Chain reaches nn::codec through the SDK's HardwareOpusDecoder C++ class, whose constructor opens this service
// and hands it a transfer memory for the decoder's work area. The decode itself runs here, on the host, with libopus;
// the guest work buffer is reserved by the SDK and left unused because libopus keeps its state in host memory.
//
// The packet on the wire is Nintendo's Opus frame: an 8-byte big-endian header {payload size, final range} followed by
// the Opus packet. The returned data size counts the header, which is how the caller advances through the stream.
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <opus/opus.h>

#include "host.h"
#include "ipc.h"
#include "ov.h"
#include "platform/platform.h"

#define HWOPUS_MAX_SESSIONS 8
#define HWOPUS_R_INVALID_ARGUMENT 0x1FCD1u   // nn::codec's "invalid argument"
#define HWOPUS_R_OUT_OF_RESOURCE 0xC401u
#define HWOPUS_LARGE_FRAME_SAMPLES 5760      // 60 ms at 48 kHz, the largest frame a decoder can produce

// One guest decoder: libopus state plus the parameters it was opened with. A decoder's own lock serialises its libopus
// state so different streams decode in parallel.
typedef struct {
    OpusDecoder *dec;
    int rate, channels;
    PlatMutex use;
    volatile int32_t refs;
    int logged;
} HwOpusDecoder;

static HwOpusDecoder *g_decoders[HWOPUS_MAX_SESSIONS];
static PlatMutex g_decoders_lock = PLAT_MUTEX_INIT;
static volatile int32_t g_decoders_live;

static int valid_format(int rate, int channels) {
    return (rate == 48000 || rate == 24000 || rate == 16000 || rate == 12000 || rate == 8000) &&
           (channels == 1 || channels == 2);
}

static void decoder_unref(HwOpusDecoder *d) {
    if (plat_dec32(&d->refs)) return;
    opus_decoder_destroy(d->dec);
    free(d);
}

// The work buffer the SDK reserves for us. libopus keeps its state on the host, so this only has to cover a decoder
// instance and the staging space a large frame needs; the SDK rounds it up to a page.
static uint32_t work_size(int rate, int channels) {
    if (!valid_format(rate, channels)) return 0;
    int state = opus_decoder_get_size(channels);
    uint32_t bytes = (uint32_t)state + (uint32_t)(HWOPUS_LARGE_FRAME_SAMPLES * 2 * channels) + 0x600u;
    return (bytes + 0xFFFu) & ~0xFFFu;
}

static uint32_t be32(const uint8_t *p) {
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

// A decode request carries the PCM destination and the Opus packet. nn::sf maps an AutoSelect output buffer to a B (or
// receive) descriptor and an AutoSelect input to an A or a static X one, so the direction picks them apart; when only one
// kind is present the larger buffer is the PCM destination.
static void decode_buffers(const IpcRequest *rq, const IpcBuffer **out, const IpcBuffer **in) {
    const IpcBuffer *b = rq->nb && rq->b[0].size ? &rq->b[0] : NULL;
    const IpcBuffer *c = rq->nc && rq->c[0].size ? &rq->c[0] : NULL;
    const IpcBuffer *a = rq->na && rq->a[0].size ? &rq->a[0] : NULL;
    const IpcBuffer *x = rq->nx && rq->x[0].size ? &rq->x[0] : NULL;
    const IpcBuffer *w = rq->nw && rq->w[0].size ? &rq->w[0] : NULL;
    *out = b ? b : c ? c : NULL;
    *in = a ? a : x ? x : w ? w : NULL;
    if (!*out && !*in) {   // one descriptor kind only: the bigger one is the PCM destination
        const IpcBuffer *only[3] = {a, x, w};
        for (int i = 0; i < 3; i++) {
            if (!only[i]) continue;
            if (!*out || only[i]->size > (*out)->size) *out = only[i];
        }
        for (int i = 0; i < 3; i++)
            if (only[i] && only[i] != *out) *in = only[i];
    } else if (!*out) {
        *out = *in;
        *in = NULL;
    } else if (!*in) {
        *in = *out;
        *out = NULL;
    }
}

// Decodes one Nintendo Opus frame into the caller's PCM buffer.
//
// The three out parameters are written at the offsets the SDK's client reads them from. Its nn::codec wrapper asks for
// them in the order (data_size, time_taken, sample_count); with the SDK's 8-byte alignment that puts data_size at 0,
// time_taken at 8 and sample_count at 0x10. sample_count is also written at 4, which is where it lands if the response
// is packed without alignment, so either layout decodes to the same audio.
static void decoder_decode(HwOpusDecoder *d, const IpcRequest *rq, IpcResponse *rs, int has_perf, int has_reset) {
    const IpcBuffer *out = NULL, *in = NULL;
    decode_buffers(rq, &out, &in);
    if (!d->logged && (rt_trace & RT_TRACE_AUDIO)) {
        d->logged = 1;
        rt_log("hwopus: first decode cmd %u: out %#llx+%#llx, in %#llx+%#llx (x%u a%u b%u w%u c%u data %u)", rq->cmd,
               (unsigned long long)(out ? out->addr : 0), (unsigned long long)(out ? out->size : 0),
               (unsigned long long)(in ? in->addr : 0), (unsigned long long)(in ? in->size : 0), rq->nx, rq->na,
               rq->nb, rq->nw, rq->nc, rq->data_size);
    }
    if (!out || !out->size || !in || in->size < 8) {
        rt_log("hwopus: decode with out %llu bytes and in %llu bytes", (unsigned long long)(out ? out->size : 0),
               (unsigned long long)(in ? in->size : 0));
        rs->result = HWOPUS_R_INVALID_ARGUMENT;
        return;
    }
    const uint8_t *src = ipc_guest(in->addr, in->size);
    uint32_t payload = be32(src), range = be32(src + 4);
    if (payload > in->size - 8) {
        rt_log("hwopus: packet header says %u bytes, the request holds %llu", payload,
               (unsigned long long)(in->size - 8));
        rs->result = HWOPUS_R_INVALID_ARGUMENT;
        return;
    }
    uint8_t reset = 0;
    if (has_reset && rq->data_size >= 1) memcpy(&reset, rq->data, 1);

    int16_t *dst = ipc_guest(out->addr, out->size);
    int capacity = (int)(out->size / (sizeof(int16_t) * (size_t)d->channels));
    if (capacity > HWOPUS_LARGE_FRAME_SAMPLES) capacity = HWOPUS_LARGE_FRAME_SAMPLES;

    uint64_t start = kern_now_ns();
    plat_mutex_lock(&d->use);
    if (reset) opus_decoder_ctl(d->dec, OPUS_RESET_STATE);
    int got = opus_decode(d->dec, src + 8, (opus_int32)payload, dst, capacity, 0);
    opus_uint32 final = 0;
    if (got >= 0) opus_decoder_ctl(d->dec, OPUS_GET_FINAL_RANGE(&final));
    plat_mutex_unlock(&d->use);
    uint64_t taken = kern_now_ns() - start;

    if (got < 0) {
        rt_log("hwopus: opus_decode: %s (%u bytes)", opus_strerror(got), payload);
        rs->result = HWOPUS_R_INVALID_ARGUMENT;
        return;
    }
    if (payload && range && final != range && !d->logged) {
        d->logged = 1;
        rt_log("hwopus: Opus final range %#x != stream %#x (logged once)", (unsigned)final, (unsigned)range);
    }
    uint32_t data_size = payload + 8;
    uint32_t samples = (uint32_t)got;
    uint8_t reply[0x14] = {0};
    memcpy(reply + 0x00, &data_size, 4);
    memcpy(reply + 0x04, &samples, 4);
    if (has_perf) {
        uint64_t time_taken = taken / 1000;   // microseconds, as the hardware decoder reports
        memcpy(reply + 0x08, &time_taken, 8);
    }
    if (has_perf) memcpy(reply + 0x10, &samples, 4);
    ipc_out(rs, reply, has_perf ? sizeof reply : 8);
}

static void decoder_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    HwOpusDecoder *d = s->state;
    switch (rq->cmd) {
    case 0:   // DecodeInterleavedOld
        decoder_decode(d, rq, rs, 0, 0);
        return;
    case 1:   // SetContext: a hardware decoder state blob, which a software decoder does not carry
        if (!d->logged) {
            d->logged = 1;
            rt_log("hwopus: SetContext with %llu bytes is not needed by the host decoder",
                   (unsigned long long)(rq->data_size ? rq->data_size : 0));
        }
        return;
    case 4:   // DecodeInterleavedWithPerfOld
        decoder_decode(d, rq, rs, 1, 0);
        return;
    case 6:   // DecodeInterleavedWithPerfAndResetOld: what nn::codec::HardwareOpusDecoder sends
        decoder_decode(d, rq, rs, 1, 1);
        return;
    case 8:   // DecodeInterleaved
        decoder_decode(d, rq, rs, 1, 1);
        return;
    default:
        ipc_unimplemented(s, rq);
    }
}

static void decoder_close(void *state) {
    HwOpusDecoder *d = state;
    plat_mutex_lock(&g_decoders_lock);
    for (int i = 0; i < HWOPUS_MAX_SESSIONS; i++)
        if (g_decoders[i] == d) g_decoders[i] = NULL;
    plat_mutex_unlock(&g_decoders_lock);
    plat_dec32(&g_decoders_live);
    rt_log("hwopus: decoder closed (%d Hz, %d channels)", d->rate, d->channels);
    decoder_unref(d);
}

static void open_decoder(const IpcRequest *rq, IpcResponse *rs) {
    uint32_t rate = 0, channels = 0, work = 0;
    if (rq->data_size >= 8) {
        memcpy(&rate, rq->data, 4);
        memcpy(&channels, rq->data + 4, 4);
    }
    if (rq->data_size >= 12) memcpy(&work, rq->data + 8, 4);
    if (!valid_format((int)rate, (int)channels)) {
        rt_log("hwopus: OpenHardwareOpusDecoder(%u Hz, %u channels) is not a format libopus takes", rate, channels);
        rs->result = HWOPUS_R_INVALID_ARGUMENT;
        return;
    }
    if (!rq->ncopy || !kern_handle_get(rq->copy[0], KERN_TMEM)) {
        rt_log("hwopus: OpenHardwareOpusDecoder without its transfer memory");
        rs->result = HWOPUS_R_INVALID_ARGUMENT;
        return;
    }
    if (plat_cas32(&g_decoders_live, 0, 0) >= HWOPUS_MAX_SESSIONS) {
        rt_log("hwopus: OpenHardwareOpusDecoder with %d decoders already open", HWOPUS_MAX_SESSIONS);
        rs->result = HWOPUS_R_OUT_OF_RESOURCE;
        return;
    }
    int err = 0;
    OpusDecoder *dec = opus_decoder_create((int)rate, (int)channels, &err);
    if (!dec || err != OPUS_OK) {
        rt_log("hwopus: opus_decoder_create(%u, %u): %s", rate, channels, opus_strerror(err));
        rs->result = HWOPUS_R_INVALID_ARGUMENT;
        return;
    }
    HwOpusDecoder *d = calloc(1, sizeof *d);
    if (!d) rt_fatal("hwopus: decoder allocation");
    plat_mutex_init(&d->use);
    d->dec = dec;
    d->rate = (int)rate;
    d->channels = (int)channels;
    d->refs = 1;
    int slot = -1;
    plat_mutex_lock(&g_decoders_lock);
    for (int i = 0; i < HWOPUS_MAX_SESSIONS && slot < 0; i++)
        if (!g_decoders[i]) slot = i;
    if (slot >= 0) g_decoders[slot] = d;
    plat_mutex_unlock(&g_decoders_lock);
    if (slot < 0) {
        decoder_unref(d);
        rs->result = HWOPUS_R_OUT_OF_RESOURCE;
        return;
    }
    plat_inc32(&g_decoders_live);
    rs->move[rs->nmove++] = ipc_session_new("IHardwareOpusDecoder", decoder_handler, d, decoder_close);
    rt_log("hwopus: decoder open %u Hz x%u, work buffer %u bytes (libopus keeps its state on the host)", rate, channels,
           work);
}

void hwopus_server_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    (void)s;
    switch (rq->cmd) {
    case 0:   // OpenHardwareOpusDecoder
        open_decoder(rq, rs);
        return;
    case 1: {   // GetWorkBufferSize(rate, channels) -> u32
        uint32_t rate = 0, channels = 0;
        if (rq->data_size >= 8) {
            memcpy(&rate, rq->data, 4);
            memcpy(&channels, rq->data + 4, 4);
        }
        uint32_t size = work_size((int)rate, (int)channels);
        IPC_OUT(rs, size);
        return;
    }
    case 5: {   // GetWorkBufferSizeEx(OpusParametersEx): the same with a large-frame flag
        uint32_t rate = 0, channels = 0;
        if (rq->data_size >= 8) {
            memcpy(&rate, rq->data, 4);
            memcpy(&channels, rq->data + 4, 4);
        }
        uint32_t size = work_size((int)rate, (int)channels);
        IPC_OUT(rs, size);
        return;
    }
    default:
        // Commands 2, 3, 6, 7, 8 and 9 are the multi-stream decoder, which needs a stream mapping and a libopus
        // multistream decoder. This game opens the plain stereo decoder only; fail loudly if that ever changes.
        ipc_unimplemented(s, rq);
    }
}
