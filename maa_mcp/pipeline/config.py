# maa_mcp/pipeline/config.py
"""
配置模块
========
流水线相关的配置类和常量映射。
"""

from dataclasses import dataclass
from typing import Dict, Any

# 导入 MaaFramework 枚举（可选）
try:
    from maa.define import MaaWin32ScreencapMethodEnum, MaaWin32InputMethodEnum
    
    _MAA_AVAILABLE = True
except ImportError:
    _MAA_AVAILABLE = False
    MaaWin32ScreencapMethodEnum = None
    MaaWin32InputMethodEnum = None


@dataclass
class PipelineConfig:
    """流水线配置"""

    screenshot_fps: float = 2.0  # 截图帧率
    message_queue_size: int = 100  # 消息队列大小
    similarity_threshold: int = 5  # 图像相似度阈值
    enable_dedup: bool = True  # 启用消息去重


class Win32MethodMaps:
    """Win32 方法映射配置"""
    
    @staticmethod
    def get_screencap_map() -> Dict[str, Any]:
        """获取截图方法映射"""
        if not _MAA_AVAILABLE:
            return {}
        return {
            "FramePool": MaaWin32ScreencapMethodEnum.FramePool,
            "PrintWindow": MaaWin32ScreencapMethodEnum.PrintWindow,
            "GDI": MaaWin32ScreencapMethodEnum.GDI,
            "DXGI_DesktopDup_Window": MaaWin32ScreencapMethodEnum.DXGI_DesktopDup_Window,
            "ScreenDC": MaaWin32ScreencapMethodEnum.ScreenDC,
            "DXGI_DesktopDup": MaaWin32ScreencapMethodEnum.DXGI_DesktopDup,
        }
    
    @staticmethod
    def get_mouse_map() -> Dict[str, Any]:
        """获取鼠标方法映射"""
        if not _MAA_AVAILABLE:
            return {}
        return {
            "PostMessage": MaaWin32InputMethodEnum.PostMessage,
            "PostMessageWithCursorPos": MaaWin32InputMethodEnum.PostMessageWithCursorPos,
            "Seize": MaaWin32InputMethodEnum.Seize,
        }
    
    @staticmethod
    def get_keyboard_map() -> Dict[str, Any]:
        """获取键盘方法映射"""
        if not _MAA_AVAILABLE:
            return {}
        return {
            "PostMessage": MaaWin32InputMethodEnum.PostMessage,
            "Seize": MaaWin32InputMethodEnum.Seize,
        }
    
    @classmethod
    def get_screencap_method(cls, method_name: str, default=None):
        """获取截图方法枚举值"""
        screencap_map = cls.get_screencap_map()
        if default is None and _MAA_AVAILABLE:
            default = MaaWin32ScreencapMethodEnum.FramePool
        return screencap_map.get(method_name, default)
    
    @classmethod
    def get_mouse_method(cls, method_name: str, default=None):
        """获取鼠标方法枚举值"""
        mouse_map = cls.get_mouse_map()
        if default is None and _MAA_AVAILABLE:
            default = MaaWin32InputMethodEnum.PostMessage
        return mouse_map.get(method_name, default)
    
    @classmethod
    def get_keyboard_method(cls, method_name: str, default=None):
        """获取键盘方法枚举值"""
        keyboard_map = cls.get_keyboard_map()
        if default is None and _MAA_AVAILABLE:
            default = MaaWin32InputMethodEnum.PostMessage
        return keyboard_map.get(method_name, default)


# UI 元素过滤列表（用于消息去重时过滤 UI 文本）
UI_ELEMENTS_FILTER = {"微信", "发送", "输入", "语音", "表情", "更多"}


__all__ = [
    "PipelineConfig",
    "Win32MethodMaps",
    "UI_ELEMENTS_FILTER",
]
