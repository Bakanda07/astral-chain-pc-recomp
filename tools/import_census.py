"""Import census for the Astral Chain port: which imports of main need host overrides.

Loads the extracted ExeFS modules with recomp/nso.py, parses the HOST_OVERRIDE / HOST_OBSERVER names out of
runtime/*.c, and reports:

- imports of main not exported by sdk and not overridden by the host (a strong one of these stops the loader),
- imports grouped by namespace, to plan the service implementations,
- overrides and observers no import of main uses (candidates for pruning).

No game files are copied anywhere; only names are printed.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'recomp'))

from nso import Nso   # noqa: E402

STB_WEAK = 2


def syms_of(nso):
    out = {}
    for s in nso.syms:
        name = s[0] if isinstance(s, tuple) else s.name
        info = s[1] if isinstance(s, tuple) else getattr(s, 'info', 0)
        out[name] = info
    return out


def host_names(kind):
    names = set()
    pattern = re.compile(r'HOST_%s\(\s*"((?:[^"\\]|\\.)*)"' % kind)
    for path in sorted((ROOT / 'runtime').glob('*.c')):
        text = path.read_text(encoding='utf-8', errors='replace')
        for m in pattern.finditer(text):
            names.add(m.group(1))
    return names


def main():
    exefs = ROOT / 'build' / 'extracted' / 'v0' / 'exefs'
    main = Nso(exefs / 'main')
    sdk = Nso(exefs / 'sdk')

    imports = syms_of(main)
    exports = syms_of(sdk)
    overrides = host_names('OVERRIDE')
    observers = host_names('OBSERVER')

    critical = []
    weak = 0
    for name, info in sorted(imports.items()):
        if name in exports or name in overrides:
            continue
        if (info >> 4) & 0xF == STB_WEAK:
            weak += 1
            continue
        critical.append(name)

    print(f'main imports: {len(imports)}, sdk exports: {len(exports)}, host overrides: {len(overrides)}, '
          f'observers: {len(observers)}')
    print(f'unresolved strong imports (would stop the loader): {len(critical)}')
    for name in critical:
        print('  UNRESOLVED', name)

    # Group by namespace.
    groups = {}
    for name in imports:
        m = re.match(r'_ZN(\d+)([A-Za-z0-9_]+)', name)
        ns = m.group(2) if m else ('c' if name.startswith('_Z') or name.startswith('__') else 'plain')
        groups.setdefault(ns, []).append(name)
    print('\nimports of main by namespace:')
    for ns in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        names = groups[ns]
        print(f'  {ns}: {len(names)}')
        for name in sorted(names):
            print(f'      {name}')

    dead_ovr = sorted(o for o in overrides if o not in imports)
    dead_obs = sorted(o for o in observers if o not in imports)
    print(f'\noverrides no import of main uses: {len(dead_ovr)}')
    for name in dead_ovr:
        print('  DEAD', name)
    print(f'observers no import of main uses: {len(dead_obs)}')
    for name in dead_obs:
        print('  DEAD-OBS', name)


if __name__ == '__main__':
    main()
