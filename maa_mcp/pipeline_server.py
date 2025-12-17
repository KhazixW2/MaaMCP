# pipeline_server.py
"""
多进程流水线 MCP 服务器
======================
真正可运行的 MCP 服务器入口，支持多进程后台监控。

使用方法：
1. 作为 MCP 服务器运行 (替代 __main__.py):
   python maa_mcp/pipeline_server.py

2. 运行测试:
   python maa_mcp/pipeline_server.py --test
"""

import os
import sys
import time
import json
import logging
import argparse
from multiprocessing import Process, Queue, Event, Manager
from queue import Empty
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# 导入 MaaFramework 相关
try:
    from maa.controller import AdbController, Win32Controller
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.pipeline import JRecognitionType, JOCR
    from maa.define import MaaWin32ScreencapMethodEnum, MaaWin32InputMethodEnum
except ImportError:
    pass

# 导入 MCP Core 和 Registry
from maa_mcp.core import mcp, controller_info_registry, ControllerType, ControllerInfo
from maa_mcp.paths import get_resource_dir, get_screenshots_dir

# 导入功能模块以注册基础工具
import maa_mcp.adb
import maa_mcp.win32
import maa_mcp.vision
import maa_mcp.control
import maa_mcp.utils
import maa_mcp.resource

# ==================== 日志配置 ====================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("PipelineServer")

# ==================== Win32 映射配置 ====================

_SCREENCAP_METHOD_MAP = {
    "FramePool": MaaWin32ScreencapMethodEnum.FramePool,
    "PrintWindow": MaaWin32ScreencapMethodEnum.PrintWindow,
    "GDI": MaaWin32ScreencapMethodEnum.GDI,
    "DXGI_DesktopDup_Window": MaaWin32ScreencapMethodEnum.DXGI_DesktopDup_Window,
    "ScreenDC": MaaWin32ScreencapMethodEnum.ScreenDC,
    "DXGI_DesktopDup": MaaWin32ScreencapMethodEnum.DXGI_DesktopDup,
}

_MOUSE_METHOD_MAP = {
    "PostMessage": MaaWin32InputMethodEnum.PostMessage,
    "PostMessageWithCursorPos": MaaWin32InputMethodEnum.PostMessageWithCursorPos,
    "Seize": MaaWin32InputMethodEnum.Seize,
}

_KEYBOARD_METHOD_MAP = {
    "PostMessage": MaaWin32InputMethodEnum.PostMessage,
    "Seize": MaaWin32InputMethodEnum.Seize,
}

# ==================== 配置 ====================


@dataclass
class PipelineConfig:
    """流水线配置"""

    screenshot_fps: float = 2.0  # 截图帧率
    message_queue_size: int = 100  # 消息队列大小
    similarity_threshold: int = 5  # 图像相似度阈值
    enable_dedup: bool = True  # 启用消息去重


# ==================== MAA 工具接口 ====================


class IMaaTool:
    """MAA 工具接口"""

    def screencap(self, controller_id: str) -> Optional[str]: ...
    def ocr(self, controller_id: str) -> List[Dict]: ...
    def click(self, controller_id: str, x: int, y: int, duration: int = 50) -> bool: ...
    def input_text(self, controller_id: str, text: str) -> bool: ...


# ==================== 真实 MAA 工具 ====================


