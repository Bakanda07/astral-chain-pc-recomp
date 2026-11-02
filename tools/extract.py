"""Extract Astral Chain 1.0.0 (title 01007300020FA000) from the player's base NSP into build/ and verify it.

Adapted from the vendored MacNativeGames extractor, tools/vendor/macnativegames/extract_exefs.py and
extract_romfs.py @ b75be8c (MIT, Copyright (c) 2026 MacNativeGames contributors). hactool is not needed for
the base game: the tool decrypts in place (NCA3, AES-CTR key-area or common ticket, hierarchical PFS0,
IVFC) and never writes key material.

Steps, each skipped when its verified output already exists:

1. ExeFS (code modules) of the base game, verified against tools/data/expected-v1.0.0.json. On the first
   extraction of a new dump the expected hashes are written into that file; later runs stop on a mismatch.
2. Base RomFS, verified through all six IVFC levels, with its file index.

The base NSP is expected to be ticketless or key-area encrypted (the usual game-card dump). An NSP whose
Program NCA needs a missing common ticket stops the extraction.

--base, --keys and --work name the files and the output directory instead of the config (the installer
imports the functions instead). Key values are read by the tools from the keys file and never printed.
"""
import argparse
import hashlib
import io
import json
import struct
import sys
import tomllib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parent.parent

GAME_TITLE_ID = '01007300020FA000'
DISPLAY_VERSION = '1.0.0'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decrypt(key, mode, data):
    ctx = Cipher(algorithms.AES(key), mode).decryptor()
    return ctx.update(data) + ctx.finalize()


def read_at(f, offset, length):
    require(0 <= offset and 0 <= length <= 512 * 1024 * 1024, 'Invalid/big read')
    f.seek(offset)
    data = f.read(length)
    require(len(data) == length, 'Truncated input')
    return data


def partition_entries(f, offset, bound, magic=b'PFS0', stride=24):
    """Read a bounded PFS0/HFS0 table without loading its file payloads."""
    require(bound >= 16, 'Truncated partition header')
    hdr = read_at(f, offset, 16)
    require(hdr[:4] == magic, f'Expected {magic.decode()}')
    count, strings_size = struct.unpack_from('<II', hdr, 4)
    require(count <= 4096 and strings_size <= 1024 * 1024, 'Invalid partition table')
    size = 16 + count * stride + strings_size
    require(size <= bound, 'Partition table out of bounds')
    raw = read_at(f, offset, size)
    strings = raw[16 + count * stride:]
    entries = []
    names = set()
    for i in range(count):
        off, length, nameoff = struct.unpack_from('<QQI', raw, 16 + i * stride)
        require(nameoff < len(strings), 'Invalid partition filename offset')
        end = strings.find(b'\0', nameoff)
        require(end >= 0, 'Unterminated partition filename')
        name = strings[nameoff:end].decode('utf-8')
        require(name not in ('', '.', '..') and '/' not in name and '\\' not in name, 'Unsafe partition filename')
        require(name not in names, 'Duplicate partition filename')
        names.add(name)
        require(size + off + length <= bound, 'Partition entry out of bounds')
        entries.append((name, offset + size + off, length))
    end = offset + size
    for _, start, length in sorted(entries, key=lambda e: e[1]):
        require(start >= end, 'Overlapping partition entries')
        end = start + length
    return entries


def container_entries(f, size):
    if read_at(f, 0, 4) == b'PFS0':
        return 'nsp', partition_entries(f, 0, size)
    raise ValueError('Expected an NSP (PFS0) game file; XCI is not supported')


def load_keys(path):
    keys = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.split('#', 1)[0].strip()
        if '=' in line:
            name, value = line.split('=', 1)
            try:
                keys[name.strip().lower()] = bytes.fromhex(value.strip())
            except ValueError:
                raise ValueError(f'Invalid key encoding at line {number}') from None
    return keys


