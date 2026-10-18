# -*- coding: utf-8 -*-
"""D1 首次引导（v2.12.0 第 12 轮 · UX 三小项）：**只弹一次**的启动引导。

为什么单独一个模块：判定只有三行，但它必须能被"不碰 Qt、不碰磁盘"地钉住。
本轮把此前那个**进程级全局** `_HIDE_TIP_SHOWN`（重启就忘）换成配置里的一次性标记
`first_run_done`；判定 / 落盘 / 展示三件事拆成可注入的三段，测试直接喂合成值。

口径（与配置归一化同一条）：
  · 只认**归一化之后的 True**（`is True`）。手改 config.json 写成 "true" / 1 / null 都会被
    pet_config 归一成 bool；这里对原始坏值一律当"还没引导过" —— 宁可多弹一次，
    也不让一条坏记录让新用户永远看不到引导。
  · **先置真、再落盘、再展示**：落盘失败不会在同一次运行里重复骚扰；展示失败（窗口正在
    退出等）也不回滚标记 —— 用户没看到是遗憾，但"下次启动再弹"比"一次运行里连弹三次"好。
  · 落盘/展示的异常在这里吞掉并**返回原因**（调用方负责留痕）；引导本身绝不许把启动带崩。
"""

# 文案口径：一句话说清"右键 / 拖动 / 托盘"三件事，不发表情、不发声（陪伴，不是打扰）。
FIRST_RUN_HINT = ("第一次见～右键我打开菜单（换形态、调大小、喂食都在里面）；"
                  "按住可以拖到别处；关掉我只是收进托盘，右键托盘图标能叫回来。")


def should_guide(cfg):
    """这一轮要不要弹引导：只认归一化之后的 True。"""
    return cfg.get("first_run_done") is not True


def mark_done(cfg):
    """置真（就地改 dict；不落盘）。返回同一个 cfg 便于串起来写。"""
    cfg["first_run_done"] = True
    return cfg


def guide(cfg, save, show):
    """弹一次首次引导 → (弹了没, 出问题的一句人话或 None)。

    save(cfg)：成功返回 None、失败返回原因（与 桌宠.save_config 的约定一致）。
    show(text)：气泡**是否真的显示出来**（与 桌宠.show_bubble 的实报一致）。
    两个都允许抛异常 —— 这里一律收成返回值，不向启动流程抛。
    """
    if not should_guide(cfg):
        return False, None
    mark_done(cfg)                      # 先置真：落盘挂了也不在同一次运行里重复骚扰
    err = None
    try:
        err = save(cfg)
    except Exception as e:              # noqa: BLE001 —— 落盘异常不许把启动带崩
        err = "首次引导标记落盘失败：%r" % (e,)
    shown = False
    try:
        shown = bool(show(FIRST_RUN_HINT))
    except Exception as e:              # noqa: BLE001 —— 气泡异常同样不许带崩启动
        err = err or ("首次引导气泡失败：%r" % (e,))
    return shown, err
