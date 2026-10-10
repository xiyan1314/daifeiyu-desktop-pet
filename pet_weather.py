# -*- coding: utf-8 -*-
"""
天气服务：open-meteo 拉取（城市配置对话框保留在桌宠.py——v13 stub 桌宠.QInputDialog）。

独立模块：不 import 桌宠.py；signals / cfg / 日志全部注入。
"""
import threading

import requests

WEATHER_CODES = {
    0: "晴", 1: "基本晴", 2: "多云", 3: "阴",
    45: "有雾", 48: "有雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    77: "雪粒",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    85: "阵雪", 86: "阵雪",
    95: "雷雨", 96: "雷雨伴冰雹", 99: "雷雨伴冰雹",
}


class WeatherService:
    """天气线程服务：fetch() 一次查询（_weather_inflight 守卫语义不变）。"""

    def __init__(self, pet, signals, cfg_getter, log):
        self.pet = pet            # _weather_inflight / show_bubble / _show_emote
        self.signals = signals
        self._cfg = cfg_getter
        self._log = log

    def fetch(self):
        if self.pet._weather_inflight:
            self.pet.show_bubble("已经在查天气啦~")
            return
        self.pet._weather_inflight = True
        city = self._cfg().get("city", "北京")
        self.pet._show_emote("question")
        self.pet.show_bubble("查天气中……等我一下下~")
        threading.Thread(target=self._worker, args=(city,), daemon=True).start()

    def on_done(self):
        self.pet._weather_inflight = False

    def _request_weather(self, city):
        """同步查一次天气（纯 HTTP，不碰 Qt）。返回 (True, 文案) 或 (False, 失败文案)。"""
        try:
            geo = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "zh"},
                timeout=8,
            ).json()
            if not geo.get("results"):
                return False, "找不到这座城市啦……"
            r = geo["results"][0]
            w = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": r["latitude"],
                    "longitude": r["longitude"],
                    # 新版 current 参数（旧 current_weather=true 有下线风险）
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                },
                timeout=8,
            ).json()["current"]
            code = w.get("weather_code", 0)
            desc = WEATHER_CODES.get(code, "晴")
            return True, ("%s今天%s，%.0f℃，风速%.0fkm/h"
                          % (city, desc, w["temperature_2m"], w["wind_speed_10m"]))
        except Exception as e:
            self._log("weather_worker: %r" % (e,))
            return False, "天气服务开小差了……"

    def _worker(self, city):
        try:
            _ok, _text = self._request_weather(city)
            self.signals.weather.emit(_text)
        finally:
            self.signals.weather_done.emit()

    def fetch_sync(self, city=None):
        """v2.3.0（1.2 Function Calling）：工具 check_weather 的同步只读数据源。

        由 ChatService 的**工作线程**直接调用（不碰 Qt、不参与 _weather_inflight 状态机）。
        """
        _city = str(city or self._cfg().get("city", "北京") or "北京")
        ok, text = self._request_weather(_city)
        if not ok:
            return False, text
        return True, {"city": _city, "weather": text, "summary": text}
