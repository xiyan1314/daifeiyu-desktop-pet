# -*- coding: utf-8 -*-
"""
大肥鱼桌宠 —— 资源库模块（角色库 + 音频库 + 声音素材库）。

v2.1 新增 VoiceAssetLibrary（声音素材/参考音）：与音效片段**分开存储**
（data/voice_ref/ + voice_assets.json），专供声音克隆后端；
RoleLibrary / VoiceAssetLibrary 都提供 on_deleted 回调，供上层清理失效引用。

职责：参考 dsh-whale-widget 的「角色管理 / 音频片段管理 / 音效组」设计，把
自定义角色（透明 PNG）与自定义音频（wav/mp3）的导入、切换、重命名、删除，
以及自定义音效组（5 个事件槽位）的管理统一封装。供 pet_dialogs 的面板与
主程序（桌宠.py）调用。

对外接口：
- class RoleLibrary(data_dir)
    目录 data_dir/roles/，索引 data_dir/roles.json（{"roles":[...], "active":id}）。
    list_roles() -> [{"id","name","file","form","file_full","frames","added"}...]  # 默认角色不在列表
    active_id() -> str                                     # "" = 默认角色
    set_active(role_id) -> bool                            # "" 回默认
    active_path() -> str|None                              # 当前角色 png 绝对路径；默认角色 None
    path_for(role_id) -> str|None                          # 任意角色 png 绝对路径（面板预览用）
    path_for_full(role_id) -> str|None                     # 吃饱形态 png；单形态返回 None
    import_file(src, name=None) -> (role|None, err|None)   # 旧版单图导入（v1.3.0 兼容，单形态）
    import_processed(base_src, full_src=None, name=None,  # 单/双形态导入（面板新入口）
                      frames_src=None,                     #   full_src=None → form="single"；
                      forms_src=None,                      #   frames_src=2~24 帧 → 帧动画角色
                      interval_ms=None, render=None,       # P1-7 新参数（全可选，旧调用兼容）
                      states=None, keep_source=False,      #   render={anchor/scale/offset}、
                      source_files=None)                   #   states={状态:png}、原图保留 source/
    update(role_id, patch) -> (bool, str)                  # P1-7 就地编辑（改名/换图/调序/渲染
                                                           #   参数/动画/状态图，id 不变，只改索引）
    form_animations(role_id) -> [{动作键: 路径...}+interval_ms...]      # P1-7/v2.0.1 逐形态动画路径
                                                            #   （内建 + 自定义命名帧动作 + 帧间隔合并键）
    form_state_paths(role_id) / form_front_paths(role_id)  # P1-7 状态资源图/front 路径（逐形态对齐）
    is_v2(role_id) -> bool                                 # P1-7 新结构角色标记
    delete(role_id) -> (bool, str)                         # 删全部素材文件+索引；active 则重置 ""
    get(role_id) -> dict|None
- class AudioLibrary(data_dir)
    目录 data_dir/audio/，索引 data_dir/audio.json
    （{"fragments":[...], "group":{"custom":{"press":...,"release":...,"feed":...,"reply":...,"coin":...}}}）。
    fragments() -> [{"id","name","file","ext","added","duration"}...]  # duration 仅 wav 探测
    fragment_path(fid) -> str|None
    import_file(src, name=None) -> (frag|None, err|None)   # 仅 .wav/.mp3，>20MB 拒绝
    delete(fid) -> (bool, str)                             # 被音效组槽位引用则同步置 ""
    rename(fid, new_name) -> (bool, str)
    group_slots() -> dict                                 # {"custom": {kind: fid|""|None}}
    set_slot(kind, fid) -> bool                           # kind 非法 False；""=静音；None=默认
    group_paths() -> dict                                 # {"press": path|""|None, ...}
                                                          #   None=未设置走内置默认；""=静音；
                                                          #   path=绝对路径（文件缺失返回 None）

实现要点：
- 纯标准库（os/json/time/uuid/shutil/wave），不依赖 PySide6，无 GUI 可运行。
- 全部文件 IO 走「写临时文件 + os.replace」原子替换；任何异常降级，
  以错误字符串返回，绝不向调用方抛异常（索引损坏/读取失败记入 error.log）。
- import_file 只校验扩展名与文件大小，不校验音频/图片内容（PNG 可加载性与
  透明通道由 pet_dialogs 用 QPixmap 把关）。
- 槽位三态：None（默认，走内置音效）/ ""（静音）/ 片段 id（自定义音）。

Python 3.10+（项目运行环境 3.10.2）。

MIT License
Copyright (c) 大肥鱼桌宠项目
"""

import json
import os
import re
import shutil
import time
import uuid
import wave

import pet_log

# P3-5+：帧动画上限（读侧与导入管线共用；由 桌宠 启动时按 cfg["role_frame_max"] 同步，
# 用户可在「设置… → 帧数上限…」里改，范围 2~60）
# P1-7：上限同样作用于每个动画动作（animations 各动作读侧截断与导入/编辑拒绝）
FRAME_MAX = 24

# P1-7：动画动作全集（forms[i].animations 的合法键；帧动画播放按「形态×动作」查表）
ANIM_ACTIONS = ("idle", "eat", "poke", "sleep")

# v2.0.1：动作自定义——内建动作之外的任意命名帧动作（ASCII 安全名，供文件/菜单/行为引用）
CUSTOM_ACTION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,23}$")

# v2.0.1：程序化合成动作（从角色贴图本身合成，无需额外素材——「动作合成」路径）
PROC_KINDS = ("breathe", "sway", "nod")
DEFAULT_PROC_PARAMS = {
    "breathe": {"amp": 0.04, "period_ms": 1600},  # 呼吸：整体轻微缩放
    "sway": {"amp": 0.06, "period_ms": 1800},     # 摇摆：左右轻微晃动
    "nod": {"amp": 12.0, "period_ms": 1400},      # 点头：上下位移（px）
}
# v2.0.1：amp 量纲随 kind 不同——breathe/sway 是缩放系数（0.001~1.0），
# nod 是位移像素（1~64px）。归一化与编辑对话框共用同一口径，避免默认 12px 被钳成 1px。
PROC_AMP_BOUNDS = {
    "breathe": (0.001, 1.0),
    "sway": (0.001, 1.0),
    "nod": (1.0, 64.0),
}

# v2.0.1：动作名保留词——play_action 内建分支（jump/emote/none）先于帧集命中，
# interval_ms 会被 form_animations 合并键覆盖：这些名字作自定义动作名永远是死条目。
ACTION_RESERVED = ("jump", "emote", "none", "interval_ms")


def is_valid_custom_action(name):
    """v2.0.1：自定义动作名校验——ASCII 安全名且不与内建动作/保留词重名。"""
    return (isinstance(name, str) and bool(CUSTOM_ACTION_RE.match(name))
            and name not in ANIM_ACTIONS and name not in ACTION_RESERVED)

# P1-7：状态名全集（forms[i].states 资源图合法键；与 pet_widgets._STATE_MARK_MAP
# 同源——未配置的状态走程序化叠图兜底，向后兼容）。pet_resources 保持 Qt-free，
# 故状态名在此以常量维护，桌宠/测试引用同一口径。
STATE_NAMES = ("sleep", "puzzled", "angry", "hiss", "cry",
               "laugh", "smug", "surprised", "drool", "blush")

# P1-7：形态渲染参数默认值（anchor 缺省 0.5/0.5 = 旧版居中行为；scale 缺省 None
# = 不额外缩放；offset 缺省 (0, 0)）
DEFAULT_ANCHOR = {"x": 0.5, "y": 0.5}


def _clamp01(v, default=0.5):
    """数值夹到 0~1；非数值给 default。"""
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return default


def _norm_anchor(v):
    """P1-7：anchor 归一化 {"x","y"}（0~1 相对锚点）；非法输入回默认 (0.5, 0.5)。"""
    if isinstance(v, dict):
        return {"x": _clamp01(v.get("x"), 0.5), "y": _clamp01(v.get("y"), 0.5)}
    return dict(DEFAULT_ANCHOR)


def _norm_offset(v):
    """P1-7：offset 归一化 {"x","y"}（px 整数）；非法输入回 (0, 0)。"""
    out = {"x": 0, "y": 0}
    if isinstance(v, dict):
        for k in ("x", "y"):
            try:
                out[k] = int(round(float(v.get(k, 0))))
            except (TypeError, ValueError):
                out[k] = 0
    return out


def _norm_animations(v):
    """P1-7/v2.0.1：animations 归一化 dict[str, list[str]]（每动作 png 文件名列表）。

    键 = 内建动作（ANIM_ACTIONS）或用户自定义动作（is_valid_custom_action：
    ASCII 安全名且非保留词 jump/emote/none/interval_ms）；非法结构/非法键丢弃；
    每个动作的帧数截断到 FRAME_MAX（与导入拒绝同口径）。"""
    if not isinstance(v, dict):
        return {}
    out = {}
    for act, lst in v.items():
        if not isinstance(act, str) or not (act in ANIM_ACTIONS or is_valid_custom_action(act)):
            continue
        if not isinstance(lst, list):
            continue
        files = [str(x) for x in lst if str(x).lower().endswith(".png")][:FRAME_MAX]
        if files:
            out[act] = files
    return out


