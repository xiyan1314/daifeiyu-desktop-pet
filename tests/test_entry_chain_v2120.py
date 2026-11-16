# -*- coding: utf-8 -*-
"""遗留-1 的钉子：入口链（spec / vbs / 开机自启）必须指向 main.py 这个守护入口。

## 为什么需要这条

v2.11.0 的「崩溃自动重启」只在 `python main.py` 起步时执行，而三处入口全指向 `桌宠.py`：
`大肥鱼桌宠.spec:5` 的 Analysis、`启动桌宠.vbs` 的"扫标记"、`pet_main.autostart_command` 的三条兜底
⇒ **打包出来的 exe 上守护一次都不跑**（发布说明 §五 5 如实登记过）。第 12 轮把三处一起改到 main.py；
本文件是"改回去就红"的那颗钉子。

## 每条能真失败在哪（改什么会红）

- 把 spec 入口改回 `['桌宠.py']` → test_spec_entry_is_main_py 红；
- 删掉 main.py 里的 entry-marker → test_main_py_carries_the_entry_marker 红（老 vbs 会找不到入口）；
- 把 entry_name() 的 ENTRY_NAMES 顺序倒过来 → test_entry_name_prefers_main_py 红；
- 把 autostart_command 的三条路径改回写死 桌宠.py → test_autostart_command_points_at_the_guard_entry 红；
- 把 vbs 里的显式 main.py 分支挪到"扫标记"之后 → test_vbs_prefers_main_py_before_the_marker_scan 红。
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pet_main  # noqa: E402


def _spec_entries():
    """从 .spec 里取 Analysis(...) 的入口列表（用 ast，不靠正则的顺序巧合）。"""
    path = os.path.join(HERE, "大肥鱼桌宠.spec")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            if isinstance(fn, ast.Name) and fn.id == "Analysis" and node.value.args:
                first = node.value.args[0]
                if isinstance(first, ast.List):
                    return [elt.value for elt in first.elts]
    raise AssertionError("大肥鱼桌宠.spec 里找不到 Analysis([...]) —— 入口链断在这里没人看得见")


def test_spec_entry_is_main_py():
    """打包入口必须是 main.py（守护入口）。"""
    assert _spec_entries() == ["main.py"], (
        "spec 的入口是 %r —— 打包 exe 上崩溃自动重启不会执行（遗留-1）" % (_spec_entries(),))


def test_main_py_carries_the_entry_marker():
    """老启动器的兼容分支靠这枚 ASCII 标记找主程序；main.py 没有标记 → 老包永远找不到它。"""
    head = open(os.path.join(HERE, "main.py"), encoding="utf-8").read(4096)
    assert "entry-marker: daifeiyu_pet_main" in head, (
        "main.py 前 4KB 里没有 entry-marker: daifeiyu_pet_main（启动桌宠.vbs 的兼容分支会失明）")


def test_entry_name_prefers_main_py(tmp_path):
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "桌宠.py").write_text("", encoding="utf-8")
    assert pet_main.entry_name(str(tmp_path)) == "main.py"


def test_entry_name_falls_back_to_the_legacy_entry(tmp_path):
    """只有老入口的包（或者被用户改名的包）不许因为缺 main.py 就拼出空路径。"""
    (tmp_path / "桌宠.py").write_text("", encoding="utf-8")
    assert pet_main.entry_name(str(tmp_path)) == "桌宠.py"


def test_entry_name_without_any_entry_is_still_the_legacy_name(tmp_path):
    """两个都没有：返回老入口名（调用方拼出一个不存在的路径 —— 用户看得见"打不开"，不是静默）。"""
    assert pet_main.entry_name(str(tmp_path)) == "桌宠.py"


def test_autostart_command_points_at_the_guard_entry(tmp_path):
    """自启命令行必须落到 main.py 上（此前三条兜底全写死 桌宠.py）。"""
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "桌宠.py").write_text("", encoding="utf-8")
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    cmd = pet_main.autostart_command(str(tmp_path), os.path.join(str(tmp_path), "python.exe"))
    assert "main.py" in cmd, "自启命令行没指向 main.py：%r" % (cmd,)
    assert "桌宠.py" not in cmd, "自启命令行还在指老入口：%r" % (cmd,)


def test_autostart_command_keeps_the_legacy_entry_when_there_is_no_main(tmp_path):
    (tmp_path / "桌宠.py").write_text("", encoding="utf-8")
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    cmd = pet_main.autostart_command(str(tmp_path), os.path.join(str(tmp_path), "python.exe"))
    assert "桌宠.py" in cmd, "老包没有 main.py，自启却指向了不存在的入口：%r" % (cmd,)


def test_vbs_prefers_main_py_before_the_marker_scan():
    """顺序不许倒：main.py 与 桌宠.py 现在都带标记，扫标记的结果取决于目录枚举顺序。"""
    text = open(os.path.join(HERE, "启动桌宠.vbs"), encoding="utf-8").read()
    explicit = text.find('fso.FileExists(folder.Path & "\\main.py")')
    assert explicit >= 0, "启动桌宠.vbs 里没有显式的 main.py 分支"
    assert 'target = "main.py"' in text[explicit:], "显式分支找到了却没把 target 设成 main.py"
    scan = text.find("daifeiyu_pet_main", explicit)
    assert scan > explicit, "标记扫描出现在显式 main.py 分支之前（两者都带标记时会随枚举顺序猜错）"

def test_vbs_is_pure_ascii():
    """启动桌宠.vbs 必须**纯 ASCII**：WSH 按 ANSI 代码页解码它，非 ASCII 会吃掉行尾换行。

    v2.12.0 的血案：第 6-8 行新增的中文注释让第 9 行报"缺少语句"——**整个脚本编译失败**，
    而绿色版"双击启动"与开机自启都靠它；唯一的判据只做 text.find()，所以九门全绿。
    机制（本机实测）：UTF-8 无 BOM + CP936 解码，"。"这类字符的末字节会被当成前导字节，
    把后面的 0x0A 一起吃掉 → 两行并一行。

    判据：文件里一个 >0x7F 的字节都不许有。改回中文注释 → 本用例当场红。
    """
    raw = open(os.path.join(HERE, "启动桌宠.vbs"), "rb").read()
    bad = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not bad, (
        "启动桌宠.vbs 混入非 ASCII 字节 %d 个（WSH 按 ANSI 解码，行尾的多字节字符会吃掉换行，"
        "整脚本编译失败）；首个 0x%02X 在偏移 %d" % (len(bad), bad[0][1], bad[0][0]))


def test_autostart_command_second_fallback_still_points_at_the_guard_entry(tmp_path):
    """兜底二：应用目录没有 pythonw.exe → 用解释器同目录的 pythonw，入口仍须是 main.py。

    三审 P1-1 的实测：只把**第一条**兜底改回写死 桌宠.py，8 条用例仍全绿 —— 后两条没人走。
    """
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "桌宠.py").write_text("", encoding="utf-8")
    interp = tmp_path / "runtime"
    interp.mkdir()
    (interp / "pythonw.exe").write_text("", encoding="utf-8")
    cmd = pet_main.autostart_command(str(tmp_path), str(interp / "python.exe"))
    assert "main.py" in cmd and "桌宠.py" not in cmd, "兜底二没指向守护入口：%r" % (cmd,)


def test_autostart_command_last_fallback_still_points_at_the_guard_entry(tmp_path):
    """兜底三：连解释器同目录都没有 pythonw → 直接用解释器本体，入口仍须是 main.py。"""
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "桌宠.py").write_text("", encoding="utf-8")
    interp = tmp_path / "runtime"
    interp.mkdir()
    cmd = pet_main.autostart_command(str(tmp_path), str(interp / "python.exe"))
    assert "main.py" in cmd and "桌宠.py" not in cmd, "兜底三没指向守护入口：%r" % (cmd,)

