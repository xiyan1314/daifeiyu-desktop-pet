# -*- coding: utf-8 -*-
"""
台词库（v2.1 独立台词自定义模块）：文本 + 对白编排，只碰文本。

设计要点
--------
- 唯一运行时数据 = data_dir/lines.json；本文件顶部的常量只是**种子**（首次运行写入，
  之后用户可任意改/删，包括内置台词）。
- 内置台词 id 稳定（bi_<类别>_<序号>）；用户删掉的内置 id 记进 deleted_builtins，
  这样未来版本新增内置台词能自动补进来，而用户删过的不会"复活"。
- 删除是**真删**（不留正文，只留 id 名单，防复活+可撤销）；撤销只保留最近一次破坏性操作。
- 不 import pet_voice / pet_resources（单向依赖：它们可 import 本模块）；
  变更通知走轻量回调（保持零 Qt，可 headless 单测）。

数据结构（lines.json）
---------------------
{"version": 1,
 "lines": [{"id","text","category","role_slot","voice_slot","order","builtin","food"}],
 "dialogues": [{"id","name","line_ids":[...]}],
 "deleted_builtins": ["bi_sajiao_01", ...]}

对外接口
--------
class LineService(data_dir, log=None)
  查询：lines(category=None) / get(line_id) / text_of(line_id) / dialogues() / get_dialogue(id)
        / dialogue_lines(id) / categories() / count()
  修改：add(text, category, role_slot, voice_slot) / save(line_id, **fields)
        / delete(line_id) / delete_many(ids) / clear_all() / restore_builtins()
        / reorder(ids) / undo()
  对白：add_dialogue(name, line_ids) / save_dialogue(id, name, line_ids) / delete_dialogue(id)
  校验：validate_references(role_exists, voice_exists) -> [{line_id, text_preview,
        missing_role, missing_voice, reason}]
  通知：on_changed(cb) / off_changed(cb) / on_invalid_reference(cb) / off_invalid_reference(cb)
        / emit_invalid_reference(items)
"""
import copy
import hashlib
import json
import os
import uuid

import pet_log

# ---------------- 内置台词种子（用户可删可改；仅首次写入，之后以 lines.json 为准） ----------------
LINES_SAJIAO = [
    "不是我干的！真的不是我~",
    "你冤枉我，我要哭给你看！",
    "哼，我才没有偷吃呢！",
    "人家这么可爱，怎么可能是坏蛋！",
    "别凶我嘛……我超乖的。",
    "不听不听，王八念经！",
    "略略略，抓不到我~",
    "我、我什么都不知道！",
    "证据呢？没有证据不能冤枉鱼！",
    "嘶——本专员只是路过案发现场~",
    "蛇蛇我呀，才没有偷吃小鱼干呢！",
    "本专员宣布：蛋糕失窃案与我无关！",
]
LINES_GREEDY = [
    "小鱼干！小鱼干在哪里！",
    "好饿哦……肚子咕咕叫了。",
    "就吃一口，就一口嘛~",
    "蛋糕！是蛋糕！",
    "钻石……亮晶晶，好想要！",
    "我闻到了零食的味道！",
    "偷吃是爱好，被抓住是意外！",
]
LINES_SCARED = [
    "呜哇！吓死我了！",
    "浑身发抖……QAQ",
    "别、别过来！",
    "我差点被吓出本体了！",
    "晕车了……好晕……",
    "心脏都要跳出来了啦！",
]
LINES_HAPPY = [
    "嘿嘿，好玩！",
    "再来一次！",
    "抱抱我嘛~",
    "绳匠最好啦！",
    "耶！",
    "贴贴~",
    "好开心呀！",
    "再夸夸我嘛~",
]
LINES_IDLE = [
    "今天也要元气满满哦！",
    "我在减肥……才怪！",
    "绳匠，陪我玩嘛~",
    "想晒太阳，又想睡懒觉……",
    "你有没有小鱼干呀？",
]
# 开场固定称呼「绳匠」（R 需求：启动即叫绳匠）
LINES_STARTUP = [
    "绳匠，你来啦！今天也最喜欢你~",
    "绳匠！我等你好久啦，抱抱~",
    "绳匠，欢迎回来，小鱼干带了吗？",
    "绳匠，今天也要一起玩哦~",
]
# 摸摸头（长按 1.5 秒触发，借参考插件 petpet 动图概念）
LINES_PETTING = [
    "嘿嘿，摸头好舒服~",
    "嘶——就、就允许你摸一下下…",
    "被绳匠摸头了，尾巴都翘起来了~",
    "再多摸摸嘛，本专员批准了！",
]
FOOD_LINES = {
    "小鱼干": ["小鱼干！最爱啦！", "啊呜~好吃！", "再来一条嘛~"],
    "蛋糕": ["蛋糕！甜到心里啦！", "啊呜~幸福！", "奶油沾到脸上了……"],
    "钻石": ["亮晶晶！我的！", "咬住不放了哦~", "发财啦发财啦！"],
}

