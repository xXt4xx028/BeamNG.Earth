"""Run standalone LuaJIT tests through Lupa (pip install lupa), without a game."""
import argparse
import os
import time
from pathlib import Path

from lupa.luajit21 import LuaRuntime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+')
    args = parser.parse_args()
    failures = 0
    for name in args.files:
        path = Path(name).resolve()
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().arg = lua.table_from({0: path.as_posix()})
        # Match the game's high-resolution elapsed timer. Windows os.clock can
        # return the same value for successive calls in collision timing tests.
        lua.globals()._test_monotonic = time.perf_counter
        lua.execute("package.preload['socket'] = function() return {gettime = _test_monotonic} end")
        lua.execute('os.exit = function(code) if code and code ~= 0 then error("test exit " .. code) end end')
        previous = Path.cwd()
        try:
            os.chdir(path.parent)
            lua.execute(path.read_text(encoding='utf-8'), name='@' + path.as_posix())
        except Exception as exc:
            failures += 1
            print(f'FAILED {name}: {exc}', flush=True)
        finally:
            os.chdir(previous)
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
