#!/usr/bin/env python3
"""agently-cli 测试桩。

用法：python stub_agently_cli.py <原 CLI 参数...> --stub-script <script.json>

script.json 为 [{args: [...], stdout: {...}, exit: 0}, ...]：
选择第一个「args 全部出现在 argv 中」的条目（兜底取第一条），
打印其 stdout 为 JSON 并以 exit 退出。stderr 可选（stderr 字段）。
"""
import json
import sys


def main() -> int:
    argv = sys.argv[1:]
    script_path = None
    clean = []
    i = 0
    while i < len(argv):
        if argv[i] == "--stub-script" and i + 1 < len(argv):
            script_path = argv[i + 1]
            i += 2
            continue
        clean.append(argv[i])
        i += 1
    if not script_path:
        print(json.dumps({"ok": False, "error": {"message": "stub: --stub-script required"}}))
        return 2
    with open(script_path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    entry = None
    for e in entries:
        if all(a in clean for a in e.get("args", [])):
            entry = e
            break
    if entry is None and entries:
        entry = entries[0]
    if entry is None:
        print(json.dumps({"ok": False, "error": {"message": "stub: empty script"}}))
        return 2

    print(json.dumps(entry.get("stdout", {"ok": True, "data": {}}), ensure_ascii=False))
    if entry.get("stderr"):
        sys.stderr.write(entry["stderr"])
    return int(entry.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main())
