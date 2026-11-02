# Handover — Astral Chain static recompilation

State of the port for the next agent. Everything below was measured on this machine against the user's own dump. The
game data, keys and all extracted/generated files stay outside git (`build/`, `generated/`); see `AGENTS.md` for the
content rules.

Current git state when this note was written:

- `HEAD` = `52d4898`.
- Working tree clean. `docs/handover.md` is tracked.
- Untracked: `Eglantine/` (read-only reference emulator, never commit it).
- The user manages git. Do not commit `Eglantine/`, `build/` or `generated/`.
- Run `python tools/check_content.py --staged` before proposing any commit. Silent = OK.

---

## 0. Reste à faire (RAF)

1. **AOT shaders (priority 1).** The translator and the on-demand cache work, but a clean build still translates
   shaders during play. The runtime already records exactly the variants play needs and has a preparation hook; use it
   and implement/port the missing seed tooling. Details in section 6.
2. **Full `fsp-srv` save data.** `runtime/ov_fsp.c` only answers the access-log commands; `CommitSaveData` is handled by
   the host override in `runtime/fs_host.c`. That is enough for the current New Game flow but not a complete
   `IFileSystem` service. Details in section 7.
3. **Longer gameplay coverage.** End-to-end play is not verified beyond the early New Game sequence and the load-data
   screen. Run further, fix the next missing service or render issue that appears, and keep a representative slice in
   the regression runs.
4. **Support work, in this order:** `nfp:user`/amiibo, `account`/`friends` commands a longer run reaches, `prepo:u` and
   `nifm:u` kept local, shared system fonts.

The user explicitly asked for real implementations, not lazy success stubs, for every service the game needs.

Definition of done for this handover:

- The title screen, the menu and New Game are still reached, with the same controller flow.
- A fresh build folder can run with the shader cache prepared ahead of time and does not compile shaders during the
  first minutes of play.
- `--seconds` runs still complete without a fatal, and `tools/check_content.py --staged` passes.

---

## 1. Current functional state

Working:

- Boot through `nn::init::Start`, all module constructors, the entry point and the first NVN calls.
- RomFS mount, directory enumeration, `root.pkz`, all `st*.pkz`, `ui`, `um`, `wet`, `wp`, `core`, sound archives.
- Shader lookup in `shader2.dat`, VSO/PSO validation and translation (once `build/xlate/ac_xlate.exe` exists).
- Title screen, `ZL + ZR` prompt, title menu, New Game, save mount/unmount, the load-data screen; controller input.
- Vulkan rendering: 1600x900, 30 fps present loop, 26 clears/frame, ~100-130 draws/frame in the menu/early game,
  no validation errors, no shader failures in the last runs.
- Performance overlay (already adapted from TotK): `AC_PERF_OVERLAY=fps|full`, F10 / L3+R3.
- Scripted input and recording; see the controller section in `AGENTS.md`.

Not working / not verified:

- Full save-data service: `fsp-srv` only has the access-log commands; `CommitSaveData` is handled by the host override
  in `runtime/fs_host.c`. This is enough for the current New Game flow but not a complete `IFileSystem` service.
- End-to-end gameplay is not visually verified beyond the early New Game sequence and the load-data screen. The last
  scripted New Game run lasted 45 s (1351 frames, no fatal) and exercised the save system.
- No shared system fonts are present in the workspace. `nn::pl::GetSharedFont` is implemented and skips missing
  types; the game's own UI fonts still render. Put extracted `.bfttf` files in `AC_SHARED_FONTS` or
  `<romfs>/../../firmware/shared-fonts` if Chinese/Korean/system-font UI is needed.
- `nifm:u`, `prepo:u`, `nfp:user` and parts of `account`/`friends` are host-side compatibility stubs; no network,
  telemetry or NFC is emulated.

---

## 2. Environment and build commands

