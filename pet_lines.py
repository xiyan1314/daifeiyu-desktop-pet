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
import os
import uuid

import pet_io   # v2.3.1：全仓共用原子写（分锁 + 线程唯一临时名 + replace 重试）
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

# v2.1.2：情绪台词也纳入台词库（此前写死在 pet_mood，用户改不了）
LINES_MOOD_PUZZLED = [
    "咦？绳匠在戳我？",
    "干嘛呀……人家在睡觉呢。",
    "唔？你碰到我啦？",
    "咦咦咦？发生什么了？",
]
LINES_MOOD_ANGRY = [
    "又戳！我要生气啦！",
    "再戳我咬你哦！",
    "哼！别闹了啦！",
    "我、我真的会生气的！",
    "你戳上瘾了是不是！",
]
LINES_MOOD_HISS = [
    "哈——！别过来！",
    "咝——我要翻脸啦！",
    "再戳我，我就躲进水里不出来了！",
    "哼，喜欢的东西我可是会咬住不放的！",
]
LINES_MOOD_DROOL = [
    "绳匠，小鱼干在哪里！",
    "好香呀……口水都要流下来啦！",
    "就吃一口，就一口嘛~",
    "我闻到了零食的味道！",
    "那个看起来好好吃……",
]
LINES_MOOD_CRY = [
    "呜……绳匠都不给我吃……",
    "人家等了好久好久……",
    "QAQ 好委屈，我要哭给你看！",
    "肚子咕咕叫，你却不管我……",
    "哼……不理你了……",
]
LINES_MOOD_SMUG = [
    "嘿嘿，是我干的~",
    "略略略，绳匠抓不到我~",
    "又干了一件坏事，开心！",
    "喜欢的，就咬住不放~",
    "嘿嘿嘿，谁让你没看见呢~",
]
LINES_MOOD_BLUSH = [
    "诶？绳匠夸我了……",
    "才、才没有很开心呢！",
    "被绳匠夸了……嘿嘿~",
    "别一直夸啦，脸都红了……",
    "绳匠觉得我可爱吗？",
]
MOOD_LINES = {
    "mood_puzzled": LINES_MOOD_PUZZLED,
    "mood_angry": LINES_MOOD_ANGRY,
    "mood_hiss": LINES_MOOD_HISS,
    "mood_drool": LINES_MOOD_DROOL,
    "mood_cry": LINES_MOOD_CRY,
    "mood_smug": LINES_MOOD_SMUG,
    "mood_blush": LINES_MOOD_BLUSH,
}

# 类别（顺序即 UI 页签顺序）；标签单一来源
LINE_CATEGORIES = ("sajiao", "greedy", "scared", "happy", "idle", "startup", "petting", "food",
                   "mood_puzzled", "mood_angry", "mood_hiss", "mood_drool", "mood_cry",
                   "mood_smug", "mood_blush")
CATEGORY_LABELS = {
    "sajiao": "撒娇",
    "greedy": "贪吃",
    "scared": "受惊",
    "happy": "开心",
    "idle": "闲逛",
    "startup": "开场",
    "petting": "摸摸头",
    "food": "喂食",
    "mood_puzzled": "戳·疑惑",
    "mood_angry": "戳·生气",
    "mood_hiss": "戳·炸毛",
    "mood_drool": "饿了",
    "mood_cry": "委屈",
    "mood_smug": "得意",
    "mood_blush": "被夸",
}
TEXT_MAX = 2000         # 单条台词长度上限（**超出明确报错**，不静默截断；数量不限）
DEFAULT_CATEGORY = "idle"

# v2.4（M4）："脏读"（lines.json 在磁盘上却读不到——记事本「ANSI」另存成 GBK、共享占用）
# 时启动弹一次的文案。措辞必须与事实一致：.bak 是**下一次保存前**才落的，此刻还没有。
DIRTY_READ_NOTICE = ("lines.json 不是 UTF-8（记事本另存成 ANSI 了？），本次已忽略原文件；"
                     "改台词前会先把它备份成 lines.json.bak")


