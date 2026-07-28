"""后台媒体会话探测（GSMTC）的契约测试。

- 有 winsdk 时真实查询必须返回列表（本机无播放则为空列表）
- 模拟 winsdk 缺失时必须安全降级为空列表（前台识别回退不受影响）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.media_sessions as media_sessions


def main():
    # 1. 真实查询：返回列表（无播放时为空，不得抛异常）
    result = media_sessions.get_playing_media()
    assert isinstance(result, list), result

    # 2. 模拟 winsdk 未安装：导入失败 → 安全返回空列表
    blocked = {
        name: None for name in list(sys.modules)
        if name == "winsdk" or name.startswith("winsdk.")
    }
    sys.modules.update(blocked)
    try:
        assert media_sessions.get_playing_media() == []
    finally:
        for name in blocked:
            del sys.modules[name]

    # 3. AUMID 清洗
    assert media_sessions._normalize_app_id("Spotify.exe") == "Spotify"
    assert media_sessions._normalize_app_id("Chrome") == "Chrome"
    assert media_sessions._normalize_app_id("App!Package.Id") == "App"
    assert media_sessions._normalize_app_id("") == ""

    print("MEDIA_SESSIONS_OK")


if __name__ == "__main__":
    main()