| What | How |
|---|---|
| Repo | `C:\Users\Sparrow\Desktop\astral-chain-pc-recomp` |
| C toolchain | MSYS2 UCRT64 clang/lld 23 at `C:\msys64\ucrt64\bin`; **never** `cl.exe` (generated C uses GNU extensions) |
| Python | `.venv` (3.12). The TotK `.venv-py314` is not needed by this port's extraction; `tools/prepare_shaders.py` from the TotK docs is missing here |
| .NET | 10.0 SDK, needed by `tools/build_xlate.py` |
| Config | `config.local.toml` (ignored): `input.base`, `input.keys`, `work.dir = 'build'` |
| Extract | `.venv\Scripts\python tools\extract.py` → `build/extracted/v0/{exefs,romfs}` |
| Shader translator | `.venv\Scripts\python tools\build_xlate.py` → `build/xlate/ac_xlate.exe` (about 15 s once NuGet is warm) |
| Generate C | `.venv\Scripts\python recomp\gen.py --exefs build\extracted\v0\exefs --out generated/v0 --jobs 16 --patches recomp\patches-v0.txt` |
| Build | `.venv\Scripts\python tools\build_game.py --version v0 --jobs 16` |
| Run | `build\v0\astralchain.exe --seconds 30 [--shot PNG]` |
| Log | `build/v0/logs/astralchain.log` (also stderr) |
| Traces | `AC_TRACE=host,gfx,kernel,svc,ipc,fs,perf,sched,present,audio` or `all`; a bare `1` is rejected |
| Content check | `python tools/check_content.py --staged` |

Important build facts:

- `tools/build_game.py` does **not** regenerate the lifted C. After changing `recomp/gen.py`, a patch table, or
  `generated/v0`, run `recomp/gen.py` first.
- `--patches recomp/patches-v0.txt` is mandatory. The file holds the 32 spin waits found by
  `tools/spin_waits.py --exefs build\extracted\v0\exefs --modules main`. Without it, clang hoists a guest spin
  loop's load and turns it into a tight `jmp $` at host `f_70003dfc50+0x70`; the game then stops making progress.
- The translator is auto-detected as the nearest `build/xlate/ac_xlate.exe` above the exe. `AC_XLATE` overrides it;
  `AC_XLATE_ID` overrides its cache identity. Keep `build/xlate/ac_xlate.id` with the exe.
- `--seconds S` ends at the first **presented** frame after the world clock passes `S`. It does not time out if the
  game never presents.
- `--shot` saves the game texture; the ImGui performance overlay is composed later and is **not** in `--shot` images.
- The game keeps running when its window loses focus (`assume_focus = 1`), as on the Switch.
- `build/` is about 9.8 GB after extraction/generation. Do not scan the whole RomFS per frame; the runtime already
  uses a prebuilt index and fault-paged image.

---

## 3. Game and platform facts

- Base title id `01007300020FA000`; update title id `01007300020FA800`. Iteration 1 targets the **base 1.0.0 only**,
  Windows x64, no 60 fps work.
- Module builds: `main` = `ed2026b20685971f8b332095a7ff80ff`, `sdk` = `e29be8ad6778527aa248310d0c71a8a5`.
  The SDK is the same in 1.0.0 and 1.0.1 according to nxnative.
- `main`: image `0xcccc000`, bss `0xbf217e0`, 337 imports, needs `nnSdk.nss`, 16 exports.
- `sdk`: image `0xc75000`, 24 737 exports. SDK 6.4.0.
- NVN ABI the game insists on: major **53**, minor **313** (the game accepts >= 310). `runtime/nvn_api_core.c`
  reports 53/313.
- No C++ exceptions or `_Unwind_*` / `longjmp` imports; only `__cxa_guard_*` and `__cxa_pure_virtual`.
  `recomp/regs.py`'s callee-saved assumptions hold.
- Memory layout (`generated/v0/layout.h`, decided only by `recomp/layout.py`):

  | Region | Base | Size |
  |---|---|---|
  | `main` | `0x7000000000` | `0xcccc000` |
  | RomFS image | `0x7000d1b000` | `0x2667f6a3c` |
  | `sdk` | `0x7267600000` | `0xc75000` |
  | kernel / helpers | `0x7268400000` | — |
  | host functions | `0x7300000000` | — |

  `RT_RET_HOST` is `0x73000ff000`.
