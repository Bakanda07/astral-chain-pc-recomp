// The settings service ("set", settings:u) for Astral Chain 1.0.0.
//
// At boot the game's language setup calls ISettingsServer::MakeLanguageCode through the SDK's hipc2 client, and the
// SDK only reached "set" through sm:, so this service is the first thing the game needs that TotK never did (TotK's
// SDK took nn::oe::GetDesiredLanguage instead). The commands served are the ones nn::settings uses; every other
// command is a named fatal so the next missing one reports its id instead of failing silently.
//
// LanguageCode values are the plain nn::settings::Language indexes (ja=0 .. pt-BR=17); the host language comes from
// ov_system.c ov_language(), the same source as nn::oe::GetDesiredLanguage.
#include <stdint.h>
#include <string.h>

#include "host.h"
#include "ipc.h"
#include "ov.h"

// The nn::settings::Language index for the game language ov_language() chose; en-US for a language outside the enum.
static int32_t game_language(void) {
    const char *code = ov_language();
    static const struct { const char *tag; int32_t idx; } table[] = {
        {"ja", 0},     {"en-US", 1}, {"fr", 2},       {"de", 3},    {"it", 4},     {"es", 5},
        {"zh-CN", 6},  {"ko", 7},    {"nl", 8},       {"pt", 9},    {"ru", 10},    {"zh-TW", 11},
        {"en-GB", 12}, {"fr-CA", 13}, {"es-419", 14}, {"zh-Hans", 15}, {"zh-Hant", 16}, {"pt-BR", 17},
    };
    for (size_t i = 0; i < sizeof table / sizeof *table; i++)
        if (!strcmp(code, table[i].tag)) return table[i].idx;
    return 1;
}

void settings_server_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs) {
    (void)s;
    switch (rq->cmd) {
    case 2: {   // GetAvailableLanguageCodes2 -> s32 count (the codes buffer is the client's own; zeros there are valid ja)
        int32_t n = 18;
        IPC_OUT(rs, n);
        return;
    }
    case 5: {   // MakeLanguageCode(s32 language) -> u64 LanguageCode (hipc2 ISettingsServer numbering)
        int32_t l = 0;
        memcpy(&l, ipc_arg(rq, 0, 4), 4);
        rt_log("set: MakeLanguageCode(%d)", l);
        uint64_t v = (uint64_t)(uint32_t)l;
        IPC_OUT(rs, v);
        return;
    }
    default: ipc_unimplemented(s, rq);
    }
}