class RealMAATool(IMaaTool):
    """
    真实 MAA 工具实现
    在子进程中重新连接设备并执行操作
    """

    def __init__(self, controller_type: ControllerType, params: dict):
        self.logger = logging.getLogger("RealMAA")
        self.controller = None
        self.tasker = None
        self.resource = None

        self.logger.info(f"初始化真实 MAA 工具: {controller_type}, 参数: {params}")

        try:
            if controller_type == ControllerType.ADB:
                self.controller = AdbController(
                    adb_path=params.get("adb_path"),
                    address=params.get("address"),
                    screencap_methods=params.get("screencap_methods", 0),
                    input_methods=params.get("input_methods", 0),
                    config=params.get("config", "{}"),
                )

            elif controller_type == ControllerType.WIN32:
                hwnd = params.get("hwnd")
                screencap = _SCREENCAP_METHOD_MAP.get(
                    params.get("screencap_method"),
                    MaaWin32ScreencapMethodEnum.FramePool,
                )
                mouse = _MOUSE_METHOD_MAP.get(
                    params.get("mouse_method"), MaaWin32InputMethodEnum.PostMessage
                )
                keyboard = _KEYBOARD_METHOD_MAP.get(
                    params.get("keyboard_method"), MaaWin32InputMethodEnum.PostMessage
                )

                self.controller = Win32Controller(
                    hwnd=hwnd,
                    screencap_method=screencap,
                    mouse_method=mouse,
                    keyboard_method=keyboard,
                )

            if self.controller:
                self.controller.post_connection().wait()

                # 初始化资源
                self.resource = Resource()
                res_path = get_resource_dir()
                self.resource.post_bundle(str(res_path)).wait()

                # 初始化 Tasker
                self.tasker = Tasker()
                self.tasker.bind(self.resource, self.controller)

        except Exception as e:
            self.logger.error(f"MAA 初始化失败: {e}")
            import traceback

            traceback.print_exc()

    def screencap(self, controller_id: str) -> Optional[str]:
        if not self.controller:
            return None
        try:
            image = self.controller.post_screencap().wait().get()
            if image is None:
                return None

            import cv2

            temp_dir = get_screenshots_dir()
            temp_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filepath = temp_dir / f"pipeline_{timestamp}.png"
            cv2.imwrite(str(filepath), image)
            return str(filepath)
        except Exception as e:
            self.logger.error(f"截图失败: {e}")
            return None

    def ocr(self, controller_id: str) -> List[Dict]:
        if not self.tasker:
            return []
        try:
            # 获取截图用于 OCR
            image = self.controller.post_screencap().wait().get()
            if image is None:
                return []

            info = (
                self.tasker.post_recognition(JRecognitionType.OCR, JOCR(), image)
                .wait()
                .get()
            )
            if not info or not info.nodes:
                return []

            results = []
            for result in info.nodes[0].recognition.all_results:
                # 转换 OCR 结果为简单字典
                results.append(
                    {
                        "text": result.text,
                        "x": result.rect.x,
                        "y": result.rect.y,
                        "w": result.rect.width,
                        "h": result.rect.height,
                        # 如果有 score 字段则添加
                        "score": getattr(result, "score", 0.99),
                    }
                )
            return results
        except Exception as e:
            self.logger.error(f"OCR 失败: {e}")
            return []

    def click(self, controller_id: str, x: int, y: int, duration: int = 50) -> bool:
        if not self.controller:
            return False
        try:
            self.controller.post_click(x, y).wait()
            return True
        except Exception as e:
            self.logger.error(f"点击失败: {e}")
            return False

    def input_text(self, controller_id: str, text: str) -> bool:
        if not self.controller:
            return False
        try:
            self.controller.post_input_text(text).wait()
            return True
        except Exception as e:
            self.logger.error(f"输入失败: {e}")
            return False


# ==================== 模拟 MAA 工具 ====================


class MockMAATool(IMaaTool):
    """
    模拟 MAA 工具（用于测试）
    """

    def __init__(self):
        self.logger = logging.getLogger("MockMAA")
        self._frame_count = 0
        self._message_templates = [
            "你好",
            "在吗？",
            "今天天气真好",
            "有什么新消息吗",
            "帮我查一下",
            "谢谢",
            "好的",
            "收到",
        ]

    def screencap(self, controller_id: str) -> Optional[str]:
        self._frame_count += 1
        temp_dir = Path("./temp_screenshots")
        temp_dir.mkdir(exist_ok=True)
        filepath = temp_dir / f"frame_{self._frame_count}.png"
        filepath.write_text(f"mock_frame_{self._frame_count}")
        return str(filepath)

    def ocr(self, controller_id: str) -> List[Dict]:
        import random

        results = []
        results.append({"text": "微信", "x": 540, "y": 50, "score": 0.99})
        results.append({"text": "发送", "x": 950, "y": 1800, "score": 0.98})
        if random.random() < 0.3:
            msg = random.choice(self._message_templates)
            results.append(
                {
                    "text": f"{msg}_{int(time.time()) % 1000}",
                    "x": 200,
                    "y": random.randint(300, 1500),
                    "score": 0.95,
                }
            )
        return results

    def click(self, controller_id: str, x: int, y: int, duration: int = 50) -> bool:
        msg = f"点击: ({x}, {y})"
        self.logger.info(msg)
        # print(f"[MockMAA] {msg}")
        time.sleep(duration / 1000)
        return True

    def input_text(self, controller_id: str, text: str) -> bool:
        msg = f"输入: {text}"
        self.logger.info(msg)
        # print(f"[MockMAA] {msg}")
        time.sleep(0.1)
        return True


