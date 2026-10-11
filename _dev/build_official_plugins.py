# -*- coding: utf-8 -*-
"""官方内容插件打包工具（v2.5.1 · 代理 C）。

用法::

    python -B _dev/build_official_plugins.py                    # 打到 plugins/（幂等：复跑逐字节相同）
    python -B _dev/build_official_plugins.py --check            # 只比对：临时重打一遍，与 plugins/ 逐字节比较
    python -B _dev/build_official_plugins.py --out D:\tmp\pk --stamp 2026-10-11
    python -B _dev/build_official_plugins.py --base-url https://github.com/.../releases/download/v2.5.1/

产物::

    <out>/packs/<id>-<version>.dfypet-plugin.zip     5 个官方包（每个都过 pet_plugin 的 12 条判据）
    <out>/index.json                                 索引（sha256 / bytes 全是真实包哈希）

设计要点
--------
* **不手搓 zip**：条目顺序（manifest 先、payload 按路径排序）、时间戳、权限位、压缩级别全部
  固定 → 复跑产物逐字节相同（幂等判据的落点）。
* **打包即过门**：每个包构建完立刻用代理 A 的 pet_plugin.validate_plugin_zip 验一遍，不过就
  非零退出并打印原因——打包工具自己就是一道门，不靠人记得跑校验。
* **素材现取**：payload 目录结构镜像宿主的存放结构（audio/ roles/ 等），落地时能直接对上；
  role 包的 payload 就是一份标准 dfypet-role 角色包内容（manifest.json + roles/），
  宿主可以直接走 pet_export.import_bundle 落地，零新代码。
* 内容里**没有代码**：kind=data / code=false / capabilities=[] 三件套对每个包都成立。
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import plugin_pack_rules as rules   # noqa: E402  判据参照实现 + 确定性 zip 读写 + 版本比较

ASSETS = os.path.join(REPO, "assets")
DEFAULT_OUT = os.path.join(REPO, "plugins")
DEFAULT_STAMP = "2026-10-11"
DEFAULT_BASE_URL = "packs/"

PACK_VERSION = "1.0.0"
AUTHOR = "大肥鱼桌宠（官方）"
HOMEPAGE = "https://github.com/xiyan1314/daifeiyu-desktop-pet"
LICENSE = "MIT"
BUNDLE_EXT = ".dfypet-plugin.zip"


# ---------------- 内容素材（**没有代码**：全是文本/图片/音频数据） ----------------

# 音效包：文件名 -> (显示名, 建议槽位)。槽位取自 pet_resources.SLOT_KINDS，"" = 不建议绑定。
# 建议槽位只是"给安装器/用户看的提示"，安装器可以不采纳（不动用户现有音效组更安全）。
AUDIO_ITEMS = (
    ("ya1.wav", "点击·呀", "press"),
    ("ya2.wav", "松开·呀啊", "release"),
    ("d1.wav", "被戳到·抖一下", ""),
    ("d2.wav", "喂食·啊呜", "feed"),
    ("task-end-a.wav", "AI 回复完成", "reply"),
    ("exp-orb.wav", "金币到账", "coin"),
)

# 台词包：key / 文案 / 类别（类别必须是 pet_lines.LINE_CATEGORIES 里的）
LINE_ITEMS = (
    ("moyu_01", "绳匠～陪我摸一会儿鱼嘛，就一会儿。", "sajiao"),
    ("moyu_02", "今天也要把本鱼放在心尖尖上哦！", "sajiao"),
    ("moyu_03", "哼，不理我的话……我就自己游过来啦！", "sajiao"),
    ("moyu_04", "小鱼干的味道！隔着屏幕都闻到了！", "greedy"),
    ("moyu_05", "本鱼宣布：这块蛋糕正在进行安全检测。", "greedy"),
    ("moyu_06", "钻石？亮晶晶的……咬一下应该没关系吧？", "greedy"),
    ("moyu_07", "嘿嘿，被夸了，尾巴都翘起来了！", "happy"),
    ("moyu_08", "今天的手感也不错，适合摸鱼！", "happy"),
    ("moyu_09", "绳匠在，本鱼就开心得冒泡泡～", "happy"),
    ("moyu_10", "写代码辛苦了，要不要看看鱼？", "idle"),
    ("moyu_11", "本鱼在认真思考……今晚吃什么。", "idle"),
    ("moyu_12", "窗外的云好好看，跟小鱼干一样好看。", "idle"),
)
DIALOGUE_ITEMS = (("摸鱼三连", ("moyu_01", "moyu_07", "moyu_10")),)

# 行为包：ASCII 安全名（validate_name：字母开头、字母数字下划线、<=24）-> 动作序列
BEHAVIOR_ITEMS = (
    ("coin_brag", [{"act": "play_action", "name": "jump"},
                   {"act": "emote", "kind": "sparkle"},
                   {"act": "say", "text": "发财啦发财啦！"},
                   {"act": "voice", "event": "reply"},
                   {"act": "wait", "ms": 800}]),
    ("shy_wiggle", [{"act": "emote", "kind": "heart"},
                    {"act": "say", "text": "才、才没有很开心呢！"},
                    {"act": "voice", "event": "poke"},
                    {"act": "wait", "ms": 600}]),
    ("sleepy_curl", [{"act": "emote", "kind": "zzz"},
                     {"act": "say", "text": "呼呼……再睡五分钟……"},
                     {"act": "voice", "event": "sleep"},
                     {"act": "wait", "ms": 1500}]),
    ("snack_alert", [{"act": "play_action", "name": "jump"},
                     {"act": "say", "text": "我闻到了零食的味道！"},
                     {"act": "voice", "event": "feed"},
                     {"act": "wait", "ms": 700}]),
)

# 人设包：文件名（= 界面里显示的预设名，宿主取 prompts/custom/*.txt）
PERSONA_NAME = "摸鱼搭子"
PERSONA_TEXT = (
    "你是一只叫「摸鱼搭子」的鱼系桌宠，整天泡在代码海里陪用户摸鱼。自称「本鱼」，"
    "把用户叫做「绳匠」；说话轻松口语化，用户在忙就催他起来走两步，用户闲着就一起摆烂。"
    "不端着、不说教、偶尔犯懒卖傻，被夸会不好意思。"
    "回答必须中文、俏皮简短、不超过25个字。"
)

# 角色包：状态图（state -> 素材文件名），键必须都在 pet_resources.STATE_NAMES 里
STATE_FILES = {
    "sleep": "sleep", "puzzled": "puzzled", "angry": "angry", "hiss": "hiss",
    "cry": "cry", "laugh": "laugh", "smug": "smug", "surprised": "surprised",
    "drool": "drool", "blush": "blush",
}
ROLE_STATES_NORMAL = ("sleep", "puzzled", "angry", "hiss", "cry",
                      "laugh", "smug", "surprised", "drool", "blush")
ROLE_STATES_FULL = ("sleep", "puzzled", "angry", "cry", "laugh", "smug", "blush")
ROLE_ID = "official_daifeiyu"
ROLE_NAME = "官方·大肥鱼"


# ---------------- 生成各类 payload 内容 ----------------

def _lines_payload():
    """台词包 payload：宿主把每条并入 lines.json（LineService.add 逐条），对白按 key 重指。"""
    cats = sorted({c for _k, _t, c in LINE_ITEMS})
    obj = {
        "format": "dfypet-lines",
        "version": 1,
        "note": ("示例台词包：装上后逐条并入你的台词库（不改动、不删除你已有的台词）；"
                 "categories 见宿主 pet_lines.LINE_CATEGORIES"),
        "categories": cats,
        "lines": [{"key": k, "text": t, "category": c, "role_slot": "", "voice_slot": ""}
                  for k, t, c in LINE_ITEMS],
        # 对白引用字段名按宿主安装器的契约：{"name","lines":[key…]}（也认 line_ids / keys）
        "dialogues": [{"name": nm, "lines": list(keys)} for nm, keys in DIALOGUE_ITEMS],
    }
    return rules.dump_json_bytes(obj)


def _audio_payload():
    """音效包 payload：宿主对每个 wav 调 AudioLibrary.import_file（拷进 audio/ + 写 audio.json）。

    pack.json 的 files 形状是**宿主安装器的契约**（_pack_names：{"files": {相对路径: 显示名}}
    或 {"files": [{"file","name"}]}，键是 payload 相对路径）；suggested_slots 只作说明用，
    宿主**有意不采纳**槽位建议（选择权留给用户）。
    """
    obj = {
        "format": "dfypet-audio",
        "version": 1,
        "note": ("装上后这 6 段会进「资源管理 → 音频片段」，可在音效组里指派给"
                 "点击/松开/喂食/AI 回复/金币（装完不会自动改你现在的音效组）。"),
        "files": [{"file": "audio/" + fn, "name": nm} for fn, nm, _slot in AUDIO_ITEMS],
        "suggested_slots": {"press": "audio/ya1.wav", "release": "audio/ya2.wav",
                            "feed": "audio/d2.wav", "reply": "audio/task-end-a.wav",
                            "coin": "audio/exp-orb.wav"},
    }
    return rules.dump_json_bytes(obj)


def _behavior_id(name):
    """行为文件里的 id **必填**：pet_behaviors._norm_behavior 硬判"8 位小写 hex"，
    缺了整条会被判"行为 id 非法"（落地实测踩到的第一条）。宿主 import_file 会换成新 id，
    但文件本身必须带一个合法 id——所以这里按行为名派生一个**确定性**的示例 id。"""
    return hashlib.md5(("dfypet-official:" + name).encode("utf-8")).hexdigest()[:8]


def _behavior_payload(name, steps):
    """单条行为文件：格式与宿主「导出行为」（BehaviorService.export_file）逐字段一致。"""
    return rules.dump_json_bytes({"format": "dfypet-behavior", "version": 1,
                                  "behavior": {"id": _behavior_id(name), "name": name,
                                               "steps": steps}})


def _role_dict():
    """角色包 payload 里的 role.json —— **就是一个角色 dict**（与 roles.json 里的条目同形状）。

    素材引用（file / file_full / forms[].file·front·states）全是 **payload 根下的 png 文件名**
    （不带目录前缀）——这正是 pet_plugin_host 的落地口径：payload/role.json + 素材平铺在
    payload 根，宿主 _resolve_inside 逐个解析、换新文件名复制进 roles/，再走
    pet_export.land_role（与「导入角色包」同一套口径）。
    """
    normal_states = {s: "daifeiyu_n_%s.png" % STATE_FILES[s] for s in ROLE_STATES_NORMAL}
    full_states = {s: "daifeiyu_f_%s.png" % STATE_FILES[s] for s in ROLE_STATES_FULL}
    return {
        "id": ROLE_ID,
        "name": ROLE_NAME,
        "file": "daifeiyu.png",
        "form": "dual",
        "file_full": "daifeiyu_full.png",
        "forms": [
            {"name": "常态", "file": "daifeiyu.png", "front": "daifeiyu_front.png",
             "states": normal_states},
            {"name": "吃饱", "file": "daifeiyu_full.png", "front": "daifeiyu_full_front.png",
             "states": full_states},
        ],
        "frames": [],
        "added": "",
    }


def _role_assets():
    """角色包的 (assets 相对路径 -> payload 相对路径) 清单：素材**平铺在 payload 根**。"""
    out = [
        ("character.png", "daifeiyu.png"),
        ("character_front.png", "daifeiyu_front.png"),
        ("character_full.png", "daifeiyu_full.png"),
        ("character_full_front.png", "daifeiyu_full_front.png"),
    ]
    for s in ROLE_STATES_NORMAL:
        out.append(("n_%s.png" % STATE_FILES[s], "daifeiyu_n_%s.png" % STATE_FILES[s]))
    for s in ROLE_STATES_FULL:
        out.append(("f_%s.png" % STATE_FILES[s], "daifeiyu_f_%s.png" % STATE_FILES[s]))
    return out


PACKS = (
    {
        "id": "official-audio-core",
        "name": "官方·基础音效（6 段）",
        "data_kind": "audio",
        "landing": "ready",     # 端到端实测：真安装器装得上，且宿主库真的 +N（见 _check_landing）
        "summary": "6 段系统音效：点击 / 松开 / 被戳 / 喂食 / AI 回复完成 / 金币到账",
        "description": ("包含什么：assets/sounds 里的 6 个 wav（ya1 / ya2 / d1 / d2 / "
                        "task-end-a / exp-orb），素材约 394 KB（压成包 165 KB）。\n"
                        "装上会看到什么：「资源管理 → 音频片段」里多 6 条，可在「音效组」里"
                        "指派给点击/松开/喂食/AI 回复/金币，也可以只留几条。\n"
                        "落地方式：对每个 wav 调 AudioLibrary.import_file（拷进 <数据目录>/audio/ "
                        "并写 audio.json）。"),
        "assets": [("sounds/" + fn, "audio/" + fn) for fn, _nm, _s in AUDIO_ITEMS],
        "generated": {"audio/pack.json": _audio_payload},
    },
    {
        "id": "official-lines-moyu",
        "name": "官方·摸鱼台词（12 条 + 1 组对白）",
        "data_kind": "lines",
        "landing": "ready",
        "summary": "12 条新增台词（撒娇/贪吃/开心/闲逛）+ 一组「摸鱼三连」对白",
        "description": ("包含什么：12 条原创台词（撒娇/贪吃/开心/闲逛各 3 条）+ 一组三句的对白"
                        "编排「摸鱼三连」，约 2 KB 的 JSON。\n"
                        "装上会看到什么：台词库里多出这 12 条（类别已分好，可直接被随机/待机"
                        "引用），对白列表里多「摸鱼三连」；你原有的台词一条都不会动、也不会被覆盖。\n"
                        "落地方式：payload/lines.json → 宿主逐条 LineService.add(text, category, "
                        "role_slot, voice_slot)，再按 key → 新 id 建对白；任一条失败逐条回滚。"),
        "assets": [],
        "generated": lambda: {"lines.json": _lines_payload()},
    },
    {
        "id": "official-role-daifeiyu",
        "name": "官方·大肥鱼角色包（双形态 + 17 张表情）",
        "data_kind": "role",
        "landing": "ready",
        "summary": "把自带的大肥鱼做成角色包：双形态（常态/吃饱）+ 17 张表情状态图",
        "description": ("包含什么：本体 4 张（侧/正 × 常态/吃饱）+ 17 张表情状态图，约 1.2 MB。\n"
                        "装上会看到什么：「角色」列表里多一只「官方·大肥鱼」，可改名/删除；"
                        "戳戳、喂食、睡觉的表情走这套美术图（而不是程序化叠图）；"
                        "重复安装会再进一只（id 不冲突），原有角色一个不动。\n"
                        "落地方式：payload/role.json（角色 dict，素材引用就是 payload 根的 png "
                        "文件名）+ 21 张 png → PluginHost 逐个换新文件名复制进 roles/，再走 "
                        "pet_export.land_role（与「导入角色包」同一套口径）。"),
        "assets": _role_assets,
        "generated": lambda: {"role.json": _role_json_bytes()},
    },
    {
        "id": "official-behaviors-idle",
        "name": "官方·待机行为（4 条）",
        "data_kind": "behaviors",
        "landing": "ready",     # 端到端实测：真安装器装得上，且宿主库真的 +N（见 _check_landing）
        "summary": "4 条现成行为：得意炫耀 / 害羞扭扭 / 蜷着睡 / 闻到零食",
        "description": ("包含什么：4 个行为 JSON（每个一条动作序列，动作类型与参数都过 "
                        "pet_behaviors.validate_steps），约 2 KB。\n"
                        "装上会看到什么：「行为」列表里多这 4 条，可在「待机行为」里给它们"
                        "排顺序/权重，让它自己动起来。\n"
                        "落地方式：对每个 json 调 BehaviorService.import_file（会分配新 id）。"),
        "assets": [],
        "generated": lambda: _behaviors_payload(),
    },
    {
        "id": "official-persona-moyu",
        "name": "官方·人设「摸鱼搭子」",
        "data_kind": "prompt",
        "landing": "ready",     # 端到端实测：真安装器装得上，且宿主库真的 +N（见 _check_landing）
        "summary": "一份新的人设文本：轻松口语化的摸鱼搭子（AI 设置里可切换）",
        "description": ("包含什么：一份人设 .txt（约 200 字节）。\n"
                        "装上会看到什么：AI 设置的人设下拉里多一项「我的：摸鱼搭子」，"
                        "选中即可让它换性格说话。\n"
                        "落地方式：把人设文件拷进 <数据目录>/prompts/custom/，"
                        "文件名就是预设名（宿主 persona_file_ids 自动认）。"),
        "assets": [],
        "generated": lambda: _persona_payload(),
    },
)


def shipped_packs(with_pending=False):
    """出货清单：默认只出 landing == "ready" 的包。

    为什么还要 landing 门：pet_plugin_host.LANDING_KINDS 现在六类全接（role / lines /
    audio / voice_ref / behaviors / prompt，见该模块的 _land 分派表），所以五个官方包都是
    ready。这道门保留下来是给**将来的新 data_kind**用的：某一类的落地管线还没接好时，
    包进了索引只会让用户撞上"本版本暂不支持落地「xxx」类插件"的拒绝（宁少勿假）。
    （voice_ref 一类目前没有官方包——没有合适素材，见 _dev/plugin_packs_report.md 第四节。）
    """
    return tuple(p for p in PACKS if with_pending or p.get("landing") == "ready")


def _behaviors_payload():
    return {"behaviors/%s.json" % name: _behavior_payload(name, steps)
            for name, steps in BEHAVIOR_ITEMS}


def _persona_payload():
    return {"prompts/%s.txt" % PERSONA_NAME: (PERSONA_TEXT + "\n").encode("utf-8")}


def _role_json_bytes():
    return rules.dump_json_bytes(_role_dict())


def _resolve(value):
    """PACKS 里的字段可以是值，也可以是返回值的函数（懒构造，便于互相引用）。"""
    return value() if callable(value) else value


def _pack_items(pack):
    """-> [(payload 相对路径, bytes)]（按路径排序，确定性）。"""
    items = []
    for src_rel, dst_rel in _resolve(pack["assets"]):
        src = os.path.join(ASSETS, src_rel.replace("/", os.sep))
        if not os.path.isfile(src):
            raise SystemExit("素材不存在：assets/%s" % src_rel)
        with open(src, "rb") as f:
            items.append(("payload/" + dst_rel, f.read()))
    gen = _resolve(pack["generated"])
    for rel, data in (gen or {}).items():
        items.append(("payload/" + rel, data() if callable(data) else data))
    items.sort(key=lambda kv: kv[0])
    seen = set()
    for rel, _data in items:
        if rel in seen:
            raise SystemExit("payload 路径重复：%s" % rel)
        seen.add(rel)
        ext = os.path.splitext(rel)[1].lower()
        if ext not in rules.ALLOWED_EXTS:
            raise SystemExit("payload 里有白名单外的文件类型（打包工具拒绝出货）：%s" % rel)
    if not items:
        raise SystemExit("包 %s 没有任何 payload 文件" % pack["id"])
    return items


def _manifest(pack, items, host_ver, stamp):
    files = [{"path": rel, "sha256": rules.sha256_bytes(data), "bytes": len(data)}
             for rel, data in items]
    return {
        "format": rules.PLUGIN_FORMAT,
        "version": rules.PLUGIN_FORMAT_VERSION,
        "payload_root": rules.PAYLOAD_ROOT,
        "created_at": stamp + "T00:00:00",
        "files": files,
        "plugin": {
            "id": pack["id"],
            "name": pack["name"],
            "version": PACK_VERSION,
            "author": AUTHOR,
            "homepage": HOMEPAGE,
            "license": LICENSE,
            "summary": pack["summary"],
            "description": pack["description"],
            "kind": "data",
            "data_kind": pack["data_kind"],
            "code": False,
            "min_host_version": host_ver,
            "max_host_version": "",
            "api_version": 1,
            "capabilities": [],
            "events": [],
            "signature": "",
        },
    }


def _check_role_payload(items):
    """role 包自检：role.json 的素材引用必须**不多不少**对上 payload 里的 png。

    （引用对不上 = 用户装完得到一个"缺素材"的角色；宿主 _land_role 会当场报错并回滚，
    但那已经是用户侧了——打包工具必须先在构建期拦住。）
    """
    import pet_export
    table = dict(items)
    try:
        role = json.loads(table["payload/role.json"].decode("utf-8"))
    except KeyError:
        raise SystemExit("role 包的 payload 里没有 role.json")
    except Exception as e:
        raise SystemExit("role.json 不是合法 JSON：%s" % e)
    refs = sorted(pet_export._role_file_refs(role))
    pngs = sorted(os.path.basename(p) for p in table if p.lower().endswith(".png"))
    if refs != pngs:
        raise SystemExit("role.json 的素材引用与 payload 里的 png 对不上：引用 %s / 文件 %s"
                         % (refs, pngs))
    return len(refs)


def _check_landing(pack, path, host_ver, strict=True):
    """**真安装**自检：就地用 pet_plugin_host 装一遍（临时数据目录）。

    这是比"过校验器"更硬的一道门：过校验器只说明包合法，这里说明**用户真的装得上**。
    landing=="ready" 的包过不了就非零退出（上架必须以"真能装"为准）；landing=="pending"
    的包只记录现状——某天它装上了，就说明 B 的 LANDING_KINDS 扩到位了，可以 --all 上架。
    """
    ready = pack.get("landing") == "ready"
    try:
        import pet_lines
        import pet_plugin_host
        import pet_resources
    except Exception as e:
        if ready and strict:
            raise SystemExit(
                "上架包 %s 无法做真安装自检：pet_plugin_host 当前不可用（%r）。\n"
                "  修好它再打包；确实要出包用 --skip-landing-check（产物不作上架依据）。"
                % (pack["id"], e))
        return "（未验证：pet_plugin_host 不可用：%r）" % (e,)
    import pet_behaviors
    with tempfile.TemporaryDirectory(prefix="dfypet_build_land_") as td:
        role_lib = pet_resources.RoleLibrary(td)
        lines_lib = pet_lines.LineService(td)
        audio_lib = pet_resources.AudioLibrary(td)
        behaviors = pet_behaviors.BehaviorService(td)
        host = pet_plugin_host.PluginHost(
            td, host_ver, role_lib=role_lib, lines_lib=lines_lib,
            audio_lib=audio_lib, behaviors=behaviors)
        ok, msg = host.install_zip(path, source_url="build-check://")
        count = _landed_count(pack["data_kind"], td, role_lib, lines_lib, audio_lib, behaviors)
    if ok and count > 0:
        return "%s  落地核对：%s +%d" % (msg, pack["data_kind"], count)
    why = ("装上了但宿主库没有变化（落地核对 = %d）" % count) if ok else msg
    if ready and strict:
        raise SystemExit("包 %s 过不了真安装管线（pet_plugin_host.install_zip）：%s"
                         % (pack["id"], why))
    return "（本轮不上架：宿主安装器当前不接受 %s —— %s）" % (pack["data_kind"], why)


def _landed_count(kind, data_dir, role_lib, lines_lib, audio_lib, behaviors):
    """安装后宿主库里**真的多了多少条**（0 = 装了个寂寞，不算装上）。"""
    if kind == "role":
        return len(role_lib.list_roles())
    if kind == "lines":
        return lines_lib.count()
    if kind == "audio":
        return len(audio_lib.fragments())
    if kind == "behaviors":
        return len(behaviors.list())
    if kind == "prompt":
        d = os.path.join(data_dir, "prompts", "custom")
        try:
            return len([n for n in os.listdir(d) if n.lower().endswith(".txt")])
        except Exception:
            return 0
    return 0


def _build_pack(pack, out_dir, host_ver, stamp, strict_landing=True):
    """打一个包 → 信息 dict；构建后立刻过校验器 + 真安装自检（不过就非零退出）。"""
    items = _pack_items(pack)
    mf = _manifest(pack, items, host_ver, stamp)
    entries = [("manifest.json", rules.dump_json_bytes(mf))] + list(items)
    name = "%s-%s%s" % (pack["id"], PACK_VERSION, BUNDLE_EXT)
    path = os.path.join(out_dir, "packs", name)
    rules.write_zip(path, entries)
    got, err = rules.validate(path, host_ver)
    if got is None:
        raise SystemExit("包 %s 没通过校验器：%s" % (pack["id"], err))
    if got["plugin"]["id"] != pack["id"] or got["plugin"]["data_kind"] != pack["data_kind"]:
        raise SystemExit("包 %s 的 manifest 与规格不一致" % pack["id"])
    refs = _check_role_payload(items) if pack["data_kind"] == "role" else 0
    landing_msg = _check_landing(pack, path, host_ver, strict=strict_landing)
    return {"id": pack["id"], "name": pack["name"], "data_kind": pack["data_kind"],
            "landing": pack.get("landing", ""), "summary": pack["summary"],
            "path": path, "filename": name,
            "sha256": rules.sha256_file(path), "bytes": os.path.getsize(path),
            "files": len(items), "entries": len(entries), "role_refs": refs,
            "landing_msg": landing_msg}


def _index(infos, host_ver, stamp, base_url):
    return {
        "index_version": 1,
        "updated_at": stamp,
        "host_min": host_ver,
        "plugins": [
            {
                "id": info["id"],
                "name": info["name"],
                "kind": "data",
                "data_kind": info["data_kind"],
                "code": False,
                "summary": info["summary"],
                "author": AUTHOR,
                "releases": [{
                    "version": PACK_VERSION,
                    "min_host_version": host_ver,
                    "api_version": 1,
                    "url": base_url + info["filename"],
                    "sha256": info["sha256"],
                    "bytes": info["bytes"],
                    "published_at": stamp,
                }],
            }
            for info in infos
        ],
    }


def build(out_dir, stamp, host_ver, base_url, quiet=False, with_pending=False,
          strict_landing=True):
    """打**全部**官方包 + 写 index.json（索引只挂上架的）。返回 (infos, index_path)。

    包与上架解耦：5 个包都打进 packs/（仓库内容），index.json 只列 landing=="ready" 的
    ——"用户点安装必须真的装上"，挂一个装不上的包比少一个伤害大（主代理 2026-10-11 裁决）。
    --all = 把 pending 的也挂进索引（等 B 的安装器扩完 LANDING_KINDS 再用）。
    """
    packs_dir = os.path.join(out_dir, "packs")
    os.makedirs(packs_dir, exist_ok=True)
    infos = []
    for pack in PACKS:
        info = _build_pack(pack, out_dir, host_ver, stamp, strict_landing=strict_landing)
        info["listed"] = (pack.get("landing") == "ready") or with_pending
        infos.append(info)
        if not quiet:
            tag = "[上架]" if info["listed"] else "[备好]"
            print("  %s %-28s %5d 文件 %8d 字节  %s"
                  % (tag, info["id"], info["files"], info["bytes"], info["sha256"][:16]))
            print("       %s" % info["landing_msg"])
    # 清掉上一轮留在 packs/ 里、这轮不再上架的包：否则磁盘上的包与 index.json 对不上，
    # 用户还能在文件夹里看到并装上"本轮没上架"的东西（索引自洽判据也会红）。
    keep = {info["filename"] for info in infos}
    stale = []
    for fn in sorted(os.listdir(packs_dir)):
        if fn.endswith(BUNDLE_EXT) and fn not in keep:
            os.remove(os.path.join(packs_dir, fn))
            stale.append(fn)
    if stale and not quiet:
        print("  [--] 清掉 %d 个本轮不上架的旧包：%s" % (len(stale), "、".join(stale)))
    listed = [i for i in infos if i["listed"]]
    index_path = os.path.join(out_dir, "index.json")
    with open(index_path, "wb") as f:
        f.write(rules.dump_json_bytes(_index(listed, host_ver, stamp, base_url)))
    if not quiet:
        held = [i["id"] for i in infos if not i["listed"]]
        print("  [OK] index.json：上架 %d 个插件（host_min=%s，updated_at=%s）"
              % (len(listed), host_ver, stamp))
        if held:
            print("  [--] 包已打好在 packs/，但本轮不挂索引（等安装器扩 LANDING_KINDS）：%s"
                  % "、".join(held))
    return infos, index_path


def _owned_files(root):
    """打包工具**自己产出**的文件：index.json + packs/*.dfypet-plugin.zip。

    plugins/README.md 是手写件，不归打包工具生成——比它等于要求打包工具"重写文档"，
    所以复跑比对只看产出物（顺带能抓出"上一轮留下、这轮不再上架的旧包"）。
    """
    out = {}
    p = os.path.join(root, "index.json")
    if os.path.isfile(p):
        out["index.json"] = p
    packs_dir = os.path.join(root, "packs")
    if os.path.isdir(packs_dir):
        for fn in sorted(os.listdir(packs_dir)):
            if fn.endswith(BUNDLE_EXT):
                out["packs/" + fn] = os.path.join(packs_dir, fn)
    return out


def _diff_dirs(a, b):
    """比较两个目录里**打包工具产出的**文件（返回差异说明列表；逐字节）。"""
    fa, fb = _owned_files(a), _owned_files(b)
    out = []
    for rel in sorted(set(fa) - set(fb)):
        out.append("只在 %s 里有：%s" % (a, rel))
    for rel in sorted(set(fb) - set(fa)):
        out.append("只在 %s 里有：%s" % (b, rel))
    for rel in sorted(set(fa) & set(fb)):
        with open(fa[rel], "rb") as x, open(fb[rel], "rb") as y:
            if x.read() != y.read():
                out.append("内容不同：%s" % rel)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="官方内容插件打包（幂等、可复跑）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录（缺省 <仓库>/plugins）")
    ap.add_argument("--stamp", default=DEFAULT_STAMP, help="created_at / updated_at / published_at")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL,
                    help="index.json 里 url 的前缀（缺省 packs/ = 相对 index.json）")
    ap.add_argument("--check", action="store_true",
                    help="只比对：临时重打一遍，与 --out 逐字节比较（不写盘）")
    ap.add_argument("--all", action="store_true",
                    help="把 landing=pending 的包也挂进索引（安装器扩了 LANDING_KINDS 之后再用）")
    ap.add_argument("--skip-landing-check", action="store_true",
                    help="跳过 ready 包的真安装自检（只在 pet_plugin_host 临时不可用时用；"
                         "用它打出来的产物不作上架依据）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    host_ver = rules.host_version()
    engine, why = rules.engine_status()
    if not args.quiet:
        print("宿主版本 %s · 校验引擎 %s（%s）" % (host_ver, engine, why))
    if args.check:
        with tempfile.TemporaryDirectory(prefix="dfypet_packs_check_") as td:
            build(td, args.stamp, host_ver, args.base_url, quiet=True,
                  with_pending=args.all, strict_landing=not args.skip_landing_check)
            diffs = _diff_dirs(args.out, td)
        if diffs:
            print("复跑产物与 %s 不一致（幂等失败）：" % args.out)
            for d in diffs[:20]:
                print("  - %s" % d)
            return 1
        if not args.quiet:
            print("幂等 OK：临时重打的产物与 %s 逐字节相同" % args.out)
        return 0
    infos, index_path = build(args.out, args.stamp, host_ver, args.base_url,
                              quiet=args.quiet, with_pending=args.all,
                              strict_landing=not args.skip_landing_check)
    if not args.quiet:
        total = sum(i["bytes"] for i in infos)
        listed = sum(1 for i in infos if i["listed"])
        print("共 %d 个包（上架 %d 个）/ 合计 %d 字节（%s）"
              % (len(infos), listed, total, os.path.relpath(args.out, REPO)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
