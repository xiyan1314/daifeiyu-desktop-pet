# -*- coding: utf-8 -*-
"""素材热重载的纯逻辑（零 Qt）：文件签名 + 变更判定 + 监听面收集。

为什么单独一个模块：QTimer 在 pytest 里只能等（慢且抖），判据会退化成"等 2 秒看有没有变"。
把"该不该重载"拆成纯函数后，判据可以喂假 stat / 假目录，1ms 内确定地测完；窗口侧只剩
"起表 + 变了就 _reload_sprites"这一行接线（接线本身另有一条真窗口的端到端判据）。

语义（对齐 plan §24.3 的"素材热重载"）：
  · 用户改/加/删素材文件 → 下一次 poll 返回变化的路径；
  · 只读访问（atime 变、内容没变）→ 不算变化；
  · 删除也算一次变化（下次重载会回退缺省图，而不是继续贴旧图）。

监听面**只包括内置 assets/ 与根级 character*.png**，不包括用户角色文件：
用户角色是用户数据，编辑到一半的半成品 PNG 不该被自动读进来（角色切换有显式的
apply_role 重载路径）。这条边界写进 README 与判据。
"""
import os


def snapshot(paths, stat=None):
    """路径列表 → {path: (mtime_ns, size)}。

    契约：**传入的路径都应当存在**（collect 侧只收存在文件）。删除的判定不在这里：
    文件没了 → collect 不再返回它 → diff 把它当"变化"。这样本函数没有静默 except
    （读不到就往上抛，由调用方记日志/重起基线）。
    """
    stat = stat or os.stat
    out = {}
    for p in paths:
        st = stat(p)
        out[p] = (int(getattr(st, "st_mtime_ns", 0) or 0), int(getattr(st, "st_size", 0) or 0))
    return out


def diff(old, new):
    """两份签名 → 发生变化的路径（新增/修改/删除，排序）。"""
    return sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p))


class Watcher(object):
    """起一份基线，之后每次 poll() 返回"自上次 poll 以来变了哪些文件"。"""

    def __init__(self, collect, stat=None):
        self._collect = collect
        self._stat = stat
        self._snap = None

    def prime(self):
        """重新起基线（窗口构造、目录被整体替换后调用）。返回监听文件数。"""
        self._snap = snapshot(self._collect(), self._stat)
        return len(self._snap)

    def poll(self):
        """返回变化路径列表；没有基线时先起基线并返回 []（不把"第一次看"当变化）。"""
        cur = snapshot(self._collect(), self._stat)
        if self._snap is None:
            self._snap = cur
            return []
        changed = diff(self._snap, cur)
        if changed:
            self._snap = cur
        return changed


def collect_assets(assets_dir, root_files=()):
    """assets/ 全树 + 根级文件清单（不存在的自动跳过）。"""
    paths = []
    if assets_dir and os.path.isdir(assets_dir):
        for base, _dirs, files in os.walk(assets_dir):
            for name in files:
                paths.append(os.path.join(base, name))
    for p in root_files:
        if os.path.isfile(p):
            paths.append(p)
    return sorted(set(paths))