# ==================== 流水线状态管理 ====================


class PipelineState:
    """流水线全局状态（单例，线程版）"""

    _instance = None
    _lock = Lock()  # 类属性：全局共享锁

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.is_running = False
        self.stop_event = Event()
        self.pipeline_thread: Optional[threading.Thread] = None
        self.message_queue = Queue(maxsize=100)
        self.stats_dict = {}
        self.last_screen_state = {}
        self.controller_id: Optional[str] = None
        self.reset()

    def reset(self):
        with PipelineState._lock:
            self.is_running = False
            self.stop_event.clear()
            temp_queue = Queue(maxsize=100)
            while not self.message_queue.empty():
                try:
                    temp_queue.put_nowait(self.message_queue.get_nowait())
                except Empty:
                    break
            self.message_queue = temp_queue  # 清空队列
            self.stats_dict = {
                "frame_count": 0,
                "ocr_count": 0,
                "new_message_count": 0,
                "start_time": 0,
                "last_update": 0,
            }
            self.last_screen_state = {}


# 懒加载全局状态
pipeline_state = None


def get_pipeline_state() -> PipelineState:
    global pipeline_state
    if pipeline_state is None:
        pipeline_state = PipelineState()
    return pipeline_state


# ==================== 流水线核心逻辑 ====================


