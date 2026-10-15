# -*- coding: utf-8 -*-
"""只读探针（代理 C · v2.8.0）：某条用例是不是**挂死**，挂在哪一行。

用法: python -B _dev/_probe_c_v280_hang.py <nodeid> [seconds]
做法: 在**本进程**里跑 pytest，并用 faulthandler.dump_traceback_later 到点把所有线程的
      栈打出来再退出（exit=True）—— 这样"挂死"会给出确切的阻塞点，而不是只有一句超时。
不碰任何产品代码与用例（只读地跑）。
"""
import faulthandler
import sys

node = sys.argv[1]
limit = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
faulthandler.dump_traceback_later(limit, exit=True)
try:
    import pytest
    rc = pytest.main([node, "-o", "addopts=", "-q", "--no-header", "-p", "no:cacheprovider"])
except SystemExit as e:
    rc = e.code
faulthandler.cancel_dump_traceback_later()
print("pytest rc=%s" % (rc,))
