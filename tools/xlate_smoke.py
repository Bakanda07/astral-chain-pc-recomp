"""Smoke test for build/xlate/ac_xlate(.exe): no game files needed.

Sends one hand-assembled Maxwell fragment shader (writes the constant colour 1.0, 0.5, 0.25, 1.0 to render target 0)
through --serve, checks the reply, validates the SPIR-V with spirv-val, then sends a malformed line and checks the
service survives and still answers. The same shader with an alpha test ("alpha_test" GREATER, "alpha_ref_bits" 0.5, as
runtime/gfx_shader.c build_request sends it) must discard, and the shader without one must not.

  python tools/xlate_smoke.py [--exe PATH]
"""

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "build" / "xlate" / ("ac_xlate.exe" if os.name == "nt" else "ac_xlate")
SPIRV_VAL = (Path(r"C:\msys64\ucrt64\bin\spirv-val.exe") if os.name == "nt"
             else Path(shutil.which("spirv-val") or "/usr/bin/spirv-val"))

PT = 7 << 16  # predicate "always"
DISCARD_OPS = (252, 4416, 4449)  # OpKill, OpTerminateInvocation, OpDemoteToHelperInvocation


def mov32i(dest: int, value: float) -> int:
    imm = struct.unpack("<I", struct.pack("<f", value))[0]
    return 0x0100000000000000 | (imm << 20) | (0xF << 12) | PT | dest


EXIT = 0xE30000000000000F | PT
SCHED = 0x001F8000FC0007E0  # scheduling control word; the decoder skips it


def fragment_code(alpha: float = 1.0) -> bytes:
    header = [0] * 20
    header[0] = 2 | (3 << 5) | (5 << 10)  # SPH type 2, version 3, stage fragment
    header[18] = 0xF  # OMAP: render target 0, components xyzw
    words = [SCHED, mov32i(0, 1.0), mov32i(1, 0.5), mov32i(2, 0.25),
             SCHED, mov32i(3, alpha), EXIT, 0]
    return struct.pack("<20I", *header) + struct.pack(f"<{len(words)}Q", *words)


def opcodes(data: bytes) -> set[int]:
    words = struct.unpack(f"<{len(data) // 4}I", data)
    ops, i = set(), 5
    while i < len(words):
        ops.add(words[i] & 0xFFFF)
        i += max(words[i] >> 16, 1)
    return ops


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", type=Path, default=EXE, help="translator to test (default build/xlate)")
    exe = ap.parse_args().exe
    if not exe.is_file():
        print(f"missing {exe}; run tools/build_xlate.py", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        code = tmp / "ps.bin"
        code.write_bytes(fragment_code())
        alpha_code = tmp / "ps_alpha.bin"
        alpha_code.write_bytes(fragment_code(0.25))   # fails GREATER 0.5, so the translator must discard
        out = tmp / "out"
        job = {"key": "const_ps", "stage": "ps", "code": str(code), "debug": False, "fout": {"0": "float"}}
        half = struct.unpack("<I", struct.pack("<f", 0.5))[0]
        lines = [
            json.dumps({"job": job, "out": str(out)}),
            "this is not json",
            json.dumps({"job": dict(job, key="again"), "out": str(out)}),
            json.dumps({"job": dict(job, key="alpha_ps", code=str(alpha_code), alpha_test=5, alpha_ref_bits=half),
                        "out": str(out)}),
        ]
        r = subprocess.run([str(exe), "--serve"], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=60)
        replies = r.stdout.splitlines()
        print("replies:", replies)
        if (len(replies) != 4 or replies[0] != "ok const_ps" or not replies[1].startswith("fail ")
                or replies[2] != "ok again" or replies[3] != "ok alpha_ps"):
            print("unexpected replies; stderr:", r.stderr, file=sys.stderr)
            return 1
        rc = 0
        for key, discards in (("const_ps", False), ("alpha_ps", True)):
            spv = out / f"{key}.spv"
            data = spv.read_bytes()
            if len(data) < 20 or struct.unpack("<I", data[:4])[0] != 0x07230203:
                print(f"{key}: reply is not SPIR-V", file=sys.stderr)
                return 1
            v = subprocess.run([str(SPIRV_VAL), "--target-env", "vulkan1.3", str(spv)], capture_output=True, text=True)
            has = bool(opcodes(data) & set(DISCARD_OPS))
            print(f"{key}: spirv-val exit {v.returncode} ({len(data)} bytes), discard {has} {v.stdout}{v.stderr}")
            if v.returncode or has != discards:
                rc = 1
        return rc


if __name__ == "__main__":
    sys.exit(main())