# 类别（顺序即 UI 页签顺序）；标签单一来源
LINE_CATEGORIES = ("sajiao", "greedy", "scared", "happy", "idle", "startup", "petting", "food")
CATEGORY_LABELS = {
    "sajiao": "撒娇",
    "greedy": "贪吃",
    "scared": "受惊",
    "happy": "开心",
    "idle": "闲逛",
    "startup": "开场",
    "petting": "摸摸头",
    "food": "喂食",
}
TEXT_MAX = 2000         # 单条台词长度上限（**超出明确报错**，不静默截断；数量不限）
DEFAULT_CATEGORY = "idle"


def _seed_source():
    """内置种子表：[(id, text, category, food)]（id 稳定，供删除名单与去重）。"""
    src = []
    for cat, lst in (("sajiao", LINES_SAJIAO), ("greedy", LINES_GREEDY),
                     ("scared", LINES_SCARED), ("happy", LINES_HAPPY),
                     ("idle", LINES_IDLE), ("startup", LINES_STARTUP),
                     ("petting", LINES_PETTING)):
        for i, t in enumerate(lst, 1):
            src.append(("bi_%s_%02d" % (cat, i), t, cat, ""))
    for food, lst in FOOD_LINES.items():
        for i, t in enumerate(lst, 1):
            # 食物名进 id：中文食物名不能进 id（保持 ASCII 稳定），用序号段位区分
            src.append(("bi_food_%s_%02d" % (_food_key(food), i), t, "food", food))
    return src


def _food_key(food):
    """食物名 → ASCII 稳定键（小鱼干/蛋糕/钻石 三个内建；未知食物用 md5 后缀，
    跨进程稳定——不能用内置 hash()，Python 字符串哈希每次启动都不同）。"""
    known = {"小鱼干": "fish", "蛋糕": "cake", "钻石": "gem"}
    if food in known:
        return known[food]
    return "x" + hashlib.md5(str(food).encode("utf-8")).hexdigest()[:6]


class LineService:
    """台词库：lines.json 持久化 + 增删改查 + 排序 + 对白 + 撤销 + 引用校验。主线程调用。"""

    VERSION = 1

    def __init__(self, data_dir, log=None):
        self._path = os.path.join(data_dir, "lines.json")
        self._log = log or pet_log.log_error
        self._lines = []          # [{id,text,category,role_slot,voice_slot,order,builtin,food}]
        self._dialogues = []      # [{id,name,line_ids}]
        self._deleted = []        # 用户删掉的内置 id（防复活）
        self._undo = None         # 最近一次破坏性操作的快照（内存，会话内可撤销）
        self._changed_cbs = []
        self._invalid_cbs = []
        self._load()

    # ---------------- 持久化 ----------------
    def _load(self):
        data = None
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None  # 有意忽略：首次运行/损坏 → 走种子（首次运行常态）
        self._lines, self._dialogues, self._deleted = [], [], []
        if isinstance(data, dict):
            for ln in (data.get("lines") or []):
                nl = self._norm_line(ln)
                if nl is not None:
                    self._lines.append(nl)
            for d in (data.get("dialogues") or []):
                nd = self._norm_dialogue(d)
                if nd is not None:
                    self._dialogues.append(nd)
            self._deleted = [str(x) for x in (data.get("deleted_builtins") or [])
                             if isinstance(x, str)]
        self._merge_builtins()
        if not self._lines and not self._deleted:
            # 空库且无删除记录 = 首次运行（或数据全损坏）：种子化。
            # 有删除记录说明是用户自己删光的 → 尊重用户，不自动复活。
            self._merge_builtins(force=True)
        self._reindex()

    def _merge_builtins(self, force=False):
        """补入缺失的内置台词：跳过用户删过的 id（防复活）；force=首次种子化。"""
        have = {ln["id"] for ln in self._lines}
        for lid, text, cat, food in _seed_source():
            if lid in have or (not force and lid in self._deleted):
                continue
            self._lines.append({"id": lid, "text": text, "category": cat,
                                "role_slot": None, "voice_slot": None,
                                "order": 0, "builtin": True, "food": food})

    def _reindex(self):
        """按类别+现有顺序重排 order（1..n，无空洞）。"""
        for i, ln in enumerate(self._lines, 1):
            ln["order"] = i

    def _save(self):
        data = {
            "version": self.VERSION,
            "lines": self._lines,
            "dialogues": self._dialogues,
            "deleted_builtins": self._deleted,
        }
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)  # 原子写：半截文件不会被当作有效库
            return ""
        except Exception as e:
            self._log("lines save failed: %r" % (e,))
            return "台词保存失败：%s" % e

    # ---------------- 归一化 ----------------
    @staticmethod
    def _norm_line(ln):
        if not isinstance(ln, dict):
            return None
        lid = str(ln.get("id") or "").strip()
        if not lid:
            return None
        text = str(ln.get("text") or "").strip()
        if not text:
            return None  # 空文本条目直接丢弃（防脏数据）
        cat = str(ln.get("category") or DEFAULT_CATEGORY)
        if cat not in LINE_CATEGORIES:
            cat = DEFAULT_CATEGORY
        return {
            "id": lid,
            "text": text[:TEXT_MAX],
            "category": cat,
            "role_slot": (str(ln["role_slot"]) if ln.get("role_slot") else None),
            "voice_slot": (str(ln["voice_slot"]) if ln.get("voice_slot") else None),
            "order": int(ln.get("order") or 0),
            "builtin": bool(ln.get("builtin")),
            "food": str(ln.get("food") or ""),
        }

    @staticmethod
    def _norm_dialogue(d):
        if not isinstance(d, dict):
            return None
        did = str(d.get("id") or "").strip()
        if not did:
            return None
        ids = d.get("line_ids")
        if not isinstance(ids, list):
            ids = []
        return {"id": did, "name": str(d.get("name") or "未命名对白")[:40],
                "line_ids": [str(x) for x in ids if isinstance(x, (str, int))]}

    # ---------------- 变更通知（轻量回调，零 Qt） ----------------
    def on_changed(self, cb):
        if cb not in self._changed_cbs:
            self._changed_cbs.append(cb)

    def off_changed(self, cb):
        if cb in self._changed_cbs:
            self._changed_cbs.remove(cb)

    def _emit_changed(self):
        for cb in list(self._changed_cbs):
            try:
                cb()
            except Exception as e:
                self._log("line changed cb failed: %r" % (e,))  # 有意忽略：单个监听者失败不影响其余

    def on_invalid_reference(self, cb):
        if cb not in self._invalid_cbs:
            self._invalid_cbs.append(cb)

    def off_invalid_reference(self, cb):
        if cb in self._invalid_cbs:
            self._invalid_cbs.remove(cb)

    def emit_invalid_reference(self, items):
        """把引用校验结果广播给监听者（UI 刷新失效列表/提示条）。"""
        for cb in list(self._invalid_cbs):
            try:
                cb(list(items or []))
            except Exception as e:
                self._log("invalid ref cb failed: %r" % (e,))  # 有意忽略：同上

    # ---------------- 查询 ----------------
    def lines(self, category=None):
        """全部台词（副本，按 order）；category 非空则只取该类别。"""
        out = [copy.deepcopy(ln) for ln in self._lines]
        if category:
            out = [ln for ln in out if ln["category"] == category]
        return sorted(out, key=lambda x: x["order"])

    def get(self, line_id):
        for ln in self._lines:
            if ln["id"] == str(line_id or ""):
                return copy.deepcopy(ln)
        return None

    def text_of(self, line_id):
        ln = self.get(line_id)
        return ln["text"] if ln else ""

    def by_category(self, category):
        """类别文本列表（随机抽取用；无条目返回空列表，调用方自行兜底）。"""
        return [ln["text"] for ln in self.lines(category)]

    def food_texts(self, food):
        """某食物的喂食台词。

        M12 修复：库可用时**不回落到内置常量**（否则用户删光的喂食台词会"复活"）；
        该食物没有任何自定义台词时给一句中性兜底，保证气泡不空、也不复活已删句子。"""
        out = [ln["text"] for ln in self.lines("food") if ln.get("food") == food]
        if out:
            return out
        if self.count() == 0:
            return list(FOOD_LINES.get(food, ["啊呜~好吃！"]))
        return ["啊呜~好吃！"]

    def dialogues(self):
        return copy.deepcopy(self._dialogues)

    def get_dialogue(self, dialogue_id):
        for d in self._dialogues:
            if d["id"] == str(dialogue_id or ""):
                return copy.deepcopy(d)
        return None

    def dialogue_lines(self, dialogue_id):
        """对白解析成有序台词列表；缺失 id 跳过（调用方用 validate 提示失效）。"""
        d = self.get_dialogue(dialogue_id)
        if d is None:
            return []
        out = []
        for lid in d["line_ids"]:
            ln = self.get(lid)
            if ln is not None:
                out.append(ln)
        return out

    def categories(self):
        return list(LINE_CATEGORIES)

    def count(self):
        return len(self._lines)

    # ---------------- 修改 ----------------
    def _snapshot(self, kind):
        self._undo = {"kind": kind, "lines": copy.deepcopy(self._lines),
                      "dialogues": copy.deepcopy(self._dialogues),
                      "deleted": list(self._deleted)}

    def _invalidate_undo(self):
        """M10 修复：非破坏性修改（新增/编辑/排序）之后旧快照不再有效——
        否则"删 A → 新增 B → 撤销"会把 B 一起抹掉（静默丢数据）。"""
        self._undo = None

    def undo(self):
        """撤销最近一次删除/清空。返回 (ok, err)。"""
        if not self._undo:
            return False, "没有可撤销的操作"
        self._lines = self._undo["lines"]
        self._dialogues = self._undo["dialogues"]
        self._deleted = self._undo["deleted"]
        self._undo = None
        err = self._save()
        self._emit_changed()
        return (False, err) if err else (True, "")

    def can_undo(self):
        return self._undo is not None

    def add(self, text, category=DEFAULT_CATEGORY, role_slot=None, voice_slot=None, food=""):
        """新增台词。返回 (line|None, err)。"""
        text = str(text or "").strip()
        if not text:
            return None, "台词不能为空"
        if len(text) > TEXT_MAX:
            return None, "这条太长了（%d 字，单条最多 %d 字）" % (len(text), TEXT_MAX)
        cat = category if category in LINE_CATEGORIES else DEFAULT_CATEGORY
        ln = {"id": "u%s" % uuid.uuid4().hex[:8], "text": text[:TEXT_MAX], "category": cat,
              "role_slot": (str(role_slot) if role_slot else None),
              "voice_slot": (str(voice_slot) if voice_slot else None),
              "order": len(self._lines) + 1, "builtin": False, "food": str(food or "")}
        self._lines.append(ln)
        self._invalidate_undo()
        self._reindex()
        err = self._save()
        self._emit_changed()
        return (None, err) if err else (dict(ln), "")

    def save(self, line_id, text=None, category=None, role_slot=None, voice_slot=None,
             food=None, clear_role=False, clear_voice=False):
        """就地修改（None=不动；clear_role/clear_voice 显式清空引用）。"""
        ln = None
        for x in self._lines:
            if x["id"] == str(line_id or ""):
                ln = x
                break
        if ln is None:
            return False, "台词不存在"
        if text is not None:
            text = str(text).strip()
            if not text:
                return False, "台词不能为空"
            if len(text) > TEXT_MAX:
                return False, "这条太长了（%d 字，单条最多 %d 字）" % (len(text), TEXT_MAX)
            ln["text"] = text
        if category is not None:
            if category not in LINE_CATEGORIES:
                return False, "类别不合法"
            ln["category"] = category
        if food is not None:
            ln["food"] = str(food or "")
        if clear_role:
            ln["role_slot"] = None
        elif role_slot is not None:
            ln["role_slot"] = str(role_slot) or None
        if clear_voice:
            ln["voice_slot"] = None
        elif voice_slot is not None:
            ln["voice_slot"] = str(voice_slot) or None
        self._invalidate_undo()
        err = self._save()
        self._emit_changed()
        return (False, err) if err else (True, "")

    def delete(self, line_id):
        """真删单条（内置也删；内置 id 记入删除名单防复活）。返回 (ok, err)。"""
        ln = None
        for x in self._lines:
            if x["id"] == str(line_id or ""):
                ln = x
                break
        if ln is None:
            return False, "台词不存在"
        self._snapshot("delete")
        self._lines = [x for x in self._lines if x["id"] != ln["id"]]
        if ln.get("builtin") and ln["id"] not in self._deleted:
            self._deleted.append(ln["id"])
        for d in self._dialogues:  # 对白里同步移除（顺序自动重排，不留空洞）
            d["line_ids"] = [x for x in d["line_ids"] if x != ln["id"]]
        self._reindex()
        err = self._save()
        self._emit_changed()
        return (False, err) if err else (True, "")

    def delete_many(self, line_ids):
        """批量删除。返回 (删除条数, err)。"""
        ids = {str(x) for x in (line_ids or [])}
        if not ids:
            return 0, "没有选中台词"
        hit = [x for x in self._lines if x["id"] in ids]
        if not hit:
            return 0, "台词不存在"
        self._snapshot("delete_many")
        for ln in hit:
            if ln.get("builtin") and ln["id"] not in self._deleted:
                self._deleted.append(ln["id"])
        self._lines = [x for x in self._lines if x["id"] not in ids]
        for d in self._dialogues:
            d["line_ids"] = [x for x in d["line_ids"] if x not in ids]
        self._reindex()
        err = self._save()
        self._emit_changed()
        return (0, err) if err else (len(hit), "")

    def clear_all(self):
        """清空全部台词与对白（调用方须二次确认）。返回 (ok, err)。"""
        self._snapshot("clear_all")
        for ln in self._lines:
            if ln.get("builtin") and ln["id"] not in self._deleted:
                self._deleted.append(ln["id"])
        self._lines = []
        self._dialogues = []
        err = self._save()
        self._emit_changed()
        return (False, err) if err else (True, "")

    def restore_builtins(self):
        """把内置台词补回来（清掉删除名单）。返回补回条数。"""
        self._snapshot("restore")
        self._deleted = []
        before = len(self._lines)
        self._merge_builtins(force=False)
        self._reindex()
        self._save()
        self._emit_changed()
        return len(self._lines) - before

    def reorder(self, ids_in_order):
        """按给定 id 顺序重排（只影响列出的 id，剩余保持相对位置在后）。返回 (ok, err)。"""
        order = [str(x) for x in (ids_in_order or [])]
        if not order:
            return False, "顺序为空"
        pos = {lid: i for i, lid in enumerate(order)}
        ranked = sorted(self._lines, key=lambda x: (pos.get(x["id"], len(pos) + x["order"]),
                                                    x["order"]))
        self._lines = ranked
        self._invalidate_undo()
        self._reindex()
        err = self._save()
        self._emit_changed()
        return (False, err) if err else (True, "")

    # ---------------- 对白 ----------------
    def add_dialogue(self, name, line_ids=None):
        """新建对白（有序台词 id 列表）。返回 (dialogue|None, err)。"""
        ids = [str(x) for x in (line_ids or [])]
        if not ids:
            return None, "对白至少要有一条台词"
        known = {ln["id"] for ln in self._lines}
        miss = [x for x in ids if x not in known]
        if miss:
            return None, "有 %d 条台词不存在，无法编排" % len(miss)
        d = {"id": "d%s" % uuid.uuid4().hex[:8], "name": str(name or "未命名对白")[:40],
             "line_ids": ids}
        self._dialogues.append(d)
        self._invalidate_undo()
        err = self._save()
        self._emit_changed()
        return (None, err) if err else (dict(d), "")

    def save_dialogue(self, dialogue_id, name=None, line_ids=None):
        """改对白名/顺序/成员（None=不动）。返回 (ok, err)。"""
        d = None
        for x in self._dialogues:
            if x["id"] == str(dialogue_id or ""):
                d = x
                break
        if d is None:
            return False, "对白不存在"
        if name is not None:
            d["name"] = str(name or "未命名对白")[:40]
        if line_ids is not None:
            ids = [str(x) for x in line_ids]
            known = {ln["id"] for ln in self._lines}
            miss = [x for x in ids if x not in known]
            if miss:
                return False, "有 %d 条台词不存在" % len(miss)
            d["line_ids"] = ids
        self._invalidate_undo()
        err = self._save()
        self._emit_changed()
        return (False, err) if err else (True, "")

    def delete_dialogue(self, dialogue_id):
        """删除整段对白。返回 (ok, err)。"""
        d = None
        for x in self._dialogues:
            if x["id"] == str(dialogue_id or ""):
                d = x
                break
        if d is None:
            return False, "对白不存在"
        self._snapshot("delete_dialogue")
        self._dialogues = [x for x in self._dialogues if x["id"] != d["id"]]
        err = self._save()
        self._emit_changed()
        return (False, err) if err else (True, "")

    # ---------------- 引用校验 ----------------
    def validate_references(self, role_exists, voice_exists):
        """扫描失效引用（不自动删、不自动替换）。

        role_exists(slot)->bool / voice_exists(slot)->bool 由调用方注入（单向依赖，不 import）。
        返回 [{"line_id","text_preview","missing_role","missing_voice","reason"}]
        """
        out = []
        for ln in self.lines():
            miss_role = bool(ln.get("role_slot")) and not role_exists(ln["role_slot"])
            miss_voice = bool(ln.get("voice_slot")) and not voice_exists(ln["voice_slot"])
            if not (miss_role or miss_voice):
                continue
            why = []
            if miss_role:
                why.append("角色不存在（可能已删除或重新导入后 ID 变了）")
            if miss_voice:
                why.append("声音素材不存在（可能已删除或重新导入后 ID 变了）")
            out.append({
                "line_id": ln["id"],
                "text_preview": (ln["text"][:24] + "…") if len(ln["text"]) > 24 else ln["text"],
                "missing_role": ln.get("role_slot") if miss_role else None,
                "missing_voice": ln.get("voice_slot") if miss_voice else None,
                "reason": "；".join(why),
            })
        return out


if __name__ == "__main__":
    # 命令行冒烟：无 GUI 自检（python pet_lines.py）
    import tempfile
    _svc = LineService(tempfile.mkdtemp(prefix="lines_"))
    assert _svc.count() >= len(LINES_SAJIAO) + len(LINES_GREEDY)
    _ln, _err = _svc.add("测试台词", "happy")
    assert _ln is not None and not _err, _err
    assert _svc.get(_ln["id"])["text"] == "测试台词"
    assert _svc.delete(_ln["id"]) == (True, "")
    assert _svc.get(_ln["id"]) is None
    assert _svc.undo()[0] is True and _svc.get(_ln["id"]) is not None
    _bi = _svc.lines("sajiao")[0]["id"]
    assert _svc.delete(_bi) == (True, "")
    _svc2 = LineService(os.path.dirname(_svc._path))
    assert _svc2.get(_bi) is None  # 删过的内置不复活
    print("SMOKE OK")
