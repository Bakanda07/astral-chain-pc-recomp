# Astral Chain Recomp

Static recompilation of *Astral Chain* (Switch, ARM64) into a native Windows x86-64 exe with a Vulkan renderer, built
on the pipeline of the TotK Recomp project (see `docs/astral-chain.md` for port notes). Design: `docs/architecture.md`.
Toolchain, build commands and tests: `docs/building.md`.


## Priorities

- **Performance first**: Astral Chain is a fast PlatinumGames action game. Frame-time budgets are a feature: keep the
  host paths cheap (upload, replay, present pacing), avoid per-frame allocations and full-RomFS scans, and measure
  with `AC_TRACE=perf` / the performance overlay instead of guessing.
- **ASTC textures are everywhere**: the game's textures are almost all ASTC (`runtime/nvn.h` formats 0x79-0x94,
  14 LDR + 14 sRGB block sizes). Sampling goes through the native ASTC path when the device supports
  textureCompressionASTC_LDR (`runtime/vk_astc.c`, `AC_ASTC=auto`), the compute decoder otherwise. Any change to the
  texture upload/sampler paths must be checked against ASTC (including sRGB) and the `--probe-astc` probe; watch for
  3D ASTC, which Vulkan cannot sample natively and the decoder handles only in 2D.

## Game content boundary

This repository is public. Game data lives outside it and every derived file stays in ignored folders.

- The user's game and key paths are in `config.local.toml` (ignored). Pass the keys file path to tools; the tools read
  it themselves. Key values stay out of your output, logs, commands and files.
- Everything extracted or generated goes under `build/` or `generated/`.
- Every file the code generator emits carries the marker defined as `GENERATED_MARKER` in `tools/check_content.py`.
- Run `python tools/check_content.py --staged` before proposing a commit. It is the same check CI runs.

## Reusing code

`refs/` holds the upstream checkouts (`tools/fetch_refs.sh` recreates it). Read-only.

- Copy only MIT, BSD, ISC, zlib or Apache-2.0 code, keep its header, and add a row to `THIRD_PARTY_NOTICES.md`.
- yuzu, suyu, OpenSmash-Ultimate and other GPL code: read for behaviour, write our own.
- `tools/vendor/` stays byte-identical to upstream; Windows changes go in `tools/extract.py`.

## Code

- Build C with MSYS2 UCRT64 Clang (`C:\msys64\ucrt64\bin`). Generated C uses GNU extensions, so `cl.exe` is out. Call
  Ninja from that directory by full path or put it first on PATH.
- Two Python environments: `.venv` (3.12) for the lifter and the build. The TotK project also used `.venv-py314` for
  scripts needing `compression.zstd`; this port's extraction runs under `.venv` with the `zstandard` package, so 3.14
  is not required.
- Generated C is never edited by hand: change the generator (`recomp/`).
- Every lifter change passes the differential tests against Unicorn (`docs/building.md`, "Checks"). After changing
  `recomp/jumptables.py`, the jumptables check must report 0 disagreements.
- `recomp/layout.py` alone decides module bases.
- Graphics bugs: `docs/maxwell.md` lists the Maxwell behaviour the Vulkan path must match.
- Comments say what the code does and why, in words that stand on their own. Cite our code by file plus function (a
  line number may follow as a hint) and upstream code by project, file and function: `refs/` moves, so its line
  numbers rot. Commit hashes belong to the attribution of copied code.

## Writing

Code, comments, docs and commit messages are in English. Commit messages are plain sentences without type prefixes.

## About "Eglantine" subfolder

Eglantine is a free and opensource (FOSS) Switch 2 emulator, derived from Eden, Yuzu and Sudachi - started by developer Camille LaVey. It's written in C++ with portability in mind, with builds for Windows, Linux and macOS. You can refer to this repo to find relevant code such as missing services or anything else, but use subagents to process the code since the codebase is large
