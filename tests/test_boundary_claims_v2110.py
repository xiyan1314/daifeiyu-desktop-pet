# -*- coding: utf-8 -*-
"""A-07 反向钉子：那 4 处「代码驱动的位移」必须**仍然没有**接「减少动效」开关。

## 为什么需要这条（2026-10-16 裁决 = (b) 收窄声明）

声明侧**已经收窄**（不是本轮才改的；研究代理与协调者都逐字核过）：
  · CHANGELOG.md:27 —— 「代码驱动的时长动画瞬时完成」+ 边界逐条列点，写着
    「行走 / 甩抛飞行 / 食物托盘飞行 / 拖拽弹簧**不在此列**」；
  · _release_notes_v2100.md:10-11 —— 同口径；
  · pet_motion.effective_duration 的 docstring —— 「已知边界（有意划定）」四条列点。

**但这三处都没有任何机器判据看着它们**：谁哪天把走路/甩抛/托盘飞行/拖拽弹簧接上
「减少动效」开关，声明立刻变成假的，而全仓**一条用例都不会红**。本文件就是那颗钉子。

## 三条等价入口（找茬 #6：只钉一个名字 = 换个写法就绕过去）

开关在仓里有三个名字，任何一个都足以改变边界行为：`_reduce_motion()`（生效值）/
`_sys_reduce_motion`（建窗缓存的系统值，读法是**属性**不是调用）/
`pet_motion.reduce_motion_enabled(...)`（纯函数入口）。钉子必须同时看见三个名字。

## 反向对照（为什么它不是恒真空转）

_boundary_violations() 是一个**纯函数**（文件名 → 源码 → 违规列表）。下面有一条
**参数化**用例拿三种合成源码（分别把三个名字接到走路 tick 里）喂给同一个函数，
**每一种都必须**报出来。
"""
import ast
import io
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 「减少动效」开关的**三条等价入口**（找茬 #6：只钉 _reduce_motion 一个名字 = 换名字就绕过去了）：
#   · _reduce_motion()            —— 生效值（配置优先；auto 时用缓存的系统值）
#   · _sys_reduce_motion          —— 建窗时缓存的系统值；直接拿它当开关同样会改变边界行为
#   · reduce_motion_enabled(...)  —— pet_motion 的纯函数入口（谁能绕开方法直接调它）
# 三个名字都必须被同一条钉子看见：谁把边界接上其中任意一个，用例都要红。
SWITCH_NAMES = frozenset(("_reduce_motion", "_sys_reduce_motion", "reduce_motion_enabled"))

# 边界处（**不许**出现上面三个名字的地方）：键 -> (能唯一定位那一段的源码标记, 人话标签)
BOUNDARY_MARKERS = {
    "pet_wander.py": ("pet.move(nx, ny)", "走路位移（U-16：位移算不算动效仍要用户拍板）"),
    "桌宠.py#flight": ("self._flight_timer.start(pet_physics.FLIGHT_TICK_MS)", "甩抛飞行（物理）"),
    "桌宠.py#tray": ("self._fly_timer.start(30)", "食物托盘飞行"),
    "桌宠.py#spring": ("K, C = 200.0, 30.0", "拖拽弹簧跟手"),
}


def _src(name):
    return io.open(os.path.join(HERE, name), encoding="utf-8").read()


def _switch_lines(src):
    """源码里所有「减少动效」开关读取点的**行号**（三条等价入口一视同仁）。

    为什么按 Name / Attribute 收、而不是只看 Call：`if self._sys_reduce_motion:` 是**属性
    读取**，不是调用；只收 Call 的话，把守卫改成"直接读缓存值"就从这个钉子底下漏过去了。
    收 Name 是为了兜住 `from pet_motion import reduce_motion_enabled` 那种写法。
    """
    tree = ast.parse(src)
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in SWITCH_NAMES:
            lines.append(int(node.lineno))
        elif isinstance(node, ast.Name) and node.id in SWITCH_NAMES:
            lines.append(int(node.lineno))
    return sorted(set(lines))


def _func_spans(src):
    """每个函数/方法 -> (名字, 起始行, 结束行)。"""
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, int(node.lineno),
                        int(getattr(node, "end_lineno", node.lineno))))
    return out


def _boundary_violations(sources):
    """**判据本体**（纯函数；测试与反向对照共用同一个表达式）。

    sources: {主文件名: 源码}（桌宠.py#flight 这类带后缀的键按主文件名取）
    返回:  违规说明列表（空 = 边界完好）
    """
    out = []
    for key, (marker, label) in BOUNDARY_MARKERS.items():
        fname = key.split("#")[0]
        src = sources.get(fname)
        if src is None:
            out.append("%s: 读不到源码（钉不住 %s）" % (key, label))
            continue
        if marker not in src:
            out.append("%s: 找不到锚点 %r（%s）—— 源码改过，请重锚本用例" % (key, marker, label))
            continue
        mk_line = src[:src.index(marker)].count("\n") + 1
        switches = _switch_lines(src)
        span = None
        for name, a, b in _func_spans(src):
            if a <= mk_line <= b and (span is None or (b - a) < (span[2] - span[1])):
                span = (name, a, b)
        if span is None:
            continue  # 模块级代码：不在这条钉子的口径里
        hit = [ln for ln in switches if span[1] <= ln <= span[2]]
        if hit:
            out.append("%s: %s 里出现了「减少动效」开关（行 %r）—— 「%s」被接进开关了，"
                       "必须同步改 CHANGELOG / 发布说明 / pet_motion 的「已知边界」"
                       % (key, span[0], hit, label))
    return out


