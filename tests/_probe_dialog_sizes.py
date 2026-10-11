# -*- coding: utf-8 -*-
"""v2.5.0 代理 B · B1 体检脚本（**不是** pytest 用例：文件名不以 test_ 开头，不被收集）。

用法（仓库根）：
    python -B tests\_probe_dialog_sizes.py               # 当前 DPI
    $env:QT_SCALE_FACTOR="1.25"; python -B tests\_probe_dialog_sizes.py
    $env:QT_SCALE_FACTOR="1.5";  python -B tests\_probe_dialog_sizes.py
可选 --json <路径> 落一份机器可读的数据（供报告生成）。
"""
import json
import os
import shutil
import sys
import tempfile

import helpers_dialog_fit_v250 as H

from PySide6.QtWidgets import QApplication  # noqa: E402

H.boot_application()
app = QApplication.instance()


def main():
    out_json = None
    if "--json" in sys.argv:
        out_json = sys.argv[sys.argv.index("--json") + 1]

    tmp = tempfile.mkdtemp(prefix="dlgprobe_")
    restore, seen = H.silence_modals()
    rows = []
    try:
        pet = H.make_pet(tmp)
        try:
            for name, mk in H.dialog_factories():
                rec = {"name": name, "ok": True, "error": None,
                       "modal_hits": 0, "shrink_w": None, "shrink_h": None}
                before = len(seen)
                win = None
                try:
                    win = mk(pet)
                    win.show()
                    app.processEvents()
                    m = H.measure(win, app)
                    m["name"] = name
                    rec.update(m)
                    sw, sh = H.probe_shrink(win, app)
                    rec["shrink_w"], rec["shrink_h"] = sw, sh
                    rec["modal_hits"] = len(seen) - before
                except Exception as e:  # noqa: BLE001 —— 体检脚本要如实记录造不出来的
                    rec["ok"] = False
                    rec["error"] = repr(e)
                finally:
                    if win is not None:
                        try:
                            win.close()
                            win.deleteLater()
                        except Exception:
                            pass
                        app.processEvents()
                rows.append(rec)
        finally:
            H.shutdown_pet(pet)
            app.processEvents()
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 132)
    print("QT_QPA_PLATFORM=%s  QT_SCALE_FACTOR=%s  screen_dpr=%s"
          % (os.environ.get("QT_QPA_PLATFORM"), os.environ.get("QT_SCALE_FACTOR"),
             app.primaryScreen().devicePixelRatio()))
    print("=" * 132)
    for r in rows:
        if not r["ok"]:
            print("%-26s CONSTRUCT FAILED: %s" % (r["name"], r["error"]))
            continue
        print(H.fmt_row(r)
              + ("  shrink=%dx%d" % (r["shrink_w"], r["shrink_h"]) if r["shrink_w"] else "")
              + ("  [modal x%d]" % r["modal_hits"] if r["modal_hits"] else ""))
    if out_json:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump({"scale": os.environ.get("QT_SCALE_FACTOR", "1"), "rows": rows},
                      f, ensure_ascii=False, indent=1)
        print("\njson -> %s" % out_json)


if __name__ == "__main__":
    main()