def common_tickets(f, entries):
    """Keep encrypted title keys in memory only; a personalized ticket never provides a common key."""
    tickets = {}
    bodies = {0x10000: 0x240, 0x10001: 0x140, 0x10002: 0x80,
              0x10003: 0x240, 0x10004: 0x140, 0x10005: 0x80}
    for name, offset, size in entries:
        if not name.lower().endswith('.tik'):
            continue
        require(size >= 4, 'Truncated NSP ticket')
        sig = struct.unpack('<I', read_at(f, offset, 4))[0]
        require(sig in bodies, 'Unsupported NSP ticket signature type')
        body = bodies[sig]
        require(size >= body + 0x180, 'Truncated NSP ticket body')
        data = read_at(f, offset + body, 0x180)
        require(data[0x141] == 0, 'Personalized NSP tickets are unsupported; a common ticket is required')
        rights, key = data[0x160:0x170], data[0x40:0x50]
        require(rights not in tickets or tickets[rights] == key, 'Conflicting NSP tickets')
        tickets[rights] = key
    return tickets


def read_nca_header(f, offset, size, keys):
    require(size >= 0xc00, 'Truncated NCA header')
    require('header_key' in keys, 'Missing header_key in prod.keys')
    raw = read_at(f, offset, 0xc00)
    hdr = b''.join(decrypt(keys['header_key'], modes.XTS(i.to_bytes(16, 'big')),
                           raw[i * 512:(i + 1) * 512]) for i in range(6))
    require(hdr[0x200:0x204] == b'NCA3', 'Expected NCA3 (check prod.keys and the game file)')
    require(struct.unpack_from('<Q', hdr, 0x208)[0] == size, 'NCA size does not match container entry')
    for i in range(4):
        start, end = struct.unpack_from('<II', hdr, 0x240 + i * 16)
        require((start == end == 0) or 0xc00 <= start * 512 < end * 512 <= size, 'NCA section out of bounds')
    return hdr


def nca_ctr_key(hdr, keys, tickets):
    generation = max(max(hdr[0x206], hdr[0x220]) - 1, 0)
    rights = hdr[0x230:0x240]
    if rights != bytes(16):
        require(rights in tickets, 'Missing common ticket for rights-managed NCA in the NSP')
        keyname = f'titlekek_{generation:02x}'
        require(keyname in keys, f'Missing {keyname} in prod.keys')
        return decrypt(keys[keyname], modes.ECB(), tickets[rights])
    require(hdr[0x207] < 3, 'Unsupported NCA key area')
    area = ('application', 'ocean', 'system')[hdr[0x207]]
    keyname = f'key_area_key_{area}_{generation:02x}'
    require(keyname in keys, f'Missing {keyname} in prod.keys')
    return decrypt(keys[keyname], modes.ECB(), hdr[0x300:0x340])[32:48]


def nca_inventory(f, entries, keys):
    records = []
    for name, offset, length in entries:
        if not name.lower().endswith('.nca'):
            continue
        hdr = read_nca_header(f, offset, length, keys)
        record = dict(name=name, nca_offset=offset, size=length, content_type=hdr[0x205],
                      title_id=f'{struct.unpack_from("<Q", hdr, 0x210)[0]:016X}')
        records.append((record, hdr))
    return records


def program_nca(records):
    """The one base Program NCA of Astral Chain."""
    programs = [(r, h) for r, h in records if r['content_type'] == 0]
    require(len(programs) == 1, 'Expected one base Program NCA; updates, DLC and combined packages are unsupported')
    record, hdr = programs[0]
    require(record['title_id'] == GAME_TITLE_ID,
            f'Expected Astral Chain base game ({GAME_TITLE_ID}); this file contains another title')
    return record, hdr


