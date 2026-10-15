# -*- coding: utf-8 -*-
"""变异体语法自检（v2.8.0 第 6 轮 · 代理 C）：每条变异应用后的源码必须还能 ast.parse。

为什么要有它（本轮实测的教训）：`old → new` 换掉的是一段**多行块**时，很容易把 `if x:`
的缩进体一起换掉 —— 新源码 IndentationError，pytest **收集期**就炸（rc=4），判定只能落
WRONG TEST（＝这条没被验证），而整批要跑完才知道，白烧一整轮（本轮踩到一次：M-C-A05）。
这一步是秒级的（纯文本 + ast，不起 pytest、不碰真仓），**跑批之前先过一遍**。

用法: python -B _dev/check_mutation_ast.py [_dev/mutations_x.json ...]
      不带参数 = 自动收全 `_dev/mutations_*.json`。
退出码: 0 = 全部可进 pytest；1 = 有锚点不是命中 1 次，或有变异体语法错。
"""
import ast
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _specs(argv):
    if argv:
        return argv
    return [os.path.join(HERE, n) for n in sorted(os.listdir(HERE))
            if n.startswith('mutations_') and n.endswith('.json')]


def main():
    total = bad = 0
    for path in _specs(sys.argv[1:]):
        try:
            data = json.loads(io.open(path, encoding='utf-8').read())
        except Exception as e:
            print('%-42s 读不出来：%r' % (os.path.basename(path), e))
            continue
        muts = data.get('mutations') or []
        if not muts:
            continue
        src_cache = {}
        broken = []
        for m in muts:
            total += 1
            rel = m.get('file') or ''
            if rel not in src_cache:
                try:
                    src_cache[rel] = io.open(os.path.join(ROOT, rel.replace('/', os.sep)),
                                             encoding='utf-8').read()
                except Exception as e:
                    src_cache[rel] = ''
                    print('[%s] 源文件读不出来：%r' % (m.get('id'), e))
            src = src_cache[rel]
            n = src.count(m.get('old') or '')
            if n != 1:
                broken.append('%s(锚点 %d 次)' % (m.get('id'), n))
                bad += 1
                continue
            if not rel.endswith('.py'):
                continue            # 非 Python 目标（README / 文档 / JSON）不做语法检查
            code = src.replace(m['old'], m['new'])
            try:
                ast.parse(code)
            except SyntaxError as e:
                broken.append('%s(语法错 %s @line %s)' % (m.get('id'), e.msg, e.lineno))
                bad += 1
        print('%-42s %3d 条，不过 %d%s' % (os.path.basename(path), len(muts), len(broken),
              '' if not broken else '  → ' + '；'.join(broken[:6])))
    print('\n%d 条变异，%d 条锚点/语法不过（0 = 全部可以进 pytest）' % (total, bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
