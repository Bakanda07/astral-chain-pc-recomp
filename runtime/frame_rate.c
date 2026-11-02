// Frame rate: the frame limit and the world clock, kept from the TotK port (MacNativeGames games/totk/runtime/
// game_patches.c @ ebe621d, MIT, Copyright (c) 2026 MacNativeGames contributors) but without its patch sets.
// Astral Chain 1.0.0 has no frame-rate patch table: rt_patch_set() returns -1, the game's adaptive
// present-interval controller steps by whole 60 Hz vsyncs at its shipping 30 fps, and the host never writes a
// patch page.
//
// What remains:
//   - the frame limit (AC_FPS_LIMIT): with no patches the pacer (frame_step_cap_ns) alone cannot speed the game
//     up; the game paces itself. The limit defaults to 60.
//   - the world clock (frame_step_world_us): wall time from the first present. Recorded and scripted input
//     (input.c) runs on it, so a replay presses at the same game time at any frame rate.
//
// AC_TRACE=perf adds a line per 120 presents: fps and the game seconds stepped against wall seconds.
#include <math.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cfg.h"
#include "gfx.h"
#include "host.h"
#include "platform/platform.h"

#define STEP_MAX_S (1.0 / 15.0)    // longest step; a longer frame slows the game down
#define STEP_RESET_S 0.25          // a gap this long (loading, a debugger) restarts the average

static double step_now;   // the step the game used this frame (whole vsyncs: interval / 60)
static uint64_t last_ns;

static void frame_limit_live(void);

void frame_step_init(void) {
    rt_log("frame rate: no patch table, the game paces itself at its shipping frame rate");
    frame_limit_live();
}

int frame_step_realtime(void) { return 0; }

// The frame limit (menu, AC_FPS_LIMIT): 30..240 or display. Without a patch set the game's own interval decides
// the actual rate; the pacer (nvn_api_obj.c) holds frames to the limit where the game presents faster than it.
// Unset, the limit is 60.
#define LIMIT_MIN_HZ 30
#define LIMIT_MAX_HZ 240
static int limit_hz = -1;   // 0: display; -1 before the first read
static unsigned limit_seen;
static int limit_read;

static int limit_parse(void) {
    const char *e = cfg_get("AC_FPS_LIMIT");
    if (!e || !*e) return 60;
    if (!strcmp(e, "display")) return 0;
    char *end;
    long n = strtol(e, &end, 10);
    if (!*end && n > LIMIT_MAX_HZ) {
        rt_log("frame rate: AC_FPS_LIMIT=%s is above %d; %d", e, LIMIT_MAX_HZ, LIMIT_MAX_HZ);
        return LIMIT_MAX_HZ;
    }
    if (!*end && n >= LIMIT_MIN_HZ) return (int)n;
    rt_log("frame rate: AC_FPS_LIMIT=%s is not %d..%d or display; 60", e, LIMIT_MIN_HZ, LIMIT_MAX_HZ);
    return 60;
}

static void frame_limit_live(void) {
    unsigned v = cfg_version();
    if (limit_read && v == limit_seen) return;
    limit_read = 1;
    limit_seen = v;
    int hz = limit_parse();
    if (hz == limit_hz) return;
    limit_hz = hz;
    if (hz) rt_log("frame rate: limit %d fps", hz);
    else if (gfx_window_refresh_hz() > 0) rt_log("frame rate: limit at the monitor's refresh rate (%.3f Hz now)", gfx_window_refresh_hz());
    else rt_log("frame rate: limit at the monitor's refresh rate (60 until the window measures it)");
}

uint64_t frame_step_cap_ns(void) {
    frame_limit_live();
    double hz = limit_hz ? limit_hz : gfx_window_refresh_hz();
    if (hz < LIMIT_MIN_HZ) hz = 60;   // display rate unknown (no window yet)
    if (hz > LIMIT_MAX_HZ) hz = LIMIT_MAX_HZ;
    return (uint64_t)(1e9 / hz + 0.5);
}

// The frame rate the limit gives, for the performance overlay: the setting, the monitor's rate for "display", 60
// at most without a patch set; 0 before the first frame read the setting.
double frame_step_limit_hz(void) {
    int hz = limit_hz;
    if (hz < 0) return 0;
    double r = hz ? hz : gfx_window_refresh_hz();
    if (r < LIMIT_MIN_HZ) r = 60;
    return r > LIMIT_MAX_HZ ? LIMIT_MAX_HZ : r;
}

// ---- AC_TRACE=perf speed lines
static uint64_t win_t0, win_frames, win_hist[4];   // win_hist: frames by present interval 1, 2, 3+ ([0] unused)
static double win_game;

static void speed_report(uint64_t now, double step, int interval) {
    if (!win_t0) {
        win_t0 = now;
        return;
    }
    win_frames++;
    win_game += step;
    win_hist[interval < 1 ? 1 : interval > 3 ? 3 : interval]++;
    if (win_frames < 120) return;
    double wall = (double)(now - win_t0) * 1e-9;
    rt_log("fps: %llu frames in %.3f s (%.1f fps), %.3f s game stepped, speed %.3f; interval 1/2/3+ %llu/%llu/%llu",
           (unsigned long long)win_frames, wall, (double)win_frames / wall, win_game, win_game / wall,
           (unsigned long long)win_hist[1], (unsigned long long)win_hist[2], (unsigned long long)win_hist[3]);
    win_t0 = now;
    win_frames = 0;
    win_game = 0;
    memset(win_hist, 0, sizeof win_hist);
}

static _Atomic int64_t world_us = -1;
static _Atomic uint64_t game_us;   // game time stepped since the first present (frame_step_ticks)
static uint64_t presents;

int64_t frame_step_world_us(void) { return atomic_load_explicit(&world_us, memory_order_relaxed); }
uint64_t frame_step_ticks(void) { return atomic_load_explicit(&game_us, memory_order_relaxed) * 60 / 1000000; }

static void world_clock(double dt, double step) {
    presents++;
    int64_t w = atomic_load_explicit(&world_us, memory_order_relaxed);
    if (w < 0) {
        rt_log("frame step: world clock starts at present %llu, %.2f s after the guest started",
               (unsigned long long)presents,
               rt_guest_start_ns ? (kern_now_ns() - rt_guest_start_ns) / 1e9 : 0.0);
        atomic_store_explicit(&world_us, 0, memory_order_relaxed);
        return;
    }
    if (!frame_step_realtime()) step = dt > STEP_MAX_S ? STEP_MAX_S : dt;   // whole-vsync steps: wall time
    atomic_store_explicit(&world_us, w + (int64_t)(step * 1e6 + 0.5), memory_order_relaxed);
}

void frame_step_present(uint64_t display_ns, int interval) {
    frame_limit_live();
    double dt = last_ns ? (double)(display_ns - last_ns) * 1e-9 : 0;
    if (interval > 0) step_now = interval / 60.0;
    last_ns = display_ns;
    // The game clock of untimed script lines: what the game stepped this frame, whole vsyncs.
    double game = step_now;
    atomic_store_explicit(&game_us, atomic_load_explicit(&game_us, memory_order_relaxed) + (uint64_t)(game * 1e6 + 0.5),
                          memory_order_relaxed);
    world_clock(dt, game);
    if (rt_trace & RT_TRACE_PERF) speed_report(display_ns, game, interval);
}