def exefs_expected():
    path = ROOT / 'tools' / 'data' / 'expected-v1.0.0.json'
    return json.loads(path.read_text()) if path.exists() else {}


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def extract_exefs(game, keys, output):
    """Extract the ExeFS of the base Program NCA into output/; write the extraction manifest next to it."""
    require(not (output.parent / 'extraction-manifest.json').exists(), 'ExeFS already extracted')
    keys = load_keys(keys)
    with game.open('rb') as f:
        kind, entries = container_entries(f, game.stat().st_size)
        tickets = common_tickets(f, entries)
        record, hdr = program_nca(nca_inventory(f, entries, keys))
        ctr_key = nca_ctr_key(hdr, keys, tickets)
        for i in range(4):
            start, end = struct.unpack_from('<II', hdr, 0x240 + 16 * i)
            if not start:
                continue
            fs = hdr[0x400 + 512 * i:0x600 + 512 * i]
            require(hashlib.sha256(fs).digest() == hdr[0x280 + 32 * i:0x2A0 + 32 * i], 'FS header hash mismatch')
            if fs[2:4] != b'\x01\x02':
                continue
            require(fs[4] == 3, 'Only AES-CTR ExeFS is supported')
            blocksize, levels = struct.unpack_from('<II', fs, 0x28)
            hashoff, hashsize, pfsoff, pfssize = struct.unpack_from('<QQQQ', fs, 0x30)
            secstart, secsize = start * 512, (end - start) * 512
            require(levels == 2 and blocksize > 0 and pfssize <= 512 * 1024 * 1024, 'Unsupported ExeFS hash layout')

            def section_read(relative, size):
                require(relative >= 0 and relative + size <= secsize, 'Section read out of bounds')
                absolute = secstart + relative
                aligned = absolute & ~15
                iv = fs[0x140:0x148][::-1] + (aligned // 16).to_bytes(8, 'big')
                data = read_at(f, record['nca_offset'] + aligned, size + absolute - aligned)
                return decrypt(ctr_key, modes.CTR(iv), data)[absolute - aligned:]

            hashes = section_read(hashoff, hashsize)
            require(hashlib.sha256(hashes).digest() == fs[8:40], 'ExeFS hash-table mismatch')
            pfs = section_read(pfsoff, pfssize)
            for index, pos in enumerate(range(0, pfssize, blocksize)):
                expected = hashes[index * 32:(index + 1) * 32]
                require(hashlib.sha256(pfs[pos:pos + blocksize]).digest() == expected,
                        f'ExeFS block hash mismatch: {index}')
            files = [(name, pfs[off:off + size]) for name, off, size in
                     partition_entries(io.BytesIO(pfs), 0, len(pfs))]
            require(any(name == 'main.npdm' for name, _ in files), 'PFS0 is not ExeFS')
            output.mkdir(parents=True, exist_ok=True)
            extracted = []
            for name, data in files:
                (output / name).write_bytes(data)
                extracted.append({'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            manifest = {'source': str(game.resolve()), 'source_size': game.stat().st_size,
                        'source_mtime_ns': game.stat().st_mtime_ns, 'container': kind,
                        'nca_inventory': [r for r, _ in nca_inventory(f, entries, keys)], 'program': record,
                        'section_index': i,
                        'integrity': 'FS header, ExeFS hash table, and every ExeFS data block verified; RSA signatures not checked',
                        'files': extracted}
            (output.parent / 'extraction-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            print(json.dumps({'integrity': manifest['integrity'], 'files': extracted}, indent=2))
            return manifest
    raise ValueError('No ExeFS section found')


def extract_romfs(game, keys, manifest, output):
    """Verify all six IVFC levels, stream the RomFS image, and index its files."""
    require(not output.exists(), 'RomFS output already exists')
    keys = load_keys(keys)
    record = manifest['program']
    with game.open('rb') as f:
        _, entries = container_entries(f, game.stat().st_size)
        actual, hdr = program_nca(nca_inventory(f, entries, keys))
        require(actual['name'] == record['name'] and actual['size'] == record['size'] and
                actual['nca_offset'] == record['nca_offset'], 'Source Program NCA changed; extract ExeFS again')
        ctr_key = nca_ctr_key(hdr, keys, common_tickets(f, entries))
        for i in range(4):
            start, end = struct.unpack_from('<II', hdr, 0x240 + i * 16)
            if not start:
                continue
            fs = hdr[0x400 + 512 * i:0x600 + 512 * i]
            require(hashlib.sha256(fs).digest() == hdr[0x280 + 32 * i:0x2A0 + 32 * i], 'FS header hash')
            if fs[2:5] != bytes([0, 3, 3]):
                continue
            require(fs[8:12] == b'IVFC' and struct.unpack_from('<III', fs, 12) == (0x20000, 32, 7),
                    'Unsupported IVFC layout')
            levels = [struct.unpack_from('<QQII', fs, 0x18 + j * 24) for j in range(6)]

            def read(relative, size):
                require(0 <= relative <= relative + size <= (end - start) * 512, 'Section bounds')
                absolute = start * 512 + relative
                aligned = absolute & ~15
                skip = absolute - aligned
                iv = fs[0x140:0x148][::-1] + (aligned // 16).to_bytes(8, 'big')
                return decrypt(ctr_key, modes.CTR(iv),
                               read_at(f, record['nca_offset'] + aligned, size + skip))[skip:]

            output.mkdir(parents=True)
            image_path = output / 'romfs.bin'
            digest = hashlib.sha256()
            counts = []
            parent = fs[0xc8:0xe8]
            with image_path.open('wb') as image:
                for level, (offset, size, power, reserved) in enumerate(levels):
                    require(12 <= power <= 24 and reserved == 0, 'IVFC block size')
                    block = 1 << power
                    require(len(parent) >= (size + block - 1) // block * 32, 'IVFC parent size')
                    captured = bytearray() if level < 5 else None
                    index = 0
                    for pos in range(0, size, 8 * 1024 * 1024):
                        chunk = read(offset + pos, min(8 * 1024 * 1024, size - pos))
                        for j in range(0, len(chunk), block):
                            payload = chunk[j:j + block]
                            require(hashlib.sha256(payload + bytes(block - len(payload))).digest()
                                    == parent[index * 32:index * 32 + 32], f'IVFC level {level} block {index} failed')
                            index += 1
                        if captured is not None:
                            captured.extend(chunk)
                        else:
                            image.write(chunk)
                            digest.update(chunk)
                    counts.append(index)
                    if captured is not None:
                        parent = bytes(captured)
                    print(f'IVFC level {level}: {index} blocks verified', flush=True)
            files = index_romfs(image_path)
            report = dict(status='pass', source_size=game.stat().st_size, program=record['name'], section=i,
                          ivfc_blocks=counts, romfs_size=levels[-1][1], romfs_sha256=digest.hexdigest(),
                          files=files,
                          integrity='FS header and all six IVFC levels verified; RSA signature not checked')
            (output / 'index.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(dict(status='pass', file_count=len(files), size=levels[-1][1],
                                  sha256=digest.hexdigest())))
            return report
    raise ValueError('No supported RomFS found')


def index_romfs(path):
    with path.open('rb') as f:
        h = struct.unpack('<10Q', read_at(f, 0, 80))
        require(h[0] == 80, 'RomFS header')
        length = path.stat().st_size
        for off, size in [(h[1], h[2]), (h[3], h[4]), (h[5], h[6]), (h[7], h[8])]:
            require(off + size <= length, 'RomFS table bounds')
        dirs = read_at(f, h[3], h[4])
        entries = read_at(f, h[7], h[8])
        files = []
        seen_dirs = set()
        seen_files = set()
        paths = set()

        def name(table, off, n):
            require(off + n <= len(table), 'Name bounds')
            s = table[off:off + n].decode('utf-8')
            require(s not in ['.', '..'] and '/' not in s and '\\' not in s and '\0' not in s, 'Unsafe path')
            return s

        todo = [(0, '')]
        while todo:
            off, parent = todo.pop()
            require(off not in seen_dirs and off + 24 <= len(dirs), 'Invalid/cyclic directory')
            seen_dirs.add(off)
            p, sibling, child, file, hash_next, n = struct.unpack_from('<6I', dirs, off)
            part = name(dirs, off + 24, n)
            prefix = parent + part + '/' if part else parent
            if sibling != 0xffffffff:
                todo.append((sibling, parent))
            if child != 0xffffffff:
                todo.append((child, prefix))
            while file != 0xffffffff:
                require(file not in seen_files and file + 32 <= len(entries), 'Invalid/cyclic file')
                seen_files.add(file)
                p, next_file, data, size, hash_next, n = struct.unpack_from('<IIQQII', entries, file)
                part = name(entries, file + 32, n)
                require(part != '', 'Empty file name')
                filename = prefix + part
                require(filename not in paths and h[9] + data + size <= length, 'Duplicate/out-of-bounds file')
                paths.add(filename)
                files.append(dict(path=filename, offset=h[9] + data, size=size))
                file = next_file
        return sorted(files, key=lambda item: item['path'])


def exefs_ok(exefs_dir, expected):
    """Whether the extracted ExeFS matches the expected hashes; (ok, problems) where problems is the list of
    differing names (or missing names when the expected file is absent)."""
    if not (exefs_dir / 'main.npdm').exists():
        return False, ['missing ExeFS']
    problems = []
    for name, want in expected.get('exefs_sha256', {}).items():
        path = exefs_dir / name
        if not path.exists() or sha256(path) != want:
            problems.append(name)
    return not problems, problems


def update_expected(manifest, romfs_report):
    """Write the measured hashes into tools/data/expected-v1.0.0.json (first run on a new dump)."""
    path = ROOT / 'tools' / 'data' / 'expected-v1.0.0.json'
    exefs = {f['name']: f['sha256'] for f in manifest['files']}
    expected = {
        '_comment': 'Hashes of what the build produces from a genuine Astral Chain 1.0.0 base game (no game data). '
                    'tools/extract.py checks every step against them; a mismatch stops the build.',
        'title_id': GAME_TITLE_ID,
        'version': 0,
        'display_version': DISPLAY_VERSION,
        'program_nca': manifest['program']['name'],
        'exefs_sha256': exefs,
        'romfs': {'size': romfs_report['romfs_size'], 'sha256': romfs_report['romfs_sha256']},
    }
    path.write_text(json.dumps(expected, indent=2) + '\n')


def check_expected(manifest, romfs_report):
    expected = exefs_expected()
    if not expected:
        update_expected(manifest, romfs_report)
        print(f'expected-v1.0.0.json: written from this dump (ExeFS: {len(manifest["files"])} files, '
              f'RomFS {romfs_report["romfs_size"]} bytes)')
        return
    problems = []
    for name, want in expected.get('exefs_sha256', {}).items():
        got = next((f['sha256'] for f in manifest['files'] if f['name'] == name), None)
        if got != want:
            problems.append(name)
    want_romfs = expected.get('romfs', {})
    if want_romfs.get('size') != romfs_report['romfs_size'] or \
            want_romfs.get('sha256') != romfs_report['romfs_sha256']:
        problems.append('romfs')
    require(not problems, f'Extracted files differ from expected-v1.0.0.json: {", ".join(problems)}. '
                          f'Copy the base game again from its source and retry.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, default=ROOT / 'config.local.toml')
    parser.add_argument('--base', type=Path, help='base game NSP (default: input.base of the config)')
    parser.add_argument('--keys', type=Path, help='prod.keys (default: input.keys of the config)')
    parser.add_argument('--work', type=Path, help='output directory with extracted/ (default: work.dir of the '
                                                  'config, else build)')
    args = parser.parse_args()

    config = {}
    if not (args.base and args.keys and args.work):
        config = tomllib.loads(args.config.read_text(encoding='utf-8'))
    given = config.get('input', {})
    base = args.base or Path(given['base'])
    keys = args.keys or Path(given['keys'])
    work = args.work or ROOT / config.get('work', {}).get('dir', 'build')
    require(base.exists(), f'Base game not found: {base}')
    require(keys.exists(), f'Keys file not found: {keys}')

    out = work / 'extracted' / 'v0'
    manifest_path = work / 'extracted' / 'extraction-manifest.json'
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        print(f'Extracting ExeFS from {base.name} (base game 1.0.0)')
        manifest = extract_exefs(base, keys, out / 'exefs')
        print('ExeFS extracted:', ', '.join(f['name'] for f in manifest['files']))

    if not (out / 'romfs' / 'index.json').exists():
        print('Extracting RomFS (verified through all six IVFC levels)')
        report = extract_romfs(base, keys, manifest, out / 'romfs')
    else:
        report = json.loads((out / 'romfs' / 'index.json').read_text())

    check_expected(manifest, report)
    print(f'OK: ExeFS and RomFS verified for Astral Chain {DISPLAY_VERSION} ({GAME_TITLE_ID})')


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        sys.exit(f'error: {error}')
