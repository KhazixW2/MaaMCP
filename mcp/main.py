import sys
import importlib.util
from pathlib import Path
from typing import Optional, Union

# 先导入 FastMCP，避免与项目中的 mcp 目录产生命名冲突
from fastmcp import FastMCP

# 处理直接运行时的路径问题
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from maa.toolkit import Toolkit
from maa.controller import AdbController
from maa.resource import Resource
from maa.tasker import Tasker, TaskDetail
from maa.pipeline import JRecognitionType, JOCR

# 动态导入 registry 模块，避免命名冲突
if __name__ == "__main__":
    # 直接运行时，使用 importlib 动态加载
    registry_path = Path(__file__).parent / "registry.py"
    spec = importlib.util.spec_from_file_location("mcp.registry", registry_path)
    registry_module = importlib.util.module_from_spec(spec)
    sys.modules["mcp.registry"] = registry_module
    spec.loader.exec_module(registry_module)
    object_registry = registry_module.object_registry
else:
    # 作为模块导入时，使用相对导入
    from .registry import object_registry

mcp = FastMCP(
    "MAA MCP",
    version="1.0.0",
    instructions="""
    MAA MCP 是一个基于 MaaFramewok 框架的 Model Context Protocol 服务，
    提供 Android 设备自动化控制能力，支持通过 ADB 连接模拟器或真机，实现屏幕截图、
    光学字符识别（OCR）、坐标点击、手势滑动等自动化操作。

    标准工作流程：
    1. 设备发现与连接
       - 调用 find_adb_device_list() 扫描可用的 ADB 设备
       - 若发现多个设备，必须暂停执行并询问用户选择目标设备（禁止自动选择）
       - 使用 connect_adb_device(device_name) 建立设备连接，获取控制器 ID

    2. 资源初始化
       - 调用 load_resource(resource_path) 加载资源包
       - 资源路径应指向包含 resource/model/*.onnx 的目录（通常为项目 assets/resource 目录）
       - 加载前需验证路径存在性，缺失时提示用户配置资源文件

    3. 任务管理器创建
       - 调用 create_tasker(controller_id, resource_id) 创建任务管理器实例
       - 将控制器与资源绑定，获取任务管理器 ID

    4. 自动化执行循环
       - 调用 ocr(tasker_id) 进行屏幕截图并执行 OCR 识别
       - 根据识别结果调用 click() 或 swipe() 执行相应操作
       - 重复执行步骤 4，直至任务完成

    注意事项：
    - 所有 ID 均为字符串类型，由系统自动生成并管理
    - 操作失败时函数返回 None 或 False，需进行错误处理
    - 多设备场景下必须等待用户明确选择，不得自动决策

    安全约束（重要）：
    - 所有 ADB 相关操作必须且仅能通过本 MCP 提供的工具函数执行
    - 严禁在终端中直接执行 adb 命令（如 adb devices、adb shell 等）
    - 严禁使用其他第三方库或方法与 ADB 设备交互
    - 严禁绕过本 MCP 工具自行实现设备控制逻辑
    """,
)

Toolkit.init_option(Path(__file__).parent)


@mcp.tool(
    name="find_adb_device_list",
    description="""
    扫描并枚举当前系统中所有可用的 ADB 设备。

    返回值类型：
    - 无设备：返回空列表 []
    - 单个设备：返回设备名称字符串，可直接用于连接
    - 多个设备：返回字典格式 {"devices": [设备名称列表], "message": "找到多个设备，请询问用户选择哪个设备"}

    重要约束：
    当返回值为字典类型时，必须立即暂停执行流程，向用户展示设备列表并等待用户明确选择。
    严禁在未获得用户确认的情况下自动选择设备。
""",
)
def find_adb_device_list() -> Union[list[str], str, dict]:
    device_list = Toolkit.find_adb_devices()
    for device in device_list:
        object_registry.register_by_name(device.name, device)
    
    device_names = [device.name for device in device_list]
    
    if len(device_names) == 0:
        return []
    elif len(device_names) == 1:
        return device_names[0]
    else:
        return {
            "devices": device_names,
            "message": "找到多个设备，请询问用户选择哪个设备，不能自动选择。"
        }


@mcp.tool(
    name="connect_adb_device",
    description="""
    建立与指定 ADB 设备的连接，创建控制器实例。

    参数：
    - device_name: 目标设备名称，需通过 find_adb_device_list() 获取

    返回值：
    - 成功：返回控制器 ID（字符串），用于后续所有设备操作
    - 失败：返回 None

    说明：
    控制器 ID 将用于后续的点击、滑动、截图等操作，请妥善保存。
""",
)
def connect_adb_device(device_name: str) -> Optional[str]:
    device = object_registry.get(device_name)
    if not device:
        return None

    adb_controller = AdbController(
        device.adb_path,
        device.address,
        device.screencap_methods,
        device.input_methods,
        device.config,
    )
    if not adb_controller.post_connection().wait().succeeded:
        return None
    return object_registry.register(adb_controller)


