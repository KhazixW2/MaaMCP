import atexit
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from maa.toolkit import Toolkit

from fastmcp import FastMCP

from maa_mcp import __version__
from maa_mcp.registry import ObjectRegistry
from maa_mcp.paths import get_data_dir, ensure_dirs


# 确保所有必要的目录存在并初始化 MaaFramework
ensure_dirs()
Toolkit.init_option(get_data_dir(), {"stdout_level": 0})


class ControllerType(Enum):
    """控制器类型枚举"""

    ADB = auto()
    WIN32 = auto()


@dataclass
class ControllerInfo:
    """控制器信息，用于记录控制器类型和配置"""

    controller_type: ControllerType
    # 连接参数，用于在子进程中重建控制器
    connection_params: dict
    # Win32 专用：键盘输入方式
    keyboard_method: Optional[str] = None


# 全局对象注册表
object_registry = ObjectRegistry()
# 控制器信息注册表：controller_id -> ControllerInfo
controller_info_registry: dict[str, ControllerInfo] = {}

# 记录当前会话保存的截图文件路径，用于退出时清理
_saved_screenshots: list[Path] = []

mcp = FastMCP(
    "MaaMCP",
    version=__version__,
    instructions="""
    MaaMCP 是一个基于 MaaFramewok 框架的 Model Context Protocol 服务，
    提供 Android 设备、Windows 桌面自动化控制能力，支持通过 ADB 连接模拟器或真机，通过窗口句柄连接 Windows 桌面，
    实现屏幕截图、光学字符识别（OCR）、坐标点击、手势滑动、按键点击、输入文本等自动化操作。

    ⭐ 多设备/多窗口协同支持：
    - 可同时连接多个 ADB 设备和/或多个 Windows 窗口
    - 每个设备/窗口拥有独立的控制器 ID（controller_id）
    - 通过在操作时指定不同的 controller_id 实现多设备协同自动化

    ⭐ 双模式运行支持：
    - 串行模式（流程 1 + 2）：传统的同步执行方式，一个指令完成后再执行下一个
    - 流水线模式（流程 1 + 3）：多线程异步执行方式，后台持续采集屏幕信息，主线程专注于决策和操作

    ========================
    标准工作流程
    ========================

    1. 设备/窗口发现与连接（必选，两种模式通用）
       - 调用 find_adb_device_list() 扫描可用的 ADB 设备
       - 调用 find_window_list() 扫描可用的 Windows 窗口
       - 若发现多个设备/窗口，需向用户展示列表并等待用户选择需要操作的目标
       - 使用 connect_adb_device(device_name) 或 connect_window(window_name) 建立连接
       - 可连接多个设备/窗口，每个连接返回独立的控制器 ID

    2. 串行自动化执行循环（流程 1 之后选择此流程进入串行模式）
       - 调用 ocr(controller_id) 对指定设备进行屏幕截图和 OCR 识别
       - 首次使用时，如果 OCR 模型文件不存在, ocr() 会返回提示信息，需要调用 check_and_download_ocr() 下载资源
       - 下载完成后即可正常使用 OCR 功能，后续调用无需再次下载
       - 根据识别结果调用 click()、double_click()、scroll()、swipe() 等执行相应操作
       - 所有操作通过 controller_id 指定目标设备/窗口
       - 可在多个设备间切换操作，实现协同自动化
       - 特点：每次操作需等待 OCR 完成，适合简单任务或对实时性要求不高的场景

    3. 流水线自动化执行（流程 1 之后选择此流程进入多线程流水线模式）
       ⭐ 适用场景：需要高频屏幕监控、实时响应的自动化任务

       3.1 启动流水线
           - 调用 start_pipeline(controller_id) 启动指定控制器的流水线
           - 流水线会在后台启动独立线程，按固定频率自动截图并缓存图片路径
           - 截图路径会自动推送到消息队列中
           - 启动流水线后，等待约 1 秒让流水线进行初始缓存

       3.2 获取流水线状态和截图
           - 调用 get_pipeline_status() 检测流水线运行状态和待处理消息数量
           - 如果有新消息，调用 get_new_messages() 获取最新的截图路径
           - 消息包含 type（固定为 "screenshot"）、image_path（截图文件路径）、timestamp、frame_id

       3.3 分析截图并执行操作
           - 读取 image_path 中的图片内容，进行视觉分析
           - 根据图片内容判断是否需要执行 OCR（调用 ocr 工具获取文字信息）
           - 根据分析结果调用 click()、double_click()、scroll()、swipe() 等执行相应操作
           - 所有操作通过 controller_id 指定目标设备/窗口
           - 可在多个设备间切换操作，实现协同自动化
           - 操作完成后继续循环 3.2 和 3.3，直到任务完成

       3.4 停止流水线
           - 任务完成后，调用 stop_pipeline() 停止流水线
           - 释放后台线程资源

       流水线模式优势：
           - 后台持续截图，大模型可直接查看完整画面进行决策
           - 大模型可根据图片内容自行决定是否需要 OCR、具体 OCR 哪个区域
           - 支持高频屏幕监控，不错过任何界面变化
           - 适合需要快速响应的实时自动化任务
           - 消息队列机制，支持异步处理和历史数据查询

    ========================
    屏幕识别策略（重要）
    ========================

    - 优先使用 OCR：始终优先调用 ocr() 进行文字识别，OCR 返回结构化文本数据，token 消耗极低
    - 按需使用截图：仅当以下情况时，才调用 screencap() 获取截图，再通过 read_file 读取图片进行视觉识别：
      1. OCR 结果不足以做出决策（如需要识别图标、图像、颜色、布局等非文字信息）
      2. 反复 OCR + 操作后界面状态无预期变化，可能存在弹窗、遮挡或其他视觉异常需要人工判断
    - 图片识别会消耗大量 token，应尽量避免频繁调用

    滚动/翻页策略（重要）：
    - ADB（Android 设备/模拟器）：优先使用 swipe() 实现页面滚动/列表翻动（scroll() 不支持 ADB）
    - Windows（桌面窗口）：优先使用 scroll() 实现列表/页面滚动（更符合鼠标滚轮语义）；仅在需要“拖拽/滑动手势”时才使用 swipe()

    注意事项：
    - controller_id 为字符串类型，由系统自动生成并管理
    - 操作失败时函数返回 None 或 False，需进行错误处理
    - 多设备场景下必须等待用户明确选择，不得自动决策
    - 请妥善保存 controller_id，以便在多设备间切换操作

    Windows 窗口控制故障排除：
    若使用 connect_window() 连接窗口后出现异常，可尝试切换截图/输入方式（需重新连接）：

    截图异常（画面为空、纯黑、花屏等）：
      - 多尝试几次（2~3次）确认是否为偶发问题，不要一次失败就切换
      - 若持续异常，按优先级切换截图方式重新连接：
        FramePool → PrintWindow → GDI → DXGI_DesktopDup_Window → ScreenDC
      - 最后手段：DXGI_DesktopDup（截取整个桌面，触控坐标会不正确，仅用于排查问题）

    键鼠操作无响应（操作后界面无变化）：
      - 多尝试几次（2~3次）确认是否为偶发问题，不要一次失败就切换
      - 若持续无响应，按优先级切换输入方式重新连接：
        鼠标：PostMessage → PostMessageWithCursorPos → Seize
        键盘：PostMessage → Seize

    安全约束（重要）：
    - 所有 ADB、窗口句柄 相关操作必须且仅能通过本 MCP 提供的工具函数执行
    - 严禁在终端中直接执行 adb 命令（如 adb devices、adb shell 等）
    - 严禁在终端中直接执行窗口句柄相关命令（如 GetWindowText、GetWindowTextLength 等）
    - 严禁使用其他第三方库或方法与 ADB 设备或窗口句柄交互
    - 严禁绕过本 MCP 工具自行实现设备控制逻辑
    """,
)


def cleanup_screenshots():
    """清理当前会话保存的临时截图文件"""
    for filepath in _saved_screenshots:
        filepath.unlink(missing_ok=True)
    _saved_screenshots.clear()


atexit.register(cleanup_screenshots)