- RomFS header (measured): metadata `0x6e25c` bytes at `0x2667887e0`; directory hash at `+0x184`, directory meta
  at `+0xbc8`, file hash at `+0x880c`, file meta at `+0x64d04`; file data at `0x200`. The four metadata tables sit
  together at the end of the image.
- The RomFS image is mapped read-faulted, not copied. `runtime/romfs.c` parses the header, maps the image at
  `ROMFS_BASE`, and serves reads. The mount cache is a small metadata cache (`0x6f000` bytes requested by the game);
  it is copied into the guest allocation directly, never page-protected (a partial-page protect broke the next
  allocation's first word).
- Root directory listing must accept `Contents:/` and nested paths with or without a trailing slash. This was a real
  bug: `Contents:/st8/` produced relative `st8/`, which never matched `st8/st8.pkz`; trimming trailing `/` fixed the
  entire asset load. Do not regress `romfs_dir_list`.

---

## 4. Code map and architecture

### Boot / CPU

- `recomp/` — NSO loader, lifter, layout, jump tables, patches, generator. Generated C is never edited by hand.
- `runtime/main.c` — process start, config, probes, `--seconds`, `--shot`.
- `runtime/boot.c` — `ldr_load`, module constructors, `nn::init::Start`, first NVN checkpoint. `--boot` stops at the
  first `nvnBootstrapLoader` call.
- `runtime/loader.c` / `ldr` — module loading, relocations, imports, exports.
- `runtime/kernel.c` — virtual cores, threads, fibers, waits, events, shared memory, SVC 0x36 preemption.
- `runtime/memory.c` — guest address space, heap, read/write faults.
- `runtime/dispatch.c` — guest address → lifted function table; host functions are hashed separately.
- `runtime/svc.c` — SVC dispatch; `runtime/ipc.c` — HIPC/CMIF/TIPC and the named-service table.

### Files

- `runtime/fs_host.c` — the port's own `nn::fs` implementation: mounts (`Contents:`, `save:`, `cache:`, `temp:`),
  file/directory handles, atomic save commits, cache storage. This is the durable save path.
- `runtime/romfs.c` — RomFS image and directory/file tables; mount cache; fault handling.
- `runtime/ov_fsp.c` — the small `fsp-srv` compatibility service (access log).
- `runtime/restbl.c` — TotK resource-size table; inert without a table, used by the RomFS mod overlay.

### Graphics

- `runtime/nvn_api_core.c` / `nvn_api_obj.c` / `nvn_api_cmd.c` / `nvn_api.h` / `nvn_obj.h` — the NVN front end:
  device/queue/window/sync, object builders, command recording, memory pools, textures.
- `runtime/vk_*.c` — Vulkan backend: execution, draw preparation, pipelines, textures, ASTC, present, memory.
- `runtime/gfx_shader.c` — shader service: translator child processes, cache keys, reflection, recorded inputs,
  preparation.
- `runtime/gfx_present.c` — swapchain/present thread and pacing.
- `runtime/vk_pipeline.c` — pipeline cache, keys, prewarm, AOT preparation, library builds.
- `runtime/vk_texture.c` / `vk_astc.c` — ASTC upload/native sampling and compute decode.

### Input / UI

- `runtime/input.c` — SDL3 gamepad, keyboard, mouse, scripted input, recording, virtual pad.
- `runtime/input_map.c` — default bindings and `AC_BIND_*`.
- `runtime/ov_input.c` — libnx `NpadState` for the game, HID services, vibration, six-axis.
- `runtime/ui/menu.cpp` — ImGui menu, performance overlay, controller/fps overlay.
- `runtime/perfmon.c` — overlay numbers.

### Services implemented / overridden

- IPC services in `runtime/ipc.c`: `audren:u`, `audout:u`, `fsp-srv`, `hid`, `hwopus`, `nifm:u`, `prepo:u`,
  `nfp:user`, `set`.
- CMIF domains are implemented minimally in `runtime/ipc.c` (`ConvertToDomain`, domain request/response headers).
  Do not remove: `prepo:u` and other services rely on it.
- Host overrides: `ov_system.c` (oe, applet/am, prepo, nfp, account, friends, time, pl fonts), `ov_input.c`,
  `ov_fs` in `fs_host.c`, `ov_gfx.c` (vi / nv allocators), `ov_media.c` (codec), `ov_settings.c`.
- `runtime/ov_nifm.c` overrides `nn::nifm::Initialize` because the SDK's service setup fails on the missing network
  domain; `runtime/ov_prepo.c` accepts play reports locally; `runtime/ov_fsp.c` answers the access-log side path.

---

## 5. Fixes that must not regress

These were each a crash/hang and are now part of the boot path:

1. **RomFS mount cache.** `ov_mount_rom` builds the metadata cache and copies it into the guest allocation with
   `mem_thaw` + `memcpy`. Never `plat_mem_protect` a guest allocation that is not page-exclusive; the next
   allocation can share the last page.
2. **RomFS root/nested listing.** Accept the mount root and trim trailing `/` in `romfs_dir_list`. Without it the file
   table stays empty and the entry point's flush crashes.
3. **Spin waits.** `recomp/patches-v0.txt` has 32 `spin main ...` lines. Generated with `--patches`. Without it the
   port hangs on a hoisted load loop.
4. **Shader GPU code minor version.** `runtime/nvn_api_core.c` devinfo `[0x30]` is **15**, not 14. Astral Chain's
   shaders are 1.15; 14 rejects every shader.
5. **Per-stage NVN programs.** Astral Chain binds a vertex program and a fragment program **separately** with stage
   masks. `nvnCommandBufferBindProgram` stores `ex->prog_stage[6]`; `shader_for`, the memo key and the descriptor
   signature use the per-stage program. Do not go back to a single `ex->prog`; that skips every draw with
   "no vertex stage".
6. **`nvnCommandBufferFenceSync`.** The backend replays submits synchronously; the sync records
   `nvn_fence_last()`. Without it starting from the title screen stops on the fence path.
7. **Fiber `GetCurrentFiber` / `SwitchToFiber(0)`.** On the thread context `GetCurrentFiber` returns the `RtThread*`
   token; `SwitchToFiber` treats it as "back to the thread context". Do not return 0.
8. **HID singular calls.** The game imports singular `GetNpadState`; the SDK's plural function is not intercepted.
   `runtime/ov_input.c` overrides both forms.
9. **Start-up service chain.** `nifm::Initialize` must return success (host override); account `OpenUser` /
   `OpenPreselectedUser` return a **Result** (0 = success), while `TryOpenPreselectedUser` returns a bool;
   `friends::UserPresence::Initialize` and `fs::EnsureSaveData` are host-overridden; `fsp-srv` 1005 must return
   success with mode 0 or `IsEnabledAccessLog` aborts.
10. **`pl:u` shared fonts.** `nn::pl::GetSharedFont` is filled directly from `.bfttf` files; missing files are skipped
    with count 0. `GetSharedFontAddress` / `Size` fail loudly if a present file is damaged.
11. **Title-to-menu.** `fsp-srv` access-log commands and `nvnCommandBufferFenceSync` are what let the `ZL+ZR` menu
    transition finish.

---

## 6. Priority 1 — AOT shaders

### 6.1 What already works

- Translator: `build/xlate/ac_xlate.exe` (3.4 MB) and `build/xlate/ac_xlate.id`. Built by
  `tools/build_xlate.py` (Ryujinx 1.3.2 + 11 patches + NativeAOT). It is auto-detected from the repo root; no
  `AC_XLATE` is needed when the layout is standard.
- On-demand translation: `runtime/gfx_shader.c` starts `ac_xlate --serve` children, caches `.spv`, `.res.json`,
  `.use` and `in/*.in` under `build/v0/shader-cache/`. Current cache has about 163 files from the title/menu runs.
- Pipeline cache: `build/v0/pipeline-cache.bin` (driver cache) and `build/v0/pipeline-keys.bin` (recorded pipeline
  keys for the boot prewarm). The prewarm rebuilds pipelines and libraries at boot.
- Recorded shaders: `build/v0/shader-answers.bin` ("ACSANS") and `build/v0/shader-programs.bin` ("ACSPRG") are written
  by play. They contain exactly the (program, answers) pairs the game asked for, not a census guess.

The per-shader cache key includes the translator identity and the answers; changing either invalidates the cache
without a manual version bump. `KEY_VERSION`/`IN_VERSION` cover layout changes on our side.

### 6.2 Existing preparation hooks

- `astralchain.exe --prepare-shaders` calls `gfx_shader_prepare_seed(dir)`:
  - reads `build/v0/seed-answers.bin` and `build/v0/seed-programs.bin` (same record formats as the recorded files);
  - translates every seed variant;
  - writes `build/v0/shader-prepared.bin` ("ACSPRP").
- `astralchain.exe --warm-shaders` reads `shader-prepared.bin` and rebuilds every variant's stage library or compute
  pipeline into the driver's disk cache, without translating again.
- `AC_TEST_PREPARE_SHADERS=1` at boot calls `gfx_shader_prepare_recorded`, which prepares **the recorded
  `shader-answers.bin`/`shader-programs.bin` pairs** at boot. This is the fastest practical path with today's data.
- `AC_PIPE_PREBUILD=0` disables the boot pipeline-key prebuild; `AC_LIB_PREBUILD=0` disables the compute/library
  prebuild. Do not disable them while measuring AOT; they are part of the goal.

Record layouts (from `runtime/gfx_shader.c`):

```text
shader-answers.bin: "ACSANS", u32 version, u32 rec_size; records:
    u32 stage, u8 code_hash[32], u8 input_id[32], u8 packed_answers[147], u8 priority_pad
shader-programs.bin: "ACSPRG", u32 version, u32 0; records:
    u32 stage, u32 length, u32 c1_length, u8 code_hash[32],
    u8 control[0x880], u8 code[length], u8 c1[c1_length]
shader-prepared.bin: "ACSPRP", u32 version, u32 rec_size(36); records:
    u8 stage, u8 priority, u8 pad[2], u8 input_id[32]
```

The seed tool writes seed records with a zero input id and the priority in the pad byte (0 title, 1 warm-up, 2 rest).
`gfx_shader_prepare_seed` translates each seed record, derives its real input id, and stores the prepared list.

### 6.3 Immediate workaround / verification

1. Run the title, menu and a representative slice of New Game long enough to populate `shader-answers.bin` and
   `shader-programs.bin` (the current files are already populated; a longer run adds field shaders).
2. Run a boot with `AC_TEST_PREPARE_SHADERS=1` and confirm the log reports translated pairs and no failures. This
   prepares the recorded pairs into the shader cache; the next boot's pipeline prewarm should have fewer misses.
3. For `--prepare-shaders`, the missing piece is the seed generator. The runtime expects `seed-answers.bin` and
   `seed-programs.bin`; the recorded files are not in the exact seed form (recorded records carry real input ids).
   Do not assume a plain file copy is a supported seed. The proper fix is the tool in 6.4.
4. Verify on a **fresh** build folder: copy the prepared cache and pipeline files, delete `shader-cache` and
   `pipeline-cache.bin` in a test folder, run `--prepare-shaders --warm-shaders`, then launch and check that the
   first minute has no shader translation stalls. Use `AC_TRACE=perf` and the overlay, and `--seconds 60`.
5. Never commit `shader-cache/`, `pipeline-cache.bin`, `shader-answers.bin`, `shader-programs.bin`,
   `shader-prepared.bin`, `pipeline-keys.bin` or `build/xlate/` — they are game-derived/ignored.

### 6.4 Proper AOT implementation

The TotK reference has the missing tooling under `refs/MacNativeGames/games/totk/scripts/`:

- `prepare_shader_seed.py` — walks the shader list and writes the seed record files;
- `shader_list.py` — the shared list of shaders/locations;
- `locate_shaders.py`, `collect_shader_issues.py`, `verify_shader_compilation.py` — diagnostics.

This port has `runtime/` support but **not** `tools/prepare_shaders.py`, `tools/shader_census.py`, or
`tools/pack_shader_cache.py` (the docs in `docs/building.md` are inherited from TotK and mention them; they are not in
this checkout). `tools/build_shaders.py` is unrelated: it compiles only the runtime's own `runtime/shaders/*.glsl`
into C headers. Decide whether to port the MNG scripts (MIT) or write a smaller Astral Chain-specific seed generator:

1. **Best AOT source:** the play-recorded `shader-answers.bin`/`shader-programs.bin`. Add a small tool that converts
   these into `seed-answers.bin`/`seed-programs.bin` (same record layouts, real program bytes, stable priority), or
   extend `gfx_shader_prepare_seed` to accept the recorded files directly. This avoids a full static shader census
   and guarantees the prepared set matches what the game asks for.
2. **Wider AOT source:** a census that extracts all Maxwell shaders from the game's archives. This is what MNG's
   `shader_census.py`/`prepare_shader_seed.py` do; it needs the game's archive reader and the same code layout
   (`control[0x880]`, `code[0x30..]`, c1 constants). It is more work but covers content not yet played.
3. **Pipeline keys:** record `pipeline-keys.bin` from a representative play session; the boot prewarm rebuilds those
   pipelines. Add the prepared shader list to `gfx_shader_warm_list` so the boot build covers both.
4. **Cache packing:** `tools/pack_shader_cache.py` is also missing. The runtime can read `shader-cache.pack`, but
   writes loose files. Port the packer only for packaging/installation, not for development.
5. **Driver crash journal:** `runtime/vk_pipeline.c` already journals per-worker variants and writes
   `shader-prepare-skip.txt` when the driver crashes. Keep that behavior; a failed preparation must be resumable.
6. **Measurement:** use `AC_TRACE=perf`, the overlay's shader-translation time, and `vk_pipeline` preparation logs.
   Acceptance: a fresh prepared folder has zero on-demand translations in the first 5 minutes, and the preparation
   itself completes without a driver crash.

Potential shortcut already in the tree: `AC_TEST_PREPARE_SHADERS=1` prepares recorded pairs at boot and is enough
for development. Treat it as the reference behavior to reproduce in `--prepare-shaders`, not as the final AOT
pipeline.

---

## 7. Other services and end-to-end work

Order after AOT:

1. **Full `fsp-srv` save data.** `runtime/ov_fsp.c` only handles access-log commands; `CommitSaveData` is overridden
   in `runtime/fs_host.c`. The host fs layer has a full atomic save transaction (`runtime/fs_host.c`), but the SDK's
   `IFileSystem` object is not served. If a later code path uses `OpenSaveDataFileSystem` + `IFileSystem::Commit`,
   implement cmd 51/52/53 and `IFileSystem` cmd 10 (`Commit`) on a session object, returning success and publishing
   the host save. The exact layouts are in the Eglantine reference (`fsp_srv.cpp`, `fs_i_filesystem.cpp`); watch
   Eglantine's cmd 22 argument-order and cmd 37 struct-size bugs.
2. **`nfp:user` / amiibo.** Current handler is a compatibility stub; if the game's New Game or menus use amiibo,
   implement the NFC service or return the documented "no reader" results consistently.
3. **`account` / `friends`.** `ov_system.c` overrides `OpenUser`, `OpenPreselectedUser`, `CloseUser`,
   `friends::UserPresence::Initialize`; check any new user/friend command that appears in a longer run.
4. **`prepo:u` / `nifm:u`.** Real play reports/network are not needed for offline play; keep them local/no-network
   and log commands. Do not replace them with a fake success that makes the game wait for data it never gets.
5. **Shared fonts.** Add `.bfttf` files via `AC_SHARED_FONTS` if system-font text is needed; the current fallback is
   intentional and does not block the English UI.

Any new service must be added to the table in `runtime/ipc.c`, declared in `runtime/ov.h`, and respect CMIF domain
requests. Unknown commands should log a backtrace and fail loudly, not return a success that leaves the game waiting
for an object or a buffer.

---

## 8. Controller and input

The full instructions are in `AGENTS.md` ("Controller"). Summary:

- Physical SDL3 gamepad works with hot-plug, both sticks, all buttons, analog ZL/ZR, rumble and gyro. No setup.
- `AC_PAD_LAYOUT=auto|nintendo|xbox`, `AC_BIND_<ACTION>` or the Buttons tab.
- Default keyboard: WASD move, arrows camera, E=A, Space=X, Shift=B, Q=L, R=R, Z=ZL, F=ZR, 1-4 D-pad, Tab=Plus,
  M=Minus; mouse left=Y, mouse right=ZL; `AC_INPUT=none` disables input.
- `AC_INPUT_SCRIPT=<file>`:
  - `<frame> <button> [hold]` in 60 Hz game ticks, or `@<ms> <button> [hold]` in world-clock milliseconds;
  - `LSTICK <x> <y> [hold]`, `RSTICK <x> <y> [hold]`;
  - buttons `A B X Y L R ZL ZR PLUS MINUS LEFT UP RIGHT DOWN LCLICK RCLICK`;
  - title example:
    ```text
    @15000 ZL 3000
    @15000 ZR 3000
    @20000 A 100
    ```
- `AC_INPUT_RECORD=<file>` records the same format; `AC_TEST_PAD=<lx>,<ly>,<rx>,<ry>` creates a virtual pad.
- `--shot` does not capture the ImGui overlay; use a window capture or inspect the overlay live.

The game reads the pad through `runtime/ov_input.c` (libnx `NpadState`) fed by `runtime/input.c`. In handheld mode
(`AC_OPERATION_MODE=handheld`) it uses id 0x20 / style 2; otherwise id 0 / full-key style 1.

---

## 9. Graphics / performance notes

- Title/menu now draws ~100-130 draws/frame; `AC_TRACE=gfx` frame lines show `draws executed/seen`. The per-stage
  program fix is the difference between `0/113` and `113/113`.
- The render-context list is at `objB = [0x7000da8000+0x640]` (0x700cc9c298): count `+0x20`, sentinel link `+0x28`,
  node payload `node+0x18`. `f_70009aba20` iterates; `f_70009aa680` checks `ctx+0x169` bit 6 and calls the context
  vtable at `ctx+0x300+0x38/0x40/0x48/0x50`. `f_70009abae0` creates a context. This is useful if a later scene
  renders black again.
- `f_70009aae40` flushes/updates the list; `f_70009aad10` checks active flags. Do not assume an empty list is always
  a bug: the title/menu initially has none until the scene is created.
- ASTC textures are everywhere. Native sampling is used when `textureCompressionASTC_LDR` is available; otherwise
  the compute decoder handles 2D. 3D ASTC cannot be sampled natively and is not decoded by the 2D path; check
  `AC_ASTC=auto`/`--probe-astc` after renderer changes.
- The Vulkan backend uses graphics pipeline libraries and a replay thread. Avoid per-frame allocations in the
  replay/draw path; use the existing counters (`AC_TRACE=perf`, overlay) and `AC_BIND_STATS`/`AC_PIPE_*` only when
  measuring.
- `vk_pipeline` boot prewarm uses `pipeline-keys.bin`; `AC_PIPE_PREBUILD=0` turns it off. `AC_LIB_PREBUILD` controls
  compute/library builds. The performance overlay shows shader translation, pipeline build, replay, upload and
  present timings.

---

## 10. Testing checklist

Run these after each significant change:

1. `python tools/check_content.py --staged` (before commit).
2. Build clean: regenerate C with `--patches`, then `tools/build_game.py`.
3. `build\v0\astralchain.exe --seconds 10 --shot build\v0\title.png`; inspect the title/menu image. It should show
   the Astral Chain logo and the `ZL + ZR` prompt, not black.
4. `build\v0\astralchain.exe --seconds 30` with `build/input_newgame2.txt`; no fatal, ~30 fps, save mount/unmount
   logs, no shader failures/validation errors. Capture a gameplay frame after a longer run.
5. AOT: fresh cache folder, `--prepare-shaders` + `--warm-shaders`, then a 60 s run; no on-demand translation
   stalls, no driver crash, prepared counts logged.
6. Controller: physical pad and an `AC_INPUT_SCRIPT` run both reach the menu; overlay F10/L3+R3 works.
7. Probes where relevant: `--selftest`, `--probe-loader`, `--probe-kernel`, `--probe-ipc`, `--probe-nvn`,
   `--probe-gfx-abi`, `--probe-shader`, `--probe-astc`, `--probe-window`, `--probe-dpi`.

### Debug tips

- Log: `build/v0/logs/astralchain.log`.
- `AC_TRACE=ipc` prints service/command/result lines (the first stop for a missing service command).
- `AC_TRACE=gfx` prints per-frame submit/draw/clear counts and NVN first calls.
- `AC_TRACE=perf` prints periodic fps/frame-time lines.
- `AC_CORE_DIAG=1` explains core waits; `AC_TRACE=sched` gives per-thread accounting. Do not leave them on for
  performance measurements.
- `build/find_map.py <rva>` maps host RVAs against `build/v0/totk.map`; `build/find_sym.py` and
  `build/dump_vtable*.py` were used for SDK symbols/vtables. These are scratch scripts under `build/`, not part of
  the repo.
- Host PC `exe+0xd38240` in logs maps to `f_70003dfc50+0x70`, the hoisted spin loop; seeing it means the spin patch
  table was not applied or the generated C was rebuilt without `--patches`.

---

## 11. Pitfalls and invariants

- Generated C is never hand-edited. Change `recomp/` and regenerate. The generator's marker must stay on every output.
- `recomp/layout.py` alone decides module bases. Do not hardcode addresses outside the generated `layout.h` where a
  layout query exists.
- C toolchain is MSYS2 UCRT64 clang; `cl.exe` cannot compile the GNU extensions in generated C.
- `write` tool may prepend a UTF-8 BOM; strip it for files that are parsed/compared byte-for-byte.
- `plat_mem_protect` works per page. Protecting part of a page affects neighboring allocations; the RomFS cache bug
  is the canonical example.
- `RT_RET_HOST`/host function addresses are outside the modules; `rt_dispatch` must resolve them through the host
  hash table, not the module tables.
- SDK-internal functions are not imports. Host overrides catch imported symbols; if the SDK calls an internal
  function that opens a service (e.g. singular `GetNpadState` or the `prepo` shim), implement the service/IPC side,
  not just the import.
- CMIF domains are required for some services. `runtime/ipc.c` has a minimal domain implementation; keep it and
  extend it rather than refusing `ConvertToDomain`.
- Async paths (device playback, shader translation) must not block IPC handlers.
- No game data in git. `build/`, `generated/`, `shader-cache`, pipeline caches, seeds and screenshots stay out;
  `Eglantine/` stays untracked.

---

## 12. Reference material

- `docs/architecture.md` — design of the port.
- `docs/building.md` — toolchain, build, probes, shader preparation (some TotK-only tool names are stale here).
- `docs/maxwell.md` — Maxwell behaviour the Vulkan path must match.
- `docs/astral-chain.md` — Astral Chain port notes, RomFS/address facts.
- `AGENTS.md` — priorities, content rules, controller instructions, Eglantine note.
- `refs/` — MIT/BSD upstreams (TotK/MNG, LAS Recomp, nxnative, d2r-mobile) and the pinned Ryujinx translator.
- `Eglantine/` — read-only GPL reference emulator for service behaviour (fsp-srv, HID, NVN sync/present). Use it for
  layouts/semantics, write our own code.
