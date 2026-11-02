# Astral Chain Recomp

**Astral Chain Recomp** is a static recompilation of *Astral Chain* (Nintendo Switch, 2019) into a native x86-64 application for Windows, built on the pipeline of TotK Recomp ([docs/architecture.md](docs/architecture.md), [docs/astral-chain.md](docs/astral-chain.md)).

> [!IMPORTANT]
> **No game files are included.** You need your own legally obtained copy of *Astral Chain*, dumped from your own console: the base game. Instructions for obtaining those files will not be provided.
>
> The game is built from your files on your machine, so the result contains the game. It is for your own use. Do not share it.

## Status

Very early development: the port boots the base game (1.0.0); rendering and playability are still in progress. The
current milestone is reaching the title screen.

Report problems as issues, following [CONTRIBUTING.md](CONTRIBUTING.md).

## Features today

- Native code, not emulation
- Base game 1.0.0

## Planned

- In-game play
- The 1.0.1 update
- 60 fps and higher frame-rate limits
- Custom resolutions, supersampling and upscaling
- Settings menu, performance overlay, input remapping
- Shaders prepared at install instead of during play

## Installing

Not yet: the setup and installer come after the title-screen milestone. Until then, build from source
([docs/building.md](docs/building.md)).

## Credits

Astral Chain Recomp builds on the projects below. What was taken from each, with its license, is listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

- [LAS Recomp](https://github.com/peiikai/LASRecomp)
- [MacNativeGames](https://github.com/ly05010419/MacNativeGames)
- [nxnative](https://github.com/seedds/nxnative)
- [Ryujinx](https://github.com/Ryujinx/Ryujinx)
- [deko3d](https://github.com/devkitPro/deko3d)
- [SDL 3](https://libsdl.org), [Dear ImGui](https://github.com/ocornut/imgui), [AMD FSR 1](https://github.com/GPUOpen-Effects/FidelityFX-FSR), [Vulkan Memory Allocator](https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator), [libopus](https://opus-codec.org), [Zstandard](https://github.com/facebook/zstd)
- [Switchbrew](https://switchbrew.org) and the Switch homebrew community

## License

The project's own code is under the [MIT License](LICENSE); third-party code keeps its own license
([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)). The license grants nothing for Nintendo's game.

Astral Chain Recomp is an independent, non-commercial fan project, not affiliated with or endorsed by Nintendo.
*Astral Chain*, *PlatinumGames* and *Nintendo Switch* are trademarks of their respective owners.

## Building from source

[docs/building.md](docs/building.md) lists the toolchain and the steps. Everything the build writes stays under
`build\` and `generated\`, which git ignores; run `tools/check_content.py` before a commit.