def run_pipeline_loop(
    controller_id: str,
    controller_type: Optional[str],
    shared_controller,  # 新增：共享 controller
    shared_tasker,  # 新增：共享 tasker
    config_dict: Dict,
    stop_event: Event,
    message_queue: Queue,
    stats_dict: Dict,
    last_screen_state: Dict,
):
    """流水线主循环（线程版，共享 MAA 实例）"""
    from maa_mcp.core import PipelineState  # 访问 lock

    pipeline_state = get_pipeline_state()
    thread_logger = logging.getLogger("PipelineLoop")
    thread_logger.info(f"流水线线程启动，控制器: {controller_id}")

    # 使用共享实例，无需重建
    if controller_id == "test_device":
        thread_logger.info("使用 MockMAA 工具")
        maa_tool = MockMAATool()
    else:
        thread_logger.info("使用共享 RealMAA 组件")

        # maa_tool 封装共享调用
        class SharedMAATool:
            def __init__(self, controller, tasker):
                self.controller = controller
                self.tasker = tasker
                self.lock = Lock()  # 每个调用加锁

            def ocr(self, cid):
                with self.lock:
                    try:
                        image = self.controller.post_screencap().wait().get()
                        if image is None:
                            return []
                        info = (
                            self.tasker.post_recognition(
                                JRecognitionType.OCR, JOCR(), image
                            )
                            .wait()
                            .get()
                        )
                        if not info or not info.nodes:
                            return []
                        results = []
                        for result in info.nodes[0].recognition.all_results:
                            results.append(
                                {
                                    "text": result.text,
                                    "x": result.rect.x,
                                    "y": result.rect.y,
                                    "w": result.rect.width,
                                    "h": result.rect.height,
                                    "score": getattr(result, "score", 0.99),
                                }
                            )
                        return results
                    except Exception as e:
                        thread_logger.error(f"OCR 失败: {e}")
                        return []

        maa_tool = SharedMAATool(shared_controller, shared_tasker)

    fps = config_dict.get("fps", 2.0)
    enable_dedup = config_dict.get("enable_dedup", True)
    last_texts = set()
    frame_count = 0
    interval = 1.0 / fps

    while not stop_event.is_set():
        try:
            loop_start = time.time()
            frame_count += 1

            ocr_results = maa_tool.ocr(controller_id)
            if not ocr_results:
                time.sleep(interval)
                continue

            # 提取文本等逻辑不变
            current_texts = set()
            text_details = {}
            for item in ocr_results:
                text = item.get("text", "")
                if text:
                    current_texts.add(text)
                    text_details[text] = item

            if enable_dedup:
                new_texts = current_texts - last_texts
            else:
                new_texts = current_texts

            ui_elements = {"微信", "发送", "输入", "语音", "表情", "更多"}
            new_texts = {t for t in new_texts if not any(ui in t for ui in ui_elements)}

            for text in new_texts:
                item = text_details.get(text, {})
                message_data = {
                    "text": text,
                    "x": item.get("x", 0),
                    "y": item.get("y", 0),
                    "score": item.get("score", 0),
                    "timestamp": time.time(),
                    "frame_id": frame_count,
                }
                try:
                    message_queue.put_nowait(message_data)
                    with pipeline_state._lock:
                        stats_dict["new_message_count"] = (
                            stats_dict.get("new_message_count", 0) + 1
                        )
                    thread_logger.info(f"🆕 新消息: {text}")
                except:
                    pass

            last_texts = current_texts
            with pipeline_state._lock:
                stats_dict["frame_count"] = frame_count
                stats_dict["ocr_count"] = stats_dict.get("ocr_count", 0) + 1
                stats_dict["last_update"] = time.time()
                last_screen_state["texts"] = list(current_texts)
                last_screen_state["timestamp"] = time.time()

            elapsed = time.time() - loop_start
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        except Exception as e:
            thread_logger.error(f"流水线异常: {e}")
            time.sleep(1)

    thread_logger.info("流水线线程已停止")


# ==================== MCP 工具实现 ====================


def _start_pipeline_impl(controller_id: str, fps: float = 2.0) -> str:
    """启动流水线实现"""
    try:
        pipeline_state = get_pipeline_state()
        if pipeline_state.is_running:
            return "⚠️ 流水线已经在运行中"

        # 获取控制器信息
        ctype_str = None
        cparams = None

        if controller_id != "test_device":
            info = controller_info_registry.get(controller_id)
            if not info:
                return f"❌ 未找到控制器: {controller_id}，请先连接设备"

            ctype_str = info.controller_type.name  # "ADB" or "WIN32"
            cparams = info.connection_params
            if not cparams:
                return f"❌ 控制器 {controller_id} 缺少连接参数，无法在后台进程重建"

        pipeline_state.reset()
        pipeline_state.controller_id = controller_id
        pipeline_state.stats_dict["start_time"] = time.time()

        logger.info(f"正在启动流水线进程, controller_id={controller_id}")

        pipeline_state.pipeline_process = Process(
            target=run_pipeline_loop,
            args=(
                controller_id,
                ctype_str,
                cparams,
                {"fps": fps, "enable_dedup": True},
                pipeline_state.stop_event,
                pipeline_state.message_queue,
                pipeline_state.stats_dict,
                pipeline_state.last_screen_state,
            ),
            daemon=True,
        )
        pipeline_state.pipeline_process.start()
        pipeline_state.is_running = True

        return f"✅ 流水线已启动 (PID: {pipeline_state.pipeline_process.pid})"
    except Exception as e:
        logger.exception("启动流水线失败")
        return f"❌ 启动流水线失败: {str(e)}"


def _stop_pipeline_impl() -> str:
    """停止流水线实现"""
    pipeline_state = get_pipeline_state()
    if not pipeline_state.is_running:
        return "⚠️ 流水线未在运行"

    pipeline_state.stop_event.set()
    if pipeline_state.pipeline_process:
        pipeline_state.pipeline_process.join(timeout=5)
        if pipeline_state.pipeline_process.is_alive():
            pipeline_state.pipeline_process.terminate()

    pipeline_state.is_running = False
    return "✅ 流水线已停止"