@mcp.tool(
    name="load_resource",
    description="""
    加载 MAA 资源包，包含 OCR 模型、图像模板等自动化所需资源。

    参数：
    - resource_path: 资源包根目录路径（字符串）
      - 路径应指向包含 resource/model/*.onnx 的目录层级
      - 典型路径示例：项目根目录下的 assets/resource
      - 传入路径为 resource 这一级目录，而非其子目录

    返回值：
    - 成功：返回资源 ID（字符串），用于创建任务管理器
    - 失败：返回 None（路径不存在或资源加载失败）

    前置检查：
    调用前应验证路径存在性，若路径不存在，需提示用户先配置资源文件。
""",
)
def load_resource(resource_path: str) -> Optional[str]:
    if not Path(resource_path).exists():
        return None
    resource = Resource()
    if not resource.post_bundle(resource_path).wait().succeeded:
        return None
    return object_registry.register(resource)


@mcp.tool(
    name="create_tasker",
    description="""
    创建任务管理器实例，将控制器与资源进行绑定，用于执行自动化任务。

    参数：
    - controller_id: 控制器 ID，由 connect_adb_device() 返回
    - resource_id: 资源 ID，由 load_resource() 返回

    返回值：
    - 成功：返回任务管理器 ID（字符串），用于后续 OCR 识别等操作
    - 失败：返回 None（控制器或资源无效，或绑定失败）

    说明：
    任务管理器是执行 OCR 识别等自动化操作的核心组件，需确保控制器和资源均已成功初始化。
""",
)
def create_tasker(controller_id: str, resource_id: str) -> Optional[str]:
    controller = object_registry.get(controller_id)
    resource = object_registry.get(resource_id)
    if not controller or not resource:
        return None
    tasker = Tasker()
    tasker.bind(resource, controller)
    if not tasker.inited:
        return None

    return object_registry.register(tasker)


@mcp.tool(
    name="ocr",
    description="""
    对当前设备屏幕进行截图，并执行光学字符识别（OCR）处理。

    参数：
    - tasker_id: 任务管理器 ID，由 create_tasker() 返回

    返回值：
    - 成功：返回识别结果字符串，包含识别到的文字、坐标信息、置信度等结构化数据
    - 失败：返回 None（截图失败或 OCR 识别失败）

    说明：
    识别结果可用于后续的坐标定位和自动化决策，通常包含文本内容、边界框坐标、置信度评分等信息。
""",
)
def ocr(tasker_id: str) -> Optional[str]:
    tasker: Tasker | None = object_registry.get(tasker_id)
    if not tasker:
        return None

    image = tasker.controller.post_screencap().wait().get()
    info: TaskDetail | None = (
        tasker.post_recognition(JRecognitionType.OCR, JOCR(), image).wait().get()
    )
    if not info:
        return None
    return info.nodes[0].recognition.all_results


@mcp.tool(
    name="click",
    description="""
    在设备屏幕上执行单点点击操作。

    参数：
    - controller_id: 控制器 ID，由 connect_adb_device() 返回
    - x: 目标点的 X 坐标（像素，整数）
    - y: 目标点的 Y 坐标（像素，整数）

    返回值：
    - 成功：返回 True
    - 失败：返回 False

    说明：
    坐标系统以屏幕左上角为原点 (0, 0)，X 轴向右，Y 轴向下。
""",
)
def click(controller_id: str, x: int, y: int) -> bool:
    controller = object_registry.get(controller_id)
    if not controller:
        return False
    return controller.post_click(x, y).wait().succeeded


@mcp.tool(
    name="swipe",
    description="""
    在设备屏幕上执行手势滑动操作，模拟手指从起始点滑动到终点。

    参数：
    - controller_id: 控制器 ID，由 connect_adb_device() 返回
    - start_x: 起始点的 X 坐标（像素，整数）
    - start_y: 起始点的 Y 坐标（像素，整数）
    - end_x: 终点的 X 坐标（像素，整数）
    - end_y: 终点的 Y 坐标（像素，整数）
    - duration: 滑动持续时间（毫秒，整数）

    返回值：
    - 成功：返回 True
    - 失败：返回 False

    说明：
    坐标系统以屏幕左上角为原点 (0, 0)。duration 参数控制滑动速度，数值越大滑动越慢。
""",
)
def swipe(
    controller_id: str,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: int,
) -> bool:
    controller = object_registry.get(controller_id)
    if not controller:
        return False
    return (
        controller.post_swipe(start_x, start_y, end_x, end_y, duration).wait().succeeded
    )


if __name__ == "__main__":
    mcp.run()