def _norm_procs(v):
    """v2.0.1：程序化合成动作归一化 {名字: {kind, amp, period_ms}}。

    kind 白名单 PROC_KINDS；amp 按 kind 钳制（breathe/sway 0.001~1.0 缩放系数，
    nod 1~64px 位移）；period_ms 钳 200~10000；非法条目丢弃（不崩）。
    名字须通过 is_valid_custom_action（内建动作名/保留词 jump·emote·none·interval_ms
    重名条目丢弃）：play_action 先查帧集与内建分支，重名合成动作永远不可达
    （死条目不保留）。"""
    if not isinstance(v, dict):
        return {}
    out = {}
    for name, p in v.items():
        if not is_valid_custom_action(name):
            continue
        if not isinstance(p, dict):
            continue
        kind = p.get("kind")
        if kind not in PROC_KINDS:
            continue
        d = DEFAULT_PROC_PARAMS[kind]
        lo, hi = PROC_AMP_BOUNDS.get(kind, (0.001, 1.0))
        try:
            amp = min(hi, max(lo, float(p.get("amp", d["amp"]))))
        except (TypeError, ValueError):
            amp = d["amp"]
        try:
            period = min(10000, max(200, int(p.get("period_ms", d["period_ms"]))))
        except (TypeError, ValueError):
            period = d["period_ms"]
        out[name] = {"kind": kind, "amp": amp, "period_ms": period}
    return out


def _flag_true(v):
    """v2.0.2 断点#12：形态标记严格布尔（True/1/"1"/"true" 为真；"false"/"0" 不算）。"""
    return v is True or v == 1 or v == "1" or v == "true"


def _norm_states(v):
    """P1-7：states 归一化 {状态名: png 文件名}；未在 STATE_NAMES 的键丢弃。"""
    if not isinstance(v, dict):
        return {}
    out = {}
    for k, val in v.items():
        if k in STATE_NAMES and isinstance(val, str) and val.lower().endswith(".png"):
            out[k] = val
    return out


def animation_frames(role, form_idx=0, action="idle"):
    """P1-7 纯函数：按「形态×动作」查动画帧文件名（读侧视角，不含文件 IO）。

    role 为归一化角色 dict（RoleLibrary.get / list_roles 返回）；
    form_idx 越界或该形态未配置该动作返回 []。
    """
    forms = role.get("forms") or []
    if not (isinstance(form_idx, int) and 0 <= form_idx < len(forms)):
        return []
    return list((forms[form_idx].get("animations") or {}).get(action, []) or [])


def form_render(role, form_idx=0):
    """P1-7 纯函数：形态渲染参数（含默认值）。

    返回 {"anchor": (x, y), "scale": float|None, "offset": (x, y)}；
    缺省 = 旧行为（居中、不额外缩放、无位移）。form_idx 越界返回默认值。
    """
    forms = role.get("forms") or []
    fm = forms[form_idx] if (isinstance(form_idx, int) and 0 <= form_idx < len(forms)) else {}
    anchor = _norm_anchor(fm.get("anchor"))
    sc = fm.get("scale")
    scale = float(sc) if isinstance(sc, (int, float)) and sc > 0 else None
    off = _norm_offset(fm.get("offset"))
    return {"anchor": (anchor["x"], anchor["y"]), "scale": scale, "offset": (off["x"], off["y"])}


def state_resource(role, form_idx, state):
    """P1-7 纯函数：forms[form_idx].states[state] 文件名（资源图优先查询）；无返回 None。

    显示侧优先级（P2-5）：资源图 → 程序化叠图；本函数只负责资源图查表，
    兜底叠图在 桌宠._build_state_pix 合并处实现。
    """
    forms = role.get("forms") or []
    if not (isinstance(form_idx, int) and 0 <= form_idx < len(forms)):
        return None
    return (forms[form_idx].get("states") or {}).get(state)

