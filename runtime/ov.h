// Shared by the system overrides: runtime/ov_system.c, ov_input.c, ov_media.c and ov_gfx.c, and their probe.
// oe_push_message, oe_set_focus and ov_nv_state are in gfx.h (the window posts focus messages, the NVN layer
// allocates through the recorded callbacks).
#pragma once
#include <stddef.h>
#include <stdint.h>

#include "gfx.h"
#include "ipc.h"

// ---- ov_system.c
int ov_handheld(void);                     // AC_OPERATION_MODE=handheld (default docked); fatal on another value
const char *ov_language(void);             // the game's language, a Switch language code ("en-US", "zh-Hans", ...)

// ---- ov_settings.c
void settings_server_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs);   // "set" (settings:u)

// ---- ov_hid.c
void hid_server_handler(IpcSession *s, const IpcRequest *rq, IpcResponse *rs);   // "hid" (IHidServer)
const char *ov_shared_font_dir(char *buf, size_t n);   // AC_SHARED_FONTS, else <romfs>/../../firmware/shared-fonts
uint64_t ov_bfttf_size(const uint8_t *p, uint64_t len); // decoded font size of a BFTTF image, 0 if it is not one