def _get_new_messages_impl(max_count: int = 10) -> List[Dict[str, Any]]:
    """获取消息实现"""
    pipeline_state = get_pipeline_state()
    messages = []
    for _ in range(max_count):
        try:
            messages.append(pipeline_state.message_queue.get_nowait())
        except Empty:
            break
    return messages


def _get_pipeline_status_impl() -> Dict[str, Any]:
    """获取状态实现（线程版）"""
    pipeline_state = get_pipeline_state()
    with PipelineState._lock:
        stats = dict(pipeline_state.stats_dict)
    start_time = stats.get("start_time", 0)
    uptime = time.time() - start_time if start_time > 0 else 0
    return {
        "is_running": pipeline_state.is_running,
        "controller_id": pipeline_state.controller_id,
        "uptime": round(uptime, 1),
        "frame_count": stats.get("frame_count", 0),
        "new_messages": stats.get("new_message_count", 0),
        "pending": pipeline_state.message_queue.qsize(),
    }


def _pipeline_send_reply_impl(text: str) -> bool:
    """发送回复实现"""
    pipeline_state = get_pipeline_state()
    if not pipeline_state.controller_id:
        return False

    cid = pipeline_state.controller_id

    if cid == "test_device":
        tool = MockMAATool()
        tool.click(cid, 540, 1700)
        tool.input_text(cid, text)
        tool.click(cid, 950, 1800)
        return True

    try:
        from maa_mcp.control import click, input_text

        click(cid, 540, 1700)
        time.sleep(0.3)
        input_text(cid, text)
        time.sleep(0.2)
        click(cid, 950, 1800)
        return True
    except Exception as e:
        logger.error(f"发送回复失败: {e}")
        return False


# ==================== MCP 工具注册 ====================


@mcp.tool()
def start_pipeline(controller_id: str, fps: float = 2.0) -> str:
    """
    启动后台监控流水线。

    Args:
        controller_id: 设备控制器ID (需先连接设备)
        fps: 截图帧率（默认2.0）
    """
    return _start_pipeline_impl(controller_id, fps)


@mcp.tool()
def stop_pipeline() -> str:
    """停止后台监控流水线。"""
    return _stop_pipeline_impl()


@mcp.tool()
def get_new_messages(max_count: int = 10) -> List[Dict[str, Any]]:
    """获取新检测到的消息（非阻塞）。"""
    return _get_new_messages_impl(max_count)


@mcp.tool()
def get_pipeline_status() -> Dict[str, Any]:
    """获取流水线运行状态。"""
    return _get_pipeline_status_impl()


@mcp.tool()
def pipeline_send_reply(text: str) -> bool:
    """
    (流水线专用) 发送回复消息。
    使用当前流水线绑定的控制器发送消息。
    """
    return _pipeline_send_reply_impl(text)


# ==================== 测试与主入口 ====================


def run_test():
    """运行本地测试"""
    print("=" * 60)
    print("🧪 流水线本地测试 (使用 MockMAA)")
    print("=" * 60)

    _start_pipeline_impl("test_device", fps=2.0)

    print("运行中 (10s)...")
    for _ in range(10):
        time.sleep(1)
        msgs = _get_new_messages_impl()
        if msgs:
            for m in msgs:
                print(f"📩 [{m['timestamp']}] {m['text']}")

    print("发送回复测试...")
    _pipeline_send_reply_impl("Test Reply")

    _stop_pipeline_impl()
    print("测试完成")


def main():
    parser = argparse.ArgumentParser(description="MaaMCP Pipeline Server")
    parser.add_argument("--test", action="store_true", help="运行本地测试")
    args = parser.parse_args()

    if args.test:
        run_test()
    else:
        # 启动 MCP 服务器
        mcp.run()


if __name__ == "__main__":
    main()