# ---------------- 通用 IO 助手（原子替换，降级不抛） ----------------
def _read_json(path, factory=dict):
    """读 JSON；文件缺失 / 损坏 / 结构非法时返回 factory() 默认值，绝不抛出。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        # 首次运行无文件=正常（静默）；文件存在但读取失败=真实故障，记日志
        if os.path.exists(path):
            pet_log.log_error("pet_resources._read_json 读取失败（按默认值重建）: %r" % (e,))
    return factory()


def _write_json(path, data):
    """原子写 JSON（临时文件 + os.replace）；成功返回 None，失败返回错误字符串。"""
    tmp = path + ".tmp"
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return None
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass  # 有意忽略：临时文件清理尽力而为，失败不影响主流程
        return str(e)


def _probe_png(path):
    """stdlib PNG 校验：魔数 + IHDR 尺寸合理。返回 (ok, err)。"""
    try:
        with open(path, "rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                return False, "不是有效的 PNG 文件"
            head = f.read(25)  # IHDR 长度(4) + 类型(4) + 数据(13) + CRC(4)
            if len(head) < 25 or head[4:8] != b"IHDR":
                return False, "PNG 头损坏"
            w = int.from_bytes(head[8:12], "big")
            h = int.from_bytes(head[12:16], "big")
            if w <= 0 or h <= 0 or w > 100000 or h > 100000:
                return False, "PNG 尺寸非法"
        return True, ""
    except Exception as e:
        return False, "无法读取：%s" % e


def _new_id():
    """生成片段/角色 id：8 位十六进制 uuid 前缀 + 时间戳，保证文件名安全且唯一。"""
    return uuid.uuid4().hex[:8] + "_" + str(int(time.time()))


def _probe_wav_ok(path):
    """WAV 头校验：PCM 且参数合理。返回 bool。"""
    try:
        with wave.open(path, "rb") as wf:
            nch, sw, fr, nf, ct, _ = wf.getparams()
        return ct == "NONE" and 0 < nf <= 25_000_000 and fr > 0 and nch > 0 and sw in (1, 2, 4)
    except Exception:
        return False


def _wav_duration(path):
    """用 wave 模块探测 WAV 时长（秒，两位小数）；失败 / 非 wav 返回 None。"""
    try:
        with wave.open(path, "rb") as wf:
            _nch, _sw, framerate, nframes, _ct, _x = wf.getparams()
        if framerate and nframes > 0:
            return round(nframes / float(framerate), 2)
    except Exception:
        pass  # 有意忽略：时长探测失败按无时长处理（导入校验另有 _probe_wav_ok 把关）
    return None


# ---------------- 角色库 ----------------
class RoleLibrary:
    """自定义角色管理：导入 / 切换 / 删除透明 PNG 角色，索引 roles.json。

    v2.1：新增 on_deleted 回调（删除角色后通知台词/语言系统清理失效引用，
    保持本模块零 Qt、单向依赖——回调由调用方注入）。
    """

    MAX_BYTES = 10 * 1024 * 1024  # 10MB 上限

    def __init__(self, data_dir):
        self._dir = os.path.join(data_dir, "roles")
        self._index = os.path.join(data_dir, "roles.json")
        self._data = {"roles": [], "active": ""}
        self._deleted_cbs = []
        self._load()

    # ---------- v2.1：删除通知（轻量回调，无 Qt） ----------
    def on_deleted(self, cb):
        if cb not in self._deleted_cbs:
            self._deleted_cbs.append(cb)

    def off_deleted(self, cb):
        if cb in self._deleted_cbs:
            self._deleted_cbs.remove(cb)

    def _emit_deleted(self, role_id):
        for cb in list(self._deleted_cbs):
            try:
                cb(role_id)
            except Exception as e:
                pet_log.log_error("role deleted cb failed: %r" % (e,))  # 有意忽略：不影响其余监听者

    # ---------- 内部 ----------
    @staticmethod
    def _normalize_form(fm, fallback_name):
        """P1-7：单个形态归一化。返回 dict 或 None（无有效 png 文件）。

        结构（file 即 still 图，保留历史字段名；其余键可选）：
        {"name", "file", "front"?, "anchor", "scale"?, "offset"?,
         "animations"?, "anim_interval_ms"?, "states"?}
        """
        if not isinstance(fm, dict):
            return None
        fn = str(fm.get("file") or "")
        if not fn.lower().endswith(".png"):
            return None
        out = {
            "name": str(fm.get("name") or "").strip()[:12] or fallback_name,
            "file": fn,
        }
        # P1-7 断点#7 side/front：可选正面图，缺省沿用现状（side/front 同图）
        front = str(fm.get("front") or "")
        if front and front.lower().endswith(".png"):
            out["front"] = front
        # P1-7 形态渲染参数：anchor 常驻（默认 0.5/0.5 = 旧居中行为）；
        # scale/offset 仅在显式配置时落盘（缺省 = 现行为等价）
        out["anchor"] = _norm_anchor(fm.get("anchor"))
        sc = fm.get("scale")
        if isinstance(sc, (int, float)) and sc > 0:
            out["scale"] = float(sc)
        off = _norm_offset(fm.get("offset"))
        if off["x"] or off["y"]:
            out["offset"] = off
        # P1-7 动画按形态分组：dict[str, list[str]]；每动作截断 FRAME_MAX
        # v2.0.1：键支持内建 + 自定义命名帧动作
        anims = _norm_animations(fm.get("animations"))
        if anims:
            out["animations"] = anims
        # v2.0.1：程序化合成动作（breathe/sway/nod）
        procs = _norm_procs(fm.get("procs"))
        if procs:
            out["procs"] = procs
        # v2.0.2 断点#12：形态角色标记（睡觉/变身/不参与喂食）。
        # 仅真值落盘（严格布尔：字符串 "false"/"0" 不算真），缺省 False=现行为等价
        for _k in ("sleep_form", "transform_form", "no_feed"):
            if _flag_true(fm.get(_k)):
                out[_k] = True
        # P1-7 帧间隔：可选全局间隔（缺省沿用 IDLE_FRAME_MS/EAT_FRAME_MS）
        aiv = fm.get("anim_interval_ms")
        if isinstance(aiv, (int, float)) and aiv > 0:
            out["anim_interval_ms"] = int(aiv)
        # P1-7 可选状态图：资源图优先、程序化叠图兜底（P2-5 合并点在显示侧）
        states = _norm_states(fm.get("states"))
        if states:
            out["states"] = states
        return out

    def _normalize_role(self, r):
        """P1-7：角色记录归一化（旧 file/file_full/frames → 新 forms 结构 + 兼容字段）。

        返回 dict 或 None（非法条目：无 id / 无有效 png）。迁移规则：
        - 旧角色级 frames 升级为 forms[0].animations.idle（若 forms[0] 已有
          显式 animations.idle 则以新结构为准）；
        - 旧 forms[].file 保留为 still 字段名（file 即 still，结构统一）；
        - 顶层 file/frames 保留为兼容视图（file=forms[0].file，
          frames=forms[0].animations.idle，v13/老调用方依赖）。
        """
        if not isinstance(r, dict):
            return None
        rid = str(r.get("id") or "")
        fname = str(r.get("file") or "")
        # 过滤非法条目：无 id / 无文件名 / 非 .png（否则 delete 会误删目录）
        if not rid or not fname or not fname.lower().endswith(".png"):
            return None
        file_full = str(r.get("file_full") or "")
        # form 归一化：只有带 file_full 的 dual 才算双形态；multi 需 ≥2 形态，
        # 否则自愈回退 single（M2 修复：损坏/半截数据不留 form 与内容不一致）
        form_raw = str(r.get("form") or "")
        if form_raw in ("single", "dual", "multi"):
            form = form_raw
        else:
            form = "dual" if file_full else "single"
        raw_forms = r.get("forms")
        if form == "dual" and not file_full:
            form = "single"
        if form == "multi" and (not isinstance(raw_forms, list) or len(raw_forms) < 2):
            form = "single"
        frames = r.get("frames")
        if not isinstance(frames, list):
            frames = []
        # P3-5+：读侧上限与导入管线口径统一（上限由用户配置 role_frame_max，
        # 见模块级 FRAME_MAX，桌宠启动时同步），避免「能存读不全」
        frames = [str(x) for x in frames if str(x).lower().endswith(".png")][:FRAME_MAX]
        # forms 归一化（v1.4 多形态 + P1-7 渲染/动画/状态字段）：
        # 新结构直接采用；旧 file/file_full 自动转换
        raw_forms = r.get("forms")
        if isinstance(raw_forms, list) and raw_forms:
            forms = []
            for fm in raw_forms[:8]:
                nf = self._normalize_form(fm, "形态%d" % (len(forms) + 1))
                if nf is not None:
                    forms.append(nf)
            if not forms:
                forms = [self._normalize_form({"name": "常态", "file": fname}, "常态")]
        else:
            forms = [self._normalize_form({"name": "常态", "file": fname}, "常态")]
            if file_full:
                nf2 = self._normalize_form({"name": "吃饱", "file": file_full}, "吃饱")
                if nf2 is not None:
                    forms.append(nf2)
        # P1-7 迁移：旧角色级 frames → forms[0].animations.idle
        # （forms[0] 已有显式 animations.idle 时以新结构为准，旧字段仅兜底）
        if frames:
            anims = dict(forms[0].get("animations") or {})
            anims.setdefault("idle", frames)
            forms[0]["animations"] = anims
        # 兼容视图：顶层 frames = forms[0].animations.idle（v13/旧调用方依赖）
        idle_view = list((forms[0].get("animations") or {}).get("idle") or [])
        # P1-7：v2 标记——任一形态带新渲染参数（front/scale/offset/states/
        # anim_interval_ms/非默认 anchor/非 idle 动画动作）即为新结构角色；
        # 桌宠据此区分「旧角色全局 scale 补偿」与「新角色 anchor/scale/offset 装配」。
        # 注意：仅 idle 动画不算 v2（旧角色级 frames 迁移也落 idle，需保持旧补偿路径）
        v2 = any(
            ("front" in fm) or ("scale" in fm) or ("offset" in fm)
            or ("states" in fm) or ("anim_interval_ms" in fm)
            or (fm.get("anchor") != DEFAULT_ANCHOR)
            or (set(fm.get("animations") or {}) - {"idle"})
            for fm in forms
        )
        return {
            "id": rid,
            "name": str(r.get("name") or "") or "未命名",
            "file": forms[0]["file"],
            "form": form,
            "file_full": (forms[1]["file"] if len(forms) >= 2 else ""),
            "forms": forms,
            "frames": idle_view,
            "added": str(r.get("added") or ""),
            "v2": bool(v2),
        }

    def _load(self):
        """读索引并归一化；active 指向已不存在的角色时重置为默认。"""
        data = _read_json(self._index)
        roles = data.get("roles") if isinstance(data.get("roles"), list) else []
        clean = []
        for r in roles:
            nr = self._normalize_role(r)
            if nr is not None:
                clean.append(nr)
        active = str(data.get("active") or "")
        if active and not any(r["id"] == active for r in clean):
            active = ""
        self._data = {"roles": clean, "active": active}
        if active != str(data.get("active") or ""):
            _write_json(self._index, self._data)  # 修复损坏的 active 引用（失败静默）

    def _save(self):
        """原子落盘；返回错误字符串或 None。"""
        return _write_json(self._index, self._data)

    def _path(self, role):
        """角色 dict -> 文件绝对路径（file 为纯文件名时拼到 roles/ 目录下）。"""
        p = role.get("file") or ""
        if not os.path.isabs(p):
            p = os.path.join(self._dir, p)
        return p

    def _role_paths(self, role):
        """角色全部素材文件绝对路径（base + 各形态 side/front + 动画帧 +
        状态资源图，去重；P1-7 起覆盖新结构引用的全部文件）。"""
        seen = set()
        names = [role.get("file"), role.get("file_full")]
        for fm in role.get("forms") or []:
            names.append(fm.get("file"))
            names.append(fm.get("front"))
            # v2.0.1：遍历全部动画动作键（内建 + 自定义命名帧动作），
            # 保证自定义动作帧也参与删除/换图清理（漏收会导致孤儿文件残留）
            for act in (fm.get("animations") or {}):
                names.extend((fm.get("animations") or {}).get(act, []) or [])
            names.extend((fm.get("states") or {}).values())
        out = []
        for f in names:
            if not f:
                continue
            p = f if os.path.isabs(f) else os.path.join(self._dir, f)
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                out.append(p)
        return out

    @staticmethod
    def _cleanup_files(*paths):
        """尽力删除半成品文件（导入回滚用），任何异常静默。"""
        for p in paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass  # 有意忽略：半成品文件清理尽力而为（导入回滚用）

    # ---------- 对外 ----------
    def list_roles(self):
        """返回全部自定义角色
        [{"id","name","file","form","file_full","frames","added"}...]；
        默认角色不在列表。"""
        return [dict(r) for r in self._data["roles"]]

    def active_id(self):
        """当前角色 id；"" = 默认角色。"""
        return str(self._data.get("active") or "")

    def set_active(self, role_id):
        """切换角色；role_id="" 回默认。角色不存在返回 False。"""
        role_id = str(role_id or "")
        if role_id and self.get(role_id) is None:
            return False
        self._data["active"] = role_id
        return self._save() is None

    def active_path(self):
        """当前角色 png 绝对路径；默认角色或文件缺失返回 None。"""
        rid = self.active_id()
        if not rid:
            return None
        return self.path_for(rid)

    def path_for(self, role_id):
        """任意角色 png 绝对路径（存在才返回）；供面板预览使用。"""
        r = self.get(str(role_id or ""))
        if r is None:
            return None
        p = self._path(r)
        try:
            return p if os.path.isfile(p) else None
        except Exception:
            return None  # 有意忽略：isfile 异常按文件不存在处理

    def path_for_full(self, role_id):
        """角色第二形态 png 绝对路径（存在才返回）；单形态返回 None。

        v1.4 多形态下等价于 forms[1]；旧 file_full 记录由 _load 转进 forms。
        """
        metas = self.form_metas(role_id)
        if len(metas) >= 2:
            f = metas[1].get("file") or ""
            if not os.path.isabs(f):
                f = os.path.join(self._dir, f)
            try:
                return f if os.path.isfile(f) else None
            except Exception:
                return None  # 有意忽略：isfile 异常按文件不存在处理
        return None

    def form_metas(self, role_id):
        """角色的形态列表 [{"name","file"}...]（v1.4 多形态）；旧角色由 _load 自动转换。"""
        r = self.get(str(role_id or ""))
        if r is None:
            return []
        return [dict(f) for f in r.get("forms") or []]

    def form_files(self, role_id):
        """各形态素材绝对路径（存在才保留）；全部缺失返回 []。"""
        return [p for p in self.form_paths(role_id) if p]

    def form_paths(self, role_id):
        """各形态素材绝对路径（与 form_metas 逐项对齐；缺失为 None）。

        主程序据此装配 sprites，保证 form_keys 与 sprites 键集一致（M2）。"""
        metas = self.form_metas(role_id)
        out = []
        for m in metas:
            p = m.get("file") or ""
            if not os.path.isabs(p):
                p = os.path.join(self._dir, p)
            try:
                out.append(p if os.path.isfile(p) else None)
            except Exception:
                out.append(None)
        return out

    def frames_for(self, role_id):
        """角色动画帧 png 绝对路径列表（都存在才返回）；无帧动画返回 []。

        P1-7：等价 forms[0].animations.idle（旧接口保留，兼容 v13/老调用方）。
        """
        anims = self.form_animations(role_id)
        if not anims:
            return []
        return list(anims[0].get("idle") or [])

    def form_animations(self, role_id):
        """P1-7：逐形态动画帧绝对路径（与 form_metas 逐项对齐）。

        返回 [{"idle": [paths], "eat": [...], "poke": [...], "sleep": [...],
               "interval_ms": int|None}, ...]；
        无动画的形态给空 dict；某动作帧文件缺失时该动作整体视为无动画
        （回退静态，与旧 frames_for 语义一致）。角色不存在返回 []。
        """
        r = self.get(str(role_id or ""))
        if r is None:
            return []
        out = []
        for fm in r.get("forms") or []:
            item = {}
            # v2.0.1：遍历全部动作键（内建 + 自定义命名帧动作）；
            # "interval_ms" 是帧间隔合并键（下方写入 int），跳过动作同名键
            # 防帧路径 list 冒充间隔（_play_idle setInterval(int(list)) TypeError）
            for act in (fm.get("animations") or {}):
                if act == "interval_ms":
                    continue
                paths = []
                ok = True
                for fn in (fm.get("animations") or {}).get(act, []) or []:
                    p = fn if os.path.isabs(fn) else os.path.join(self._dir, fn)
                    try:
                        if os.path.isfile(p):
                            paths.append(p)
                        else:
                            ok = False
                            break  # 帧文件缺失：该动作整体视为无动画（回退静态）
                    except Exception:
                        ok = False
                        break
                if paths and ok:
                    item[act] = paths
            aiv = fm.get("anim_interval_ms")
            if isinstance(aiv, (int, float)) and aiv > 0:
                item["interval_ms"] = int(aiv)
            out.append(item)
        return out

    def custom_actions(self, role_id, form_idx=0):
        """v2.0.1：该形态的命名动作清单 [(name, kind)]，kind = frames/proc。

        含自定义帧动作（animations 中非内建键）与程序化动作（procs）；不含内建动作。"""
        r = self.get(str(role_id or ""))
        if r is None:
            return []
        forms = r.get("forms") or []
        if not (0 <= form_idx < len(forms)):
            return []
        fm = forms[form_idx]
        out = []
        for act in (fm.get("animations") or {}):
            if act not in ANIM_ACTIONS:
                out.append((act, "frames"))
        for name in sorted(fm.get("procs") or {}):
            out.append((name, "proc"))
        return out

    def procs(self, role_id, form_idx=0):
        """v2.0.1：该形态的程序化动作 {名字: {kind, amp, period_ms}}（已归一化）。"""
        r = self.get(str(role_id or ""))
        if r is None:
            return {}
        forms = r.get("forms") or []
        if not (0 <= form_idx < len(forms)):
            return {}
        return dict(forms[form_idx].get("procs") or {})

    def form_role_flags(self, role_id):
        """v2.0.2 断点#12：逐形态角色标记 [{sleep_form, transform_form, no_feed}]
        （与 form_metas/form_keys 逐项对齐，缺省全部 False）；角色不存在返回 []。

        严格布尔口径 _flag_true（"false"/"0" 字符串不算真）——读侧兜底：
        经 _data 直接注入的角色（导入/测试路径）可能未经 _load 归一化。"""
        r = self.get(str(role_id or ""))
        if r is None:
            return []
        out = []
        for fm in r.get("forms") or []:
            out.append({
                "sleep_form": _flag_true(fm.get("sleep_form")),
                "transform_form": _flag_true(fm.get("transform_form")),
                "no_feed": _flag_true(fm.get("no_feed")),
            })
        return out

    def form_state_paths(self, role_id):
        """P1-7：逐形态状态资源图绝对路径（与 form_metas 逐项对齐）。

        返回 [{state: path}...]；未配置/文件缺失的状态不出现（显示侧走
        程序化叠图兜底，P2-5 资源图优先）。角色不存在返回 []。
        """
        r = self.get(str(role_id or ""))
        if r is None:
            return []
        out = []
        for fm in r.get("forms") or []:
            item = {}
            for st, fn in (fm.get("states") or {}).items():
                p = fn if os.path.isabs(fn) else os.path.join(self._dir, fn)
                try:
                    if os.path.isfile(p):
                        item[st] = p
                except Exception:
                    pass  # 有意忽略：isfile 异常按文件缺失处理（走叠图兜底）
            out.append(item)
        return out

    def form_front_paths(self, role_id):
        """P1-7 断点#7：逐形态 front 图绝对路径（与 form_metas 逐项对齐）。

        未配置 front 或文件缺失 → 回退该形态 side 路径（缺省 side/front 同图）；
        side 也缺失 → None。角色不存在返回 []。
        """
        metas = self.form_metas(role_id)
        out = []
        for m in metas:
            fp = m.get("front") or ""
            if fp:
                p = fp if os.path.isabs(fp) else os.path.join(self._dir, fp)
                try:
                    if os.path.isfile(p):
                        out.append(p)
                        continue
                except Exception:
                    pass  # 有意忽略：isfile 异常按缺失处理（回退 side）
            side = m.get("file") or ""
            sp = side if os.path.isabs(side) else os.path.join(self._dir, side)
            try:
                out.append(sp if os.path.isfile(sp) else None)
            except Exception:
                out.append(None)
        return out

    def resolve(self, fname):
        """P1-7 编辑辅助：把索引里的相对文件名解析为绝对路径（不检查存在性）。"""
        if not fname:
            return ""
        return fname if os.path.isabs(fname) else os.path.join(self._dir, fname)

    def stage_file(self, src):
        """P1-7 编辑辅助：把处理好的素材复制进 roles/ 目录（不落索引）。

        返回新文件名（<uuid8>_e<时间戳>.png）或 None（失败）。调用方负责：
        更新索引成功后保留、失败时删除（避免孤儿文件）。
        """
        try:
            if not isinstance(src, str) or not os.path.isfile(src):
                return None
            os.makedirs(self._dir, exist_ok=True)
            fn = "%s_e%s.png" % (uuid.uuid4().hex[:8], str(int(time.time())))
            shutil.copyfile(src, os.path.join(self._dir, fn))
            return fn
        except Exception:
            return None

    def is_v2(self, role_id):
        """P1-7：角色是否含新结构渲染/动画参数（front/scale/offset/anchor 非默认/
        animations/states/anim_interval_ms）。桌宠据此区分旧角色全局 scale
        补偿路径与新角色 anchor/scale/offset 装配路径。"""
        r = self.get(str(role_id or ""))
        return bool(r and r.get("v2"))

    def import_file(self, src, name=None):
        """旧版导入（v1.3.0 兼容）：只复制一张图，无「吃饱」变体（单形态）。

        面板入口已改用 import_processed（支持单/双形态 + 自动处理素材）。
        成功返回 (role, None)，失败 (None, err)。
        本库保持 Qt-free，只校验扩展名与大小；PNG 可加载性由调用方用 QPixmap 把关。"""
        try:
            if not src or not isinstance(src, str) or not os.path.isfile(src):
                return None, "文件不存在"
            if os.path.splitext(src)[1].lower() != ".png":
                return None, "仅支持 .png 角色图"
            try:
                if os.path.getsize(src) > self.MAX_BYTES:
                    return None, "文件超过 10MB，无法导入"
            except Exception:
                return None, "无法读取文件大小"
            _ok_png, _err_png = _probe_png(src)
            if not _ok_png:
                return None, _err_png  # D1：旧版入口也校验 PNG 内容，坏图不入库
            if name is None or not str(name).strip():
                name = os.path.splitext(os.path.basename(src))[0]
            name = str(name).strip()[:40] or "未命名"
            try:
                os.makedirs(self._dir, exist_ok=True)
            except Exception as e:
                return None, "无法创建角色目录：%s" % e
            rid = _new_id()
            dst = os.path.join(self._dir, rid + ".png")
            try:
                shutil.copyfile(src, dst)
            except Exception:
                try:
                    if os.path.exists(dst):
                        os.remove(dst)  # 半截文件清理，不留孤儿
                except Exception:
                    pass  # 有意忽略：半截文件清理尽力而为，不留孤儿
                return None, "复制文件失败"
            # P1-7：旧版入口也走统一归一化（forms 结构补齐，行为不变）
            role = self._normalize_role({
                "id": rid,
                "name": name,
                "file": rid + ".png",
                "form": "single",
                "added": time.strftime("%Y-%m-%d"),
            })
            if role is None:
                return None, "角色数据无效"
            self._data["roles"].append(role)
            err = self._save()
            if err:
                # 索引写失败：回滚复制，避免孤儿文件
                try:
                    os.remove(dst)
                except Exception:
                    pass  # 有意忽略：回滚清理尽力而为
                self._data["roles"].pop()
                return None, err
            return role, None
        except Exception as e:
            return None, "导入失败：%s" % e

    def import_processed(self, base_src, full_src=None, name=None, frames_src=None, forms_src=None,
                         interval_ms=None, render=None, states=None,
                         keep_source=False, source_files=None):
        """导入已自动处理的角色素材（面板新入口；旧调用不传新参数仍工作）。

        full_src 给路径 → 双形态（旧参数，等价 forms_src 两个形态）。
        frames_src 给 2~FRAME_MAX 张已处理帧 → 帧动画角色：帧存为 <id>_f%02d.png，
        base 必须是首帧（"file" 指向 _f00）；P1-7 起帧写入
        forms[0].animations.idle，"frames" 保留为兼容视图。
        forms_src 给 [(名字, png路径), ...]（1~8 个，v1.4 多形态）→
        形态文件存为 <id>_form%d.png，形态 0 即 base；记录 "forms"。
        P1-7 新参数（全部可选，缺省 = 现行为）：
        - interval_ms：帧间隔 ms（写入各形态 anim_interval_ms；缺省走
          IDLE_FRAME_MS/EAT_FRAME_MS）
        - render：渲染参数。单 dict（所有形态同参）或与 forms 对齐的 list：
          {"anchor": {"x","y"}, "scale": 倍率, "offset": {"x","y"}}（键均可缺省）
        - states：状态资源图 {state: png路径}（写入 forms[0].states）
        - keep_source：P2-6 原图保留开关（默认 False）；True 时把 source_files
          里的原图复制到 roles/<id>/source/（保留失败不影响导入）
        - source_files：原图路径列表（配合 keep_source）
        成功返回 (role, None)，失败 (None, err)；任何失败都会清理半成品文件。
        """
        try:
            for label, src in (("常态", base_src), ("吃饱", full_src)):
                if src is None:
                    continue
                if not isinstance(src, str) or not os.path.isfile(src):
                    return None, "%s素材文件不存在" % label
                if os.path.splitext(src)[1].lower() != ".png":
                    return None, "%s素材必须是 png" % label
                try:
                    if os.path.getsize(src) > self.MAX_BYTES:
                        return None, "%s素材超过 10MB" % label
                except Exception:
                    return None, "无法读取文件大小"
            if frames_src is not None:
                if not isinstance(frames_src, list) or len(frames_src) < 2:
                    return None, "帧动画至少需要 2 帧"
                if len(frames_src) > FRAME_MAX:
                    return None, "帧动画最多 %d 帧（可在设置里调整）" % FRAME_MAX
                for i, src in enumerate(frames_src):
                    if not isinstance(src, str) or not os.path.isfile(src):
                        return None, "第 %d 帧素材不存在" % (i + 1)
                    if os.path.splitext(src)[1].lower() != ".png":
                        return None, "第 %d 帧素材必须是 png" % (i + 1)
                    try:
                        if os.path.getsize(src) > self.MAX_BYTES:
                            return None, "第 %d 帧素材超过 10MB" % (i + 1)
                    except Exception:
                        return None, "无法读取文件大小"
            if forms_src is not None:
                if not isinstance(forms_src, list) or not (1 <= len(forms_src) <= 8):
                    return None, "形态数量必须在 1~8 之间"
                for i, fm in enumerate(forms_src):
                    if not isinstance(fm, (list, tuple)) or len(fm) != 2:
                        return None, "第 %d 个形态格式错误" % (i + 1)
                    src = fm[1]
                    if not isinstance(src, str) or not os.path.isfile(src):
                        return None, "第 %d 个形态素材不存在" % (i + 1)
                    if os.path.splitext(src)[1].lower() != ".png":
                        return None, "第 %d 个形态素材必须是 png" % (i + 1)
                    try:
                        if os.path.getsize(src) > self.MAX_BYTES:
                            return None, "第 %d 个形态素材超过 10MB" % (i + 1)
                    except Exception:
                        return None, "无法读取文件大小"
            if name is None or not str(name).strip():
                name = "未命名"  # base_src 是临时文件，不能用其文件名当角色名
            name = str(name).strip()[:40] or "未命名"
            try:
                os.makedirs(self._dir, exist_ok=True)
            except Exception as e:
                return None, "无法创建角色目录：%s" % e
            rid = _new_id()
            dst_base = os.path.join(self._dir, rid + ".png")
            dst_full = os.path.join(self._dir, rid + "_full.png") if full_src else None
            dst_frames = []
            dst_forms = []
            try:
                if frames_src:
                    for i, src in enumerate(frames_src):
                        dst_frames.append(os.path.join(self._dir, "%s_f%02d.png" % (rid, i)))
                        shutil.copyfile(src, dst_frames[-1])
                    # 帧动画角色：base 即首帧（复制首帧到 <id>.png，保持静态预览/回退一致）
                    shutil.copyfile(frames_src[0], dst_base)
                else:
                    shutil.copyfile(base_src, dst_base)
                if dst_full is not None:
                    shutil.copyfile(full_src, dst_full)
                if forms_src is not None:
                    for i, (fm_name, fm_src) in enumerate(forms_src):
                        if i == 0:
                            dst_forms.append(dst_base)  # 形态 0 即 base
                        else:
                            d = os.path.join(self._dir, "%s_form%d.png" % (rid, i))
                            shutil.copyfile(fm_src, d)
                            dst_forms.append(d)
            except Exception:
                self._cleanup_files(dst_base, dst_full, *dst_frames, *dst_forms)
                return None, "复制文件失败"
            # ---- P1-7 新参数校验（缺省 = 现行为）----
            n_forms_total = (len(forms_src) if forms_src is not None
                             else (2 if full_src else 1))
            render_specs = None
            if render is not None:
                if isinstance(render, dict):
                    render_specs = [render] * n_forms_total  # 单 dict：所有形态同参
                elif isinstance(render, list) and len(render) == n_forms_total:
                    render_specs = [x if isinstance(x, dict) else {} for x in render]
                else:
                    self._cleanup_files(dst_base, dst_full, *dst_frames, *dst_forms)
                    return None, "渲染参数格式错误"
                for spec in render_specs:
                    anchor = spec.get("anchor")
                    if anchor is not None and not isinstance(anchor, dict):
                        self._cleanup_files(dst_base, dst_full, *dst_frames, *dst_forms)
                        return None, "anchor 必须是 {x,y}"
            if states is not None:
                if not isinstance(states, dict):
                    self._cleanup_files(dst_base, dst_full, *dst_frames, *dst_forms)
                    return None, "状态图必须是 {状态: png路径}"
                _norm_st = _norm_states(states)
                if _norm_st != states or not all(
                        isinstance(v, str) and os.path.isfile(v) for v in states.values()):
                    self._cleanup_files(dst_base, dst_full, *dst_frames, *dst_forms)
                    return None, "状态图参数无效"
                # 状态图按额外素材复制：<id>_st_<state>.png（原图路径由调用方保证有效）
                dst_states = {}
                for st, sp in states.items():
                    dst_states[st] = "%s_st_%s.png" % (rid, st)
            if interval_ms is not None:
                try:
                    interval_ms = int(interval_ms)
                except (TypeError, ValueError):
                    interval_ms = None
                if interval_ms is None or not (10 <= interval_ms <= 10000):
                    self._cleanup_files(dst_base, dst_full, *dst_frames, *dst_forms)
                    return None, "帧间隔必须是 10~10000 之间的整数 ms"
            # ---- 复制状态资源图（失败回滚整个导入）----
            if states:
                try:
                    for st, sp in states.items():
                        shutil.copyfile(sp, os.path.join(self._dir, dst_states[st]))
                except Exception:
                    self._cleanup_files(dst_base, dst_full, *dst_frames, *dst_forms,
                                        *[os.path.join(self._dir, x) for x in dst_states.values()])
                    return None, "复制状态图失败"
            role = {
                "id": rid,
                "name": name,
                "file": rid + ".png",
                "form": ("multi" if (forms_src is not None and len(forms_src) >= 2)
                         else ("dual" if full_src else "single")),
                "added": time.strftime("%Y-%m-%d"),
            }
            if full_src:
                role["file_full"] = rid + "_full.png"
            if frames_src:
                role["frames"] = ["%s_f%02d.png" % (rid, i) for i in range(len(frames_src))]
            if forms_src is not None:
                role["forms"] = [
                    {"name": (fm[0].strip()[:12] if isinstance(fm[0], str) else "")
                             or "形态%d" % (i + 1),
                     "file": os.path.basename(dst_forms[i])}
                    for i, fm in enumerate(forms_src)
                ]
            else:
                # 旧参数路径（full_src）也落 forms，避免重启前后结构不一致
                role["forms"] = [{"name": "常态", "file": rid + ".png"}]
                if full_src:
                    role["forms"].append({"name": "吃饱", "file": rid + "_full.png"})
            # P1-7：高级选项写入 forms（渲染参数/帧间隔/状态图）
            if render_specs:
                for fm, spec in zip(role["forms"], render_specs):
                    if spec.get("anchor") is not None:
                        fm["anchor"] = _norm_anchor(spec.get("anchor"))
                    if spec.get("scale") is not None:
                        fm["scale"] = spec.get("scale")
                    if spec.get("offset") is not None:
                        fm["offset"] = spec.get("offset")
            if interval_ms is not None:
                for fm in role["forms"]:
                    fm["anim_interval_ms"] = interval_ms
            if states:
                role["forms"][0]["states"] = dst_states
            # 统一归一化（frames→animations、anchor 默认、v2 标记、兼容视图）
            role = self._normalize_role(role)
            if role is None:
                self._cleanup_files(dst_base, dst_full, *dst_frames, *dst_forms,
                                    *[os.path.join(self._dir, x) for x in dst_states.values()])
                return None, "角色数据无效"
            # P2-6：保留原图到 roles/<id>/source/（可选，默认关；失败不影响导入）
            if keep_source and source_files:
                try:
                    sdir = os.path.join(self._dir, rid, "source")
                    os.makedirs(sdir, exist_ok=True)
                    for sf in source_files:
                        if not (isinstance(sf, str) and os.path.isfile(sf)):
                            continue
                        base = os.path.basename(sf)
                        target = os.path.join(sdir, base)
                        j = 1
                        stem, ext = os.path.splitext(base)
                        while os.path.exists(target):
                            target = os.path.join(sdir, "%s_%d%s" % (stem, j, ext))
                            j += 1
                        shutil.copyfile(sf, target)
                except Exception:
                    pass  # 有意忽略：原图保留失败不影响导入（体积优化开关，尽力而为）
            self._data["roles"].append(role)
            err = self._save()
            if err:
                self._cleanup_files(dst_base, dst_full, *dst_frames, *dst_forms,
                                    *[os.path.join(self._dir, x) for x in dst_states.values()])
                self._data["roles"].pop()
                return None, err
            return role, None
        except Exception as e:
            return None, "导入失败：%s" % e

    def delete(self, role_id):
        """删除角色（文件 + 索引项）；若为当前角色则重置为默认。返回 (bool, err)。

        边界：素材文件被占用时可能删第一张成功、第二张失败——此时索引未动，
        该角色仍在列表里但部分文件已消失（预览会提示文件缺失，重试删除即可）。"""
        role_id = str(role_id or "")
        r = self.get(role_id)
        if r is None:
            return False, "角色不存在"
        try:
            for p in self._role_paths(r):
                if os.path.exists(p):
                    os.remove(p)
            # P2-6：保留的原图目录（roles/<id>/source/）一并清理，不留孤儿
            src_dir = os.path.join(self._dir, role_id, "source")
            if os.path.isdir(src_dir):
                shutil.rmtree(src_dir, ignore_errors=True)
        except Exception as e:
            return False, "删除文件失败：%s" % e
        self._data["roles"] = [x for x in self._data["roles"] if x["id"] != role_id]
        if self._data["active"] == role_id:
            self._data["active"] = ""
        err = self._save()
        if err:
            return False, err
        self._emit_deleted(role_id)  # v2.1：通知外部清理失效引用（台词/绑定）
        return True, ""

    def get(self, role_id):
        """按 id 取角色 dict（副本）；不存在返回 None。"""
        role_id = str(role_id or "")
        for r in self._data["roles"]:
            if r["id"] == role_id:
                return dict(r)
        return None

    def update(self, role_id, patch):
        """P1-7：就地编辑角色（id 不变）。返回 (bool, err)。

        patch 键（全部可选，只改给出的；未知键忽略）：
        - name: str 新名字（截断 40，空拒绝）
        - forms: list[dict] 完整形态列表（1~8 个）整体替换——改名/换图/调序/
          改渲染参数/改动画/改状态图；每项结构同 _normalize_form
        - file / file_full: 旧字段快捷改法（写回 forms[0].file / forms[1].file）
        - frames: list[str] 帧文件名（写回 forms[0].animations.idle；旧兼容；
          超 FRAME_MAX 拒绝）
        update 只改索引不搬文件：调用方负责新文件就位（编辑对话框换图时
        写入新文件再 patch），成功落盘后由调用方清理不再被引用的旧文件。
        """
        role_id = str(role_id or "")
        r = self.get(role_id)
        if r is None:
            return False, "角色不存在"
        if not isinstance(patch, dict):
            return False, "patch 必须是 dict"
        new_r = dict(r)
        if "name" in patch:
            nm = str(patch.get("name") or "").strip()
            if not nm:
                return False, "名字不能为空"
            new_r["name"] = nm[:40]
        if "forms" in patch:
            raw_forms = patch["forms"]
            if not isinstance(raw_forms, list) or not (1 <= len(raw_forms) <= 8):
                return False, "形态数量必须在 1~8 之间"
            forms = []
            for i, fm in enumerate(raw_forms):
                if not isinstance(fm, dict):
                    return False, "第 %d 个形态格式错误" % (i + 1)
                nf = self._normalize_form(fm, "形态%d" % (len(forms) + 1))
                if nf is None:
                    return False, "第 %d 个形态缺少有效的 png 文件" % (i + 1)
                forms.append(nf)
            new_r["forms"] = forms
            new_r["file"] = forms[0]["file"]
            new_r["file_full"] = forms[1]["file"] if len(forms) >= 2 else ""
            new_r["frames"] = []  # forms 替换为权威结构：旧兼容视图由归一化重建
        else:
            forms = [dict(f) for f in (new_r.get("forms") or [])]
            if "file" in patch:
                fv = str(patch.get("file") or "")
                if not fv.lower().endswith(".png"):
                    return False, "文件必须是 png"
                if not forms:
                    return False, "角色形态数据缺失"
                forms[0]["file"] = fv
                new_r["file"] = fv
            if "file_full" in patch and forms:
                fv2 = str(patch.get("file_full") or "")
                if fv2 and not fv2.lower().endswith(".png"):
                    return False, "文件必须是 png"
                if len(forms) >= 2:
                    forms[1]["file"] = fv2
                    new_r["file_full"] = fv2
            if "file" in patch or "file_full" in patch:
                new_r["forms"] = forms
        if "frames" in patch:
            fr = patch.get("frames")
            if not isinstance(fr, list):
                return False, "frames 必须是列表"
            frs = [str(x) for x in fr if str(x).lower().endswith(".png")]
            if len(frs) != len(fr):
                return False, "帧文件名必须是 png"
            if len(frs) > FRAME_MAX:
                return False, "帧动画最多 %d 帧（可在设置里调整）" % FRAME_MAX
            forms = [dict(f) for f in (new_r.get("forms") or [])]
            if not forms:
                return False, "角色形态数据缺失"
            anims = dict(forms[0].get("animations") or {})
            anims["idle"] = frs
            forms[0]["animations"] = anims
            new_r["forms"] = forms
        # 统一归一化（兼容视图 frames/file 同步、v2 标记刷新）
        new_r = self._normalize_role(new_r)
        if new_r is None:
            return False, "角色数据无效"
        for i, x in enumerate(self._data["roles"]):
            if x["id"] == role_id:
                self._data["roles"][i] = new_r
                break
        err = self._save()
        if err:
            return False, err
        return True, ""


# ---------------- 音频库 ----------------
# 自定义音效组支持的 5 个事件槽位
SLOT_KINDS = ("press", "release", "feed", "reply", "coin")
_AUDIO_EXTS = (".wav", ".mp3")


class AudioLibrary:
    """自定义音频片段与音效组管理：导入 / 重命名 / 删除 / 槽位映射，索引 audio.json。"""

    MAX_BYTES = 20 * 1024 * 1024  # 20MB 上限

    def __init__(self, data_dir):
        self._dir = os.path.join(data_dir, "audio")
        self._index = os.path.join(data_dir, "audio.json")
        self._data = {
            "fragments": [],
            "group": {"custom": {k: None for k in SLOT_KINDS}},
        }
        self._load()

    # ---------- 内部 ----------
    def _load(self):
        """读索引并归一化：片段字段补齐、槽位三态（fid/""/None）校验。"""
        data = _read_json(self._index)
        frags = data.get("fragments") if isinstance(data.get("fragments"), list) else []
        clean = []
        for f in frags:
            if not isinstance(f, dict):
                continue
            fid = str(f.get("id") or "")
            if not fid:
                continue
            ext = str(f.get("ext") or "").lower()
            if ext and not ext.startswith("."):
                ext = "." + ext
            if ext not in _AUDIO_EXTS:
                continue  # 非法扩展名的残留项直接丢弃
            clean.append({
                "id": fid,
                "name": str(f.get("name") or "") or "未命名",
                "file": str(f.get("file") or ""),
                "ext": ext,
                "added": str(f.get("added") or ""),
                "duration": f.get("duration") if isinstance(f.get("duration"), (int, float)) else None,
            })
        group = data.get("group") if isinstance(data.get("group"), dict) else {}
        custom = group.get("custom") if isinstance(group.get("custom"), dict) else {}
        slots = {}
        for k in SLOT_KINDS:
            v = custom.get(k)
            if v is None or v == "" or isinstance(v, str):
                slots[k] = v
            else:
                slots[k] = None
        self._data = {"fragments": clean, "group": {"custom": slots}}

    def _save(self):
        """原子落盘；返回错误字符串或 None。"""
        return _write_json(self._index, self._data)

    def _get(self, fid):
        fid = str(fid or "")
        for f in self._data["fragments"]:
            if f["id"] == fid:
                return f
        return None

    # ---------- 对外 ----------
    def fragments(self):
        """全部片段 [{"id","name","file","ext","added","duration"}...]。"""
        return [dict(f) for f in self._data["fragments"]]

    def fragment_path(self, fid):
        """片段绝对路径；片段不存在或文件缺失返回 None。"""
        f = self._get(fid)
        if f is None:
            return None
        p = f.get("file") or ""
        if not os.path.isabs(p):
            p = os.path.join(self._dir, p)
        try:
            return p if os.path.isfile(p) else None
        except Exception:
            return None  # 有意忽略：isfile 异常按文件不存在处理

    def import_file(self, src, name=None):
        """导入音频：复制到 audio/<id>.<ext>。仅 .wav/.mp3、>20MB 拒绝，不校验音频内容。"""
        try:
            if not src or not isinstance(src, str) or not os.path.isfile(src):
                return None, "文件不存在"
            ext = os.path.splitext(src)[1].lower()
            if ext not in _AUDIO_EXTS:
                return None, "仅支持 .wav / .mp3 音频"
            try:
                if os.path.getsize(src) > self.MAX_BYTES:
                    return None, "文件超过 20MB，无法导入"
            except Exception:
                return None, "无法读取文件大小"
            # D2：内容校验——损坏音频不入库（wav 走 wave 头校验；mp3 查 ID3/帧同步）
            if ext == ".wav":
                if _wav_duration(src) is None and _probe_wav_ok(src) is False:
                    return None, "WAV 文件损坏或不是 PCM 格式"
            else:
                with open(src, "rb") as f:
                    head = f.read(10)
                if not (head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)):
                    return None, "MP3 文件损坏"
            if name is None or not str(name).strip():
                name = os.path.splitext(os.path.basename(src))[0]
            name = str(name).strip()[:40] or "未命名"
            try:
                os.makedirs(self._dir, exist_ok=True)
            except Exception as e:
                return None, "无法创建音频目录：%s" % e
            fid = _new_id()
            dst = os.path.join(self._dir, fid + ext)
            try:
                shutil.copyfile(src, dst)
            except Exception:
                try:
                    if os.path.exists(dst):
                        os.remove(dst)  # 半截文件清理，不留孤儿
                except Exception:
                    pass  # 有意忽略：半截文件清理尽力而为，不留孤儿
                return None, "复制文件失败"
            duration = _wav_duration(dst) if ext == ".wav" else None
            frag = {
                "id": fid,
                "name": name,
                "file": fid + ext,
                "ext": ext,
                "added": time.strftime("%Y-%m-%d"),
                "duration": duration,
            }
            self._data["fragments"].append(frag)
            err = self._save()
            if err:
                try:
                    os.remove(dst)
                except Exception:
                    pass  # 有意忽略：回滚清理尽力而为
                self._data["fragments"].pop()
                return None, err
            return frag, None
        except Exception as e:
            return None, "导入失败：%s" % e

    def delete(self, fid):
        """删除片段（文件 + 索引项）；被音效组槽位引用的槽位同步置 ""（静音）。"""
        f = self._get(fid)
        if f is None:
            return False, "音频片段不存在"
        try:
            p = f.get("file") or ""
            if not os.path.isabs(p):
                p = os.path.join(self._dir, p)
            if os.path.exists(p):
                os.remove(p)
        except Exception as e:
            return False, "删除文件失败：%s" % e
        self._data["fragments"] = [x for x in self._data["fragments"] if x["id"] != fid]
        for k, v in self._data["group"]["custom"].items():
            if v == fid:
                self._data["group"]["custom"][k] = ""
        err = self._save()
        if err:
            return False, err
        return True, ""

    def rename(self, fid, new_name):
        """重命名片段；空名字返回错误。返回 (bool, err)。"""
        f = self._get(fid)
        if f is None:
            return False, "音频片段不存在"
        name = str(new_name or "").strip()
        if not name:
            return False, "名字不能为空"
        f["name"] = name[:40]
        err = self._save()
        if err:
            return False, err
        return True, ""

    def group_slots(self):
        """音效组槽位原始值：{"custom": {kind: fid|""|None}}（副本，改它不影响内部）。"""
        return {"custom": dict(self._data["group"].get("custom", {}))}

    def set_slot(self, kind, fid):
        """设置槽位：fid=片段 id；""=静音；None=恢复默认。kind 非法返回 False。

        事件播放走 winsound 仅支持 wav：非 wav 片段拒绝入槽位（可试听但不可绑定）。
        """
        if kind not in SLOT_KINDS:
            return False
        if fid is None:
            val = None
        elif fid == "":
            val = ""
        else:
            fid = str(fid)
            f = self._get(fid)
            if f is None:
                return False
            if str(f.get("ext", "")).lower() != ".wav":
                return False  # 槽位仅支持 wav
            val = fid
        self._data["group"]["custom"][kind] = val
        return self._save() is None

    def group_paths(self):
        """解析槽位为可播放路径：{"press": path|""|None, ...}。

        None = 未设置（走内置默认音效）；"" = 静音；path = 片段绝对路径
        （文件缺失返回 None，等价于走默认）。
        """
        out = {}
        slots = self._data["group"].get("custom", {})
        for k in SLOT_KINDS:
            v = slots.get(k)
            if v is None or v == "":
                out[k] = v
            else:
                out[k] = self.fragment_path(v)
        return out


# ---------------- v2.1：声音素材库（参考音，与音效片段彻底分开） ----------------
# 参考音用于声音克隆后端（GPT-SoVITS / F5-TTS / CosyVoice / 商业 API）：
# 与「音效片段」语义不同（音效是播出来听的，参考音是喂给模型学音色的），
# 因此独立目录 data/voice_ref/ 与独立索引 voice_assets.json，互不混用。
class VoiceAssetLibrary:
    """声音素材（参考音）库：导入 / 重命名 / 删除 / 试听路径 / 删除通知。

    只负责存储与元数据，不做 TTS / 绑定 / 合成（那是语言系统 pet_voice 的职责）。
    """

    MAX_BYTES = 20 * 1024 * 1024  # 20MB 上限（克隆参考音通常 3~10 秒，远小于此）
    _EXTS = (".wav", ".mp3")

    def __init__(self, data_dir):
        self._dir = os.path.join(data_dir, "voice_ref")
        self._index = os.path.join(data_dir, "voice_assets.json")
        self._assets = []
        self._deleted_cbs = []
        self._load()

    # ---------- 内部 ----------
    def _load(self):
        data = _read_json(self._index)
        raw = data.get("assets") if isinstance(data.get("assets"), list) else []
        clean = []
        for a in raw:
            if not isinstance(a, dict):
                continue
            sid = str(a.get("id") or "").strip()
            if not sid:
                continue
            ext = str(a.get("ext") or "").lower()
            if ext and not ext.startswith("."):
                ext = "." + ext
            if ext not in self._EXTS:
                continue  # 非法扩展名残留项丢弃
            clean.append({
                "id": sid,
                "name": str(a.get("name") or "") or "未命名声音",
                "file": str(a.get("file") or ""),
                "ext": ext,
                "added": str(a.get("added") or ""),
                "duration": a.get("duration") if isinstance(a.get("duration"), (int, float)) else None,
            })
        self._assets = clean

    def _save(self):
        return _write_json(self._index, {"assets": self._assets})

    def _get(self, slot):
        slot = str(slot or "")
        for a in self._assets:
            if a["id"] == slot:
                return a
        return None

    # ---------- 删除通知（轻量回调，无 Qt） ----------
    def on_deleted(self, cb):
        if cb not in self._deleted_cbs:
            self._deleted_cbs.append(cb)

    def off_deleted(self, cb):
        if cb in self._deleted_cbs:
            self._deleted_cbs.remove(cb)

    def _emit_deleted(self, slot):
        for cb in list(self._deleted_cbs):
            try:
                cb(slot)
            except Exception as e:
                pet_log.log_error("voice asset deleted cb failed: %r" % (e,))  # 有意忽略：不影响其余

    # ---------- 对外 ----------
    def assets(self):
        """全部声音素材 [{"id","name","file","ext","added","duration"}...]。"""
        return [dict(a) for a in self._assets]

    def get_asset(self, slot):
        """按槽位取素材元数据（副本）；不存在返回 None。"""
        a = self._get(slot)
        return dict(a) if a is not None else None

    def asset_path(self, slot):
        """素材绝对路径；不存在或文件缺失返回 None。"""
        a = self._get(slot)
        if a is None:
            return None
        p = a.get("file") or ""
        if not os.path.isabs(p):
            p = os.path.join(self._dir, p)
        try:
            return p if os.path.isfile(p) else None
        except Exception:
            return None  # 有意忽略：isfile 异常按文件不存在处理

    def exists(self, slot):
        return self.asset_path(slot) is not None

    def import_file(self, src, name=None):
        """导入参考音（复制到 voice_ref/<id>.<ext>）。仅 wav/mp3、>20MB 拒绝。"""
        try:
            if not src or not isinstance(src, str) or not os.path.isfile(src):
                return None, "文件不存在"
            ext = os.path.splitext(src)[1].lower()
            if ext not in self._EXTS:
                return None, "参考音仅支持 .wav / .mp3"
            try:
                if os.path.getsize(src) > self.MAX_BYTES:
                    return None, "文件超过 20MB，无法导入"
            except Exception:
                return None, "无法读取文件大小"
            if ext == ".wav":
                if _wav_duration(src) is None and _probe_wav_ok(src) is False:
                    return None, "WAV 文件损坏或不是 PCM 格式"
            else:
                with open(src, "rb") as f:
                    head = f.read(10)
                if not (head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF
                                                    and (head[1] & 0xE0) == 0xE0)):
                    return None, "MP3 文件损坏"
            if name is None or not str(name).strip():
                name = os.path.splitext(os.path.basename(src))[0]
            name = str(name).strip()[:40] or "未命名声音"
            try:
                os.makedirs(self._dir, exist_ok=True)
            except Exception as e:
                return None, "无法创建参考音目录：%s" % e
            sid = _new_id()
            dst = os.path.join(self._dir, sid + ext)
            try:
                shutil.copyfile(src, dst)
            except Exception:
                try:
                    if os.path.exists(dst):
                        os.remove(dst)  # 半截文件清理，不留孤儿
                except Exception:
                    pass  # 有意忽略：清理尽力而为
                return None, "复制文件失败"
            asset = {
                "id": sid,
                "name": name,
                "file": sid + ext,
                "ext": ext,
                "added": time.strftime("%Y-%m-%d"),
                "duration": _wav_duration(dst) if ext == ".wav" else None,
            }
            self._assets.append(asset)
            err = self._save()
            if err:
                try:
                    os.remove(dst)
                except Exception:
                    pass  # 有意忽略：回滚清理尽力而为
                self._assets.pop()
                return None, err
            return asset, None
        except Exception as e:
            return None, "导入失败：%s" % e

    def rename(self, slot, new_name):
        """重命名参考音。返回 (bool, err)。"""
        a = self._get(slot)
        if a is None:
            return False, "声音素材不存在"
        name = str(new_name or "").strip()
        if not name:
            return False, "名字不能为空"
        a["name"] = name[:40]
        err = self._save()
        return (False, err) if err else (True, "")

    def delete(self, slot):
        """删除参考音（文件 + 索引项），并发删除通知。返回 (bool, err)。"""
        a = self._get(slot)
        if a is None:
            return False, "声音素材不存在"
        try:
            p = a.get("file") or ""
            if not os.path.isabs(p):
                p = os.path.join(self._dir, p)
            if os.path.exists(p):
                os.remove(p)
        except Exception as e:
            return False, "删除文件失败：%s" % e
        self._assets = [x for x in self._assets if x["id"] != a["id"]]
        err = self._save()
        if err:
            return False, err
        self._emit_deleted(a["id"])
        return True, ""


# ---------------- 冒烟测试（无 GUI，可直接运行本文件） ----------------
if __name__ == "__main__":
    # P0-2：以下 print 为命令行冒烟工具输出（python pet_resources.py 运行可见），保留不改为日志
    import tempfile

    tmp = tempfile.mkdtemp(prefix="pet_resources_smoke_")

    print("=== 冒烟 1：RoleLibrary 导入 / 切换 / 删除 ===")
    rl = RoleLibrary(tmp)
    assert rl.active_id() == "" and rl.active_path() is None and rl.list_roles() == []
    import base64
    fake = os.path.join(tmp, "测试角色.png")
    with open(fake, "wb") as f:
        # 1x1 透明 PNG（D1 起 import 校验 PNG 头/IHDR 尺寸）
        f.write(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
    role, err = rl.import_file(fake)
    assert err is None and role is not None, err
    assert rl.list_roles()[0]["id"] and rl.list_roles()[0]["name"] == "测试角色"
    assert rl.get(role["id"]) is not None and rl.get("不存在") is None
    assert rl.set_active(role["id"]) is True
    p = rl.active_path()
    assert p and os.path.isfile(p) and p.lower().endswith(".png")
    assert rl.path_for(role["id"]) == p
    assert rl.set_active("不存在的id") is False
    assert rl.set_active("") is True and rl.active_path() is None
    big = os.path.join(tmp, "big.png")
    with open(big, "wb") as f:
        f.write(b"\x89PNG" + b"\x00" * (10 * 1024 * 1024 + 1))
    r2, e2 = rl.import_file(big)
    assert r2 is None and e2
    txt = os.path.join(tmp, "note.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("hi")
    r3, e3 = rl.import_file(txt)
    assert r3 is None and e3
    assert rl.delete(role["id"]) == (True, "")
    assert rl.get(role["id"]) is None and rl.list_roles() == []
    assert rl.delete(role["id"]) == (False, "角色不存在")
    # 删除 active 角色应重置为默认
    role2, _ = rl.import_file(fake, "第二个")
    rl.set_active(role2["id"])
    rl.delete(role2["id"])
    assert rl.active_id() == ""

    print("=== 冒烟 2：AudioLibrary 导入 / 重命名 / 槽位 ===")
    al = AudioLibrary(tmp)
    assert al.fragments() == [] and al.group_slots()["custom"]["press"] is None
    wav = os.path.join(tmp, "clip.wav")
    with wave.open(wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * 100)  # 有效 PCM wav（D2 起 import 校验音频头）
    frag, err = al.import_file(wav)
    assert err is None and frag is not None, err
    assert frag["ext"] == ".wav" and isinstance(frag["duration"], float)
    assert os.path.isfile(al.fragment_path(frag["id"]))
    assert al.rename(frag["id"], "  新名字 ") == (True, "")
    assert al.fragments()[0]["name"] == "新名字"
    assert al.rename("不存在", "x") == (False, "音频片段不存在")
    assert al.set_slot("press", frag["id"]) is True
    assert al.set_slot("release", "") is True
    assert al.set_slot("feed", None) is True
    assert al.set_slot("bogus", frag["id"]) is False
    assert al.set_slot("coin", "不存在的片段") is False
    gp = al.group_paths()
    assert gp["press"] and os.path.isfile(gp["press"])
    assert gp["release"] == "" and gp["feed"] is None and gp["reply"] is None
    assert al.delete(frag["id"]) == (True, "")
    assert al.group_slots()["custom"]["press"] == ""  # 被引用的槽位同步置 ""
    assert al.group_paths()["press"] == ""
    assert al.delete(frag["id"]) == (False, "音频片段不存在")
    mp3 = os.path.join(tmp, "t.mp3")
    with open(mp3, "wb") as f:
        f.write(b"ID3" + b"\x00" * 50)
    f2, e2 = al.import_file(mp3, "歌")
    assert e2 is None and f2["ext"] == ".mp3" and f2["duration"] is None
    bigm = os.path.join(tmp, "big.mp3")
    with open(bigm, "wb") as f:
        f.write(b"\x00" * (20 * 1024 * 1024 + 1))
    fb, eb = al.import_file(bigm)
    assert fb is None and eb
    r4, e4 = al.import_file(os.path.join(tmp, "不存在.wav"), None)  # 不存在 → 文件不存在
    assert r4 is None and e4 == "文件不存在"

    print("=== 冒烟 3：持久化重载 ===")
    rl2 = RoleLibrary(tmp)
    al2 = AudioLibrary(tmp)
    assert rl2.active_id() == ""
    assert [f["ext"] for f in al2.fragments()] == [".mp3"]
    assert al2.group_slots()["custom"]["press"] == ""

    print("=== 冒烟 4：P1-7 schema 迁移 / 动画查表 / update ===")
    import json as _json
    fake2 = os.path.join(tmp, "旧角色.png")
    with open(fake2, "wb") as f:
        f.write(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
    # 旧结构：角色级 frames + file_full + forms[].file（无 animations/anchor）
    old_index = {
        "roles": [{
            "id": "old1", "name": "旧帧角色", "file": "old1.png",
            "form": "dual", "file_full": "old1_full.png",
            "frames": ["old1_f00.png", "old1_f01.png", "old1_f02.png"],
            "forms": [{"name": "常态", "file": "old1.png"},
                      {"name": "吃饱", "file": "old1_full.png"}],
            "added": "",
        }],
        "active": "",
    }
    with open(os.path.join(tmp, "roles.json"), "w", encoding="utf-8") as f:
        _json.dump(old_index, f, ensure_ascii=False)
    rl3 = RoleLibrary(tmp)
    migrated = rl3.get("old1")
    assert migrated is not None
    # 迁移：frames → forms[0].animations.idle；顶层 frames 保留兼容视图
    assert animation_frames(migrated, 0, "idle") == ["old1_f00.png", "old1_f01.png", "old1_f02.png"]
    assert migrated["frames"] == animation_frames(migrated, 0, "idle")
    # file 保留作 still；file_full 仍可用（v13 语义）
    assert migrated["forms"][0]["file"] == "old1.png"
    assert migrated["file_full"] == "old1_full.png"
    assert migrated.get("v2") is False  # 纯旧结构不算 v2（保留全局 scale 补偿路径）
    # 新结构：forms[0].animations.idle + states + render，v2 标记生效
    new_index = {
        "roles": [{
            "id": "new1", "name": "新角色", "file": "new1.png",
            "form": "single", "file_full": "",
            "forms": [{
                "name": "常态", "file": "new1.png",
                "anchor": {"x": 0.5, "y": 1.0}, "scale": 1.5, "offset": {"x": 3, "y": -4},
                "animations": {"idle": ["new1_f00.png", "new1_f01.png"], "eat": []},
                "anim_interval_ms": 90,
                "states": {"angry": "new1_angry.png", "hiss": "no.txt"},
            }],
            "added": "",
        }],
        "active": "",
    }
    with open(os.path.join(tmp, "roles.json"), "w", encoding="utf-8") as f:
        _json.dump(new_index, f, ensure_ascii=False)
    rl4 = RoleLibrary(tmp)
    nr = rl4.get("new1")
    assert nr is not None and nr.get("v2") is True
    assert animation_frames(nr, 0, "idle") == ["new1_f00.png", "new1_f01.png"]
    assert animation_frames(nr, 0, "eat") == []  # 空动作不保留
    assert nr["forms"][0]["anchor"] == {"x": 0.5, "y": 1.0}
    assert nr["forms"][0]["scale"] == 1.5
    assert nr["forms"][0]["anim_interval_ms"] == 90
    assert nr["forms"][0]["states"] == {"angry": "new1_angry.png"}  # 非 png 丢弃
    # update：改名 + forms 替换 + 兼容视图同步，id 不变
    ok_up, err_up = rl4.update("new1", {
        "name": "新角色改",
        "forms": [{"name": "小形态", "file": "new1.png", "anchor": {"x": 0.5, "y": 0.5}}],
    })
    assert ok_up and err_up == "", err_up
    upr = rl4.get("new1")
    assert upr["id"] == "new1" and upr["name"] == "新角色改"
    assert len(upr["forms"]) == 1 and upr["forms"][0]["name"] == "小形态"
    assert upr["frames"] == [] and upr["file"] == "new1.png"
    # update：frames 超上限拒绝（FRAME_MAX=24）
    ok_up2, err_up2 = rl4.update("new1", {"frames": ["f%02d.png" % i for i in range(25)]})
    assert ok_up2 is False and "24" in err_up2, err_up2

    shutil.rmtree(tmp, ignore_errors=True)
    print("RESOURCES SMOKE OK")
