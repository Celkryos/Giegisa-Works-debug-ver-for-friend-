"""后台媒体会话探测（Windows GSMTC）。

通过 WinRT 的 GlobalSystemMediaTransportControlsSessionManager 枚举
系统中所有已向系统注册的媒体会话（浏览器、网易云、QQ 音乐等），
即使应用在后台播放也能拿到标题/艺术家/播放状态。

依赖可选第三方包 winsdk（pip install winsdk）。未安装时所有函数
安全降级为空结果，调用方自动回退到“前台窗口标题”识别。
"""

import asyncio

# 播放状态枚举值（与 GlobalSystemMediaTransportControlsSessionPlaybackStatus 对齐）
_PLAYING = 4


def _normalize_app_id(app_id):
    """AUMID 往往带实例后缀（如 Chrome.exe._bla_），做个简单清洗。"""
    text = str(app_id or "").strip()
    for suffix in (".exe", ".EXE"):
        if text.lower().endswith(suffix):
            text = text[: -len(suffix)]
    return text.split("!")[0].split(".")[0] if "!" in text else text


async def _query_sessions():
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    )
    manager = await SessionManager.request_async()
    results = []
    for session in manager.get_sessions():
        try:
            info = session.get_playback_info()
            if info is None or info.playback_status != _PLAYING:
                continue
            props = await session.try_get_media_properties_async()
            title = (getattr(props, "title", "") or "").strip()
            artist = (getattr(props, "artist", "") or "").strip()
            if title:
                results.append({
                    "app": _normalize_app_id(session.source_app_user_model_id),
                    "title": title,
                    "artist": artist,
                })
        except Exception:
            # 单个会话异常（应用刚退出等）不影响整体枚举
            continue
    return results


def get_playing_media():
    """返回当前正在后台/前台播放的媒体会话列表 [{app, title, artist}]。

    未安装 winsdk、非 Windows 或查询失败时返回空列表。
    """
    try:
        return asyncio.run(_query_sessions())
    except ImportError:
        return []
    except Exception:
        return []


def winsdk_available():
    """检测可选依赖 winsdk 是否可用（用于设置界面提示等）。"""
    try:
        import winsdk  # noqa: F401
        return True
    except ImportError:
        return False
