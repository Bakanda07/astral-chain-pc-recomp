# Astral Chain port notes

Working notes for porting the TotK Recomp pipeline to Astral Chain 1.0.0 (01007300020FA000). Facts marked
"nxnative" come from the MIT nxnative project's game profile; they apply to 1.0.1 and need re-verification
against our 1.0.0 base game.

## Iteration 1 scope

Base 1.0.0 only, no update, no 60 fps, stop at the title screen. Windows only.

## Verified from the user's dump (base 1.0.0)

- ExeFS modules: `main` (7 644 617 B), `sdk` (5 231 344 B), `rtld`, `main.npdm`. No `subsdk0`.
- main.npdm: main thread priority 44, core 0, stack 0x100000 (matches `runtime/kernel.c` MAIN_*).
- RomFS: 8 701 files, 10 309 560 892 B.
- Ticketless dump (key-area AES-CTR); no hactool needed for the base game.

## Textures: ASTC

Astral Chain stores most textures as ASTC (PlatinumGames pipeline). The host covers the full NVN ASTC set
(runtime/nvn.h, formats 0x79-0x94: 14 LDR + 14 sRGB block sizes) and decodes on the GPU when the device lacks
native support (runtime/vk_astc.c: `AC_ASTC=auto|native|gpu|cpu|check`, `AC_ASTC_BC=1` re-encodes to BC3).
The Intel Arc 140T reports textureCompressionASTC_LDR, so `auto` samples natively.

Watch at runtime:
- ASTC **3D** textures: Vulkan has no native 3D ASTC; the gpu/cpu decoder handles 2D only. If the game uploads
  ASTC 3D (NVNtextureType 3D), the upload path must decode it (nvxnative notes do not mention any).
- sRGB ASTC: mapped; verify the game's linear/sRGB expectations match the TotK behaviour (nvn_api_tex.c).

## Game facts to re-verify (from nxnative's 1.0.1 profile)

- SDK 6.4.0, NVN, PlatinumGames engine, Wwise audio through nn::audio (audren), Bink 2 movies (.bk2, decoder
  most likely statically linked in main = guest code, nothing to do).
- 82 PKZ archives (version 0x10000), 8 556 entries, zstd compression (not Oodle); DAT/DTT containers.
- 1 348 shaders (540 VS, 738 PS, 70 CS) in PlatinumGames VSO/PSO/CSO/HSO/DSO objects; 1 620 cover pairs.
- GPU code versions 1.9/1.12/1.15; the loader compares byte 7 with the driver at main+0x9e97d0.
- Swap chain 1600x900, present interval 2 (30 fps shipping). Heap ~3 GB, BSS 191 MB (image ~0xccf0000).
- mem_reserve 0xf0000000, app_pool 0xCD500000, sys_resource 0; depth mode near=0; upper-left origin;
  alpha test GREATER via its own lib; swkbd for character creation.
- 60 fps mods (later iteration): FPSLocker write `00B5CE8C` `3D088889`->`3C888889`; nxnative patch = 112 hooks,
  30 Hz clock, integer timers.

## Risks to check during the census and boot

- C++ exceptions / unwinder: if main or sdk import `__cxa_throw`, `_Unwind_*` or `longjmp` with callers, the
  callee-saved trust of recomp/regs.py is unsound: use `recomp/gen.py --no-callee-saved-trust`.
- SDK 6.4.0 host services not covered by the TotK override set (178 overrides exist; Astral Chain imports a
  different subset).
- NVN ABI version: runtime/nvn_api_core.c reports major 55 / minor >= 15 (TotK); SDK 6.4.0's NVN may require a
  different version and abort (verify_boot / the first nvnDeviceGetProcAddress).
- NVN proc table: runtime/nvn_procs.inc has 537 TotK proc names; unknown asks stop the game (add as needed).
- Bink 2 movies: guest code, but they may use nn::codec or other host services not yet implemented.
- Heap size 3 GB: the TotK memory layer reserves a large heap; keep the reservation but watch the game's
  requested sizes at boot (nv::Initialize graphics work memory).