def test_the_four_displacements_are_still_outside_the_switch():
    """这 4 处**仍然**不读「减少动效」开关 —— 谁接上，这里就红。"""
    sources = {n: _src(n) for n in ("pet_wander.py", "桌宠.py")}
    problems = _boundary_violations(sources)
    assert problems == [], "边界被破了（声明会变成假的）：\n%s" % "\n".join(problems)


# 三种"把开关接进边界"的合成写法（每种只带**一个**开关名字，否则测不出是哪个名字被抓到）。
# 缩进与 pet_wander.tick 里那条 "        pet.move(nx, ny)" 对齐。
_SWITCH_INJECTIONS = {
    "_reduce_motion":
        "        if pet._reduce_motion():\n"
        "            return\n"
        "        pet.move(nx, ny)\n",
    "_sys_reduce_motion":
        "        if pet._sys_reduce_motion:\n"
        "            return\n"
        "        pet.move(nx, ny)\n",
    "reduce_motion_enabled":
        "        if pet_motion.reduce_motion_enabled(\"off\", None):\n"
        "            return\n"
        "        pet.move(nx, ny)\n",
}


# 桌宠.py 侧的另一处边界（拖拽弹簧）：同一批开关名字注入到锚点前面一行。
_STATIC_SPRING_INJECTIONS = {
    "_reduce_motion":
        "        if pet._reduce_motion():\n            return\n        K, C = 200.0, 30.0\n",
    "_sys_reduce_motion":
        "        if pet._sys_reduce_motion:\n            return\n        K, C = 200.0, 30.0\n",
    "reduce_motion_enabled":
        "        if pet_motion.reduce_motion_enabled(\"off\", None):\n"
        "            return\n        K, C = 200.0, 30.0\n",
}


@pytest.mark.parametrize("switch", sorted(_SWITCH_INJECTIONS))
def test_the_boundary_checker_can_actually_fail(switch):
    """反向对照：把开关接到边界里，同一个函数**必须**报出违规。

    **三个等价入口逐一试**（找茬 #6）：只钉 `_reduce_motion` 一个名字时，谁把守卫改成
    `if self._sys_reduce_motion:` 或 `pet_motion.reduce_motion_enabled(...)`，这条钉子
    就一声不吭——声明当场变成假的，而用例全绿。现在换其中任何一个名字都必须红。

    两处边界各试一遍：pet_wander.py 的走路 tick（锚点 = pet.move）与 桌宠.py 的拖拽弹簧
    （锚点 = K, C = 200.0, 30.0）——后者证明"同一个开关名字换了**文件**也照样被抓到"。
    """
    # ① 走路位移（pet_wander.py）
    walk = _src("pet_wander.py")
    mutated = walk.replace("        pet.move(nx, ny)\n", _SWITCH_INJECTIONS[switch], 1)
    assert mutated != walk, "锚点没换掉（走路那条 pet.move 的缩进变了？）"
    problems = _boundary_violations({"pet_wander.py": mutated, "桌宠.py": _src("桌宠.py")})
    assert any("pet_wander.py" in p for p in problems), (
        "用 %s 把开关接进走路 tick 之后判据没报 —— 这条钉子对这个入口是空的：%r"
        % (switch, problems))
    # ② 拖拽弹簧（桌宠.py · 同一个判据、另一份文件、另一个锚点）
    zc = _src("桌宠.py")
    spring = zc.replace("        K, C = 200.0, 30.0\n",
                        _STATIC_SPRING_INJECTIONS[switch], 1)
    assert spring != zc, "锚点没换掉（拖拽弹簧那条 K, C 的缩进变了？）"
    problems = _boundary_violations({"pet_wander.py": walk, "桌宠.py": spring})
    assert any("桌宠.py#spring" in p for p in problems), (
        "用 %s 把开关接进拖拽弹簧之后判据没报 —— 这个入口在 桌宠.py 侧是空的：%r"
        % (switch, problems))


# 每份文件的**实际措辞**（不是我以为的措辞）：三处的词不一样，逐份钉 ——
#   CHANGELOG / 发布说明 用「行走」，pet_motion 的代码侧登记用「走路」；
#   共同点是四处位移都必须被**逐个点名**（漏一个 = 声明不完整）。
DECLARATION_WORDS = {
    "CHANGELOG.md": ("行走", "甩抛", "食物托盘", "拖拽弹簧"),
    "_release_notes_v2100.md": ("行走", "甩抛", "食物托盘", "拖拽弹簧"),
    "pet_motion.py": ("走路", "甩抛", "食物托盘", "拖拽弹簧"),
}


def test_the_declaration_keeps_the_boundary_in_writing():
    """声明侧也要钉：三处「边界」写法必须在，且必须**逐个点名**那 4 处。

    能真失败：把任意一处边界列点里的某个名字删掉 → 本条红（声明就不完整了，
    而 Code 侧那条钉子只保证代码没变，保证不了文档没被删）。
    """
    for fname, needed in DECLARATION_WORDS.items():
        src = _src(fname)
        for name in needed:
            assert name in src, "%s 的边界列点漏了「%s」（四处位移必须逐个点名）" % (fname, name)
    # 「边界」这个说法本身也要在（否则列点退化成四句孤立的句子，没人看得出它们是一条裁决）
    assert "不在此列" in _src("CHANGELOG.md"), "CHANGELOG 里那句边界没了"
    assert "已知边界" in _src("pet_motion.py"), (
        "pet_motion 的「已知边界」段没了 —— 那是这条裁决唯一的代码侧登记")