def _seed_source():
    """内置种子表：[(id, text, category, food)]（id 稳定，供删除名单与去重）。"""
    src = []
    for cat, lst in (("sajiao", LINES_SAJIAO), ("greedy", LINES_GREEDY),
                     ("scared", LINES_SCARED), ("happy", LINES_HAPPY),
                     ("idle", LINES_IDLE), ("startup", LINES_STARTUP),
                     ("petting", LINES_PETTING)):
        for i, t in enumerate(lst, 1):
            src.append(("bi_%s_%02d" % (cat, i), t, cat, ""))
    for cat, lst in MOOD_LINES.items():
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
        # v2.4（M4）：本次启动"文件在磁盘上但没读到"（编码不是 UTF-8 / 共享占用）——
        # 内存里只有内置种子。此时一个字节都不写是 v2.3.1 定下的口径，但用户**下一次编辑**
        # 就会把原文整体覆盖成 UTF-8 种子库，所以写前必须留 .bak（见 _save）。
        self._dirty_read = False
        self._dirty_backed = False
        self._load()

    @property
    def dirty_read(self):
        """启动时 lines.json 在磁盘上却没读到 → True（调用方据此弹一次提示气泡）。"""
        return self._dirty_read

    # ---------------- 持久化 ----------------
    def _load(self):
        """读 lines.json 并归一化；**只有真损坏**才回写（v2.3.1 兼容审查 S1 修复）。

        读路径统一走 pet_io（utf-8-sig）。旧实现自己 open(..., encoding="utf-8") 并把
        ValueError / UnicodeDecodeError 一律当"内容坏了"→ data=None → 末尾 _save() 回写
        **内置种子库**：带 UTF-8 BOM 的合法 lines.json（103 字节、1 条自定义台词）会被
        改写成 20269 字节的种子库，用户台词全丢且零日志；GBK 另存的同理。现在：

        - 文件不存在（首次运行）→ 种子，并落盘；
        - 真解析失败 / 顶层不是对象 → **先留 .bak** 再回写种子（愈合留证，判错可恢复）；
        - 读取失败（权限/共享占用）或非 UTF-8 编码 → **一个字节都不写**（不能证明损坏）。
        """
        data, corrupted = pet_io.read_json_or(self._path, lambda: None, expect=dict,
                                              log=self._log)
        # data is None 且不是"损坏" → 要么文件不存在（首次运行），要么这次没读到（不写）
        _unreadable = data is None and os.path.exists(self._path)
        # v2.4（M4）：脏读标记。corrupted 那条路径下面已经留了 .bak 并主动愈合，
        # 不算脏读（否则 _save 会再覆盖一次 .bak 并多记一行"旧备份被覆盖"）。
        self._dirty_read = bool(_unreadable and not corrupted)
        self._dirty_backed = False
        self._lines, self._dialogues, self._deleted = [], [], []
        if isinstance(data, dict):
            for ln in (data.get("lines") or []):
                nl = self._norm_line_checked(ln)  # 超长截断会留痕（不静默砍数据）
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
        # v2.3.1（评审报告根因 B 的同类遗留）：之前这里是"坏 lines.json 只报错、被动等下次
        # 写盘才愈合"。现在与 memory/alarms/behaviors/索引 同口径——**读到真坏就回写一次**
        # 愈合文件，让坏数据不再每次启动重报。
        # v2.3.1（兼容审查 S1）：判据从"data is None"收紧成"真损坏 / 文件不存在"——
        # 读失败（OSError）与编码不是 UTF-8 都不能证明文件坏了，绝不回写覆盖。
        # 报错走注入的 self._log（此前这里写的是全局 _log_error，本模块并没有这个名字）。
        if corrupted or (data is None and not _unreadable):
            if corrupted:
                pet_io.backup_before_heal(self._path, self._log)
            err = self._save()
            if err:
                self._log("lines heal save failed: %s" % err)

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
        # v2.4（M4）：本次启动是脏读时，内存里只有内置种子——这一写就把用户原文永久覆盖了。
        # 与 pet_book._read_failed 同口径：**写前**先留一份 .bak（一次脏读只留一份，写失败
        # 重试不重复覆盖），保存成功后清标记回到正常路径。
        if self._dirty_read and not self._dirty_backed:
            if pet_io.backup_before_heal(self._path, self._log):
                self._dirty_backed = True
        # v2.3.1：统一走 pet_io（分锁 + 线程唯一临时名 + replace 重试）——
        # 此前固定 "<lines>.tmp" 且无锁，两个保存点交错会互相截断
        err = pet_io.atomic_write_json(self._path, data, log=self._log)
        if err is None:
            if self._dirty_read:
                _had_bak = self._dirty_backed   # 备份失败时日志不能谎称已留证
                self._dirty_read = False
                self._dirty_backed = False
                self._log("lines.json 已按 UTF-8 重建（原文件此前不是 UTF-8 或读不到；%s）"
                          % ("原文已留 .bak" if _had_bak else "**备份失败**，原文已被覆盖"))
            return ""
        return "台词保存失败：%s" % err

    # ---------------- 归一化 ----------------
    def _norm_line_checked(self, ln):
        """_norm_line + 超长截断留痕（手改 lines.json 的超长行会被截断，但必须可追溯）。"""
        out = self._norm_line(ln)
        if out is not None:
            raw = str((ln or {}).get("text") or "").strip()
            if len(raw) > TEXT_MAX:
                self._log("line %s text truncated %d -> %d chars"
                          % (out.get("id"), len(raw), TEXT_MAX))
        return out

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
        # v2.2.5：字段级类型容错——手改 lines.json 的 "order": "abc" 此前会让
        # LineService.__init__ 抛 ValueError → 程序启动直接失败（docstring 承诺的"损坏走种子"
        # 只覆盖 JSON 解析失败，不覆盖字段类型错误）。此处逐字段兜底，坏值按 0 处理。
        try:
            order = int(ln.get("order") or 0)
        except (TypeError, ValueError):
            order = 0
        # v2.3.1（兼容审查 M1）：**先复制原条目**再覆盖已知键——此前这里"重建已知键"，
        # 会把用户手加的备注/未来版本写入的新字段在"读取时归一化回写"这一步永久删掉。
        # 与 pet_alarm._norm_alarm / pet_behaviors._norm_behavior 同口径。
        out = dict(ln)
        out.update({
            "id": lid,
            "text": text[:TEXT_MAX],
            "category": cat,
            "role_slot": (str(ln["role_slot"]) if ln.get("role_slot") else None),
            "voice_slot": (str(ln["voice_slot"]) if ln.get("voice_slot") else None),
            "order": order,
            "builtin": bool(ln.get("builtin")),
            "food": str(ln.get("food") or ""),
        })
        return out

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

    def texts_by_category(self, category):
        """类别文本列表（**免深拷贝**版，供刷新台词池等高频路径用）。

        与 by_category 的差别：不 deepcopy 每条台词（几千条时明显更快）。
        返回的是新列表（可安全持有），但元素是内部字符串（不可变，无副作用）。"""
        return [ln["text"] for ln in self._lines if ln["category"] == category]

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
