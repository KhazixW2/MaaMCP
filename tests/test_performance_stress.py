"""压力测试 - 测量关键函数在高负载下的性能表现"""

import time
import pytest
from typing import Callable, Any, Optional, List, Dict

from maa_mcp.vision import ocr, screencap
from maa_mcp.control import click, swipe, input_text, click_key, scroll, double_click
from maa_mcp.core import controller_info_registry, ControllerType
from maa_mcp.adb import find_adb_device_list, connect_adb_device
from maa_mcp.win32 import find_window_list, connect_window


class PerformanceTimer:
    """性能计时器，用于测量函数执行时间"""

    def __init__(self):
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.elapsed_time: Optional[float] = None

    def start(self):
        """开始计时"""
        self.start_time = time.perf_counter()
        self.end_time = None
        self.elapsed_time = None

    def stop(self):
        """停止计时"""
        if self.start_time is not None:
            self.end_time = time.perf_counter()
            self.elapsed_time = self.end_time - self.start_time

    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.stop()


class PerformanceTestResult:
    """性能测试结果类"""

    def __init__(
        self,
        function_name: str,
        execution_time: float,
        success: bool,
        result: Any = None,
    ):
        self.function_name = function_name
        self.execution_time = execution_time
        self.success = success
        self.result = result

    def __str__(self):
        status = "成功" if self.success else "失败"
        return f"{self.function_name} - {status}, 耗时: {self.execution_time:.4f}秒"


class PerformanceBenchmarker:
    """性能基准测试工具，用于批量测试函数性能"""

    def __init__(self):
        self.results: List[PerformanceTestResult] = []

    def benchmark(self, func: Callable, *args, **kwargs) -> PerformanceTestResult:
        """执行单次性能测试"""
        timer = PerformanceTimer()
        success = False
        result = None

        try:
            timer.start()
            result = func(*args, **kwargs)
            timer.stop()
            success = True
        except Exception as e:
            timer.stop()
            print(f"[Error] {func.__name__} 执行失败: {e}")

        test_result = PerformanceTestResult(
            function_name=func.__name__,
            execution_time=timer.elapsed_time or 0,
            success=success,
            result=result,
        )

        self.results.append(test_result)
        return test_result

    def run_multiple(
        self,
        func: Callable,
        iterations: int = 5,
        print_stats: bool = True,
        *args,
        **kwargs,
    ) -> List[PerformanceTestResult]:
        """多次执行性能测试，获取平均时间"""
        test_results = []

        total_start_time = time.perf_counter()
        last_print_time = 0

        for i in range(iterations):
            # 使用\r实现同一行滚动显示进度，限制刷新频率避免拖慢速度
            current_time = time.perf_counter()
            if iterations > 1 and print_stats:
                # 每0.1秒或最后一次才刷新
                if current_time - last_print_time > 0.1 or i == iterations - 1:
                    print(
                        f"\r[Iteration {i+1}/{iterations}] - 进行中...",
                        end="",
                        flush=True,
                    )
                    last_print_time = current_time

            result = self.benchmark(func, *args, **kwargs)
            test_results.append(result)

        total_end_time = time.perf_counter()
        total_wall_time = total_end_time - total_start_time

        # 完成后换行
        if iterations > 1 and print_stats:
            print()

        # 计算统计信息
        if test_results and print_stats:
            success_times = [r.execution_time for r in test_results if r.success]
            if success_times:
                avg_time = sum(success_times) / len(success_times)
                max_time = max(success_times)
                min_time = min(success_times)
                total_execution_time = sum(success_times)

                print(f"\n[Statistics] {func.__name__}")
                print(f"  平均时间: {avg_time:.4f} 秒")
                print(f"  最大时间: {max_time:.4f} 秒")
                print(f"  最小时间: {min_time:.4f} 秒")
                print(f"  成功率: {len(success_times)}/{iterations}")
                print(f"  总执行耗时 (Sum): {total_execution_time:.4f} 秒")
                print(f"  总墙钟耗时 (Wall): {total_wall_time:.4f} 秒")
                if total_wall_time > total_execution_time * 1.1:
                    print(f"  注意: 墙钟时间显著大于执行时间，可能存在系统开销或IO等待")

        return test_results

    def print_summary(self):
        """打印所有测试结果摘要"""
        print("\n" + "=" * 50)
        print("性能测试结果摘要")
        print("=" * 50)

        for result in self.results:
            print(result)

        # 统计总览
        total_tests = len(self.results)
        successful_tests = sum(1 for r in self.results if r.success)
        avg_time_all = (
            sum(r.execution_time for r in self.results if r.success) / successful_tests
            if successful_tests
            else 0
        )

        print(f"\n总览: {successful_tests}/{total_tests} 个测试成功")
        if successful_tests:
            print(f"平均执行时间: {avg_time_all:.4f} 秒")
        print("=" * 50)


class StressTestConfig:
    """压力测试配置类"""

    def __init__(self):
        self.iterations = 10  # 默认执行1000次
        self.warmup_iterations = 10  # 预热迭代次数
        self.timeout = 30.0  # 单个测试超时时间（秒）


class MockController:
    """模拟控制器类，用于模拟设备/窗口控制器的基本功能"""

    def __init__(self):
        self.controller_id = "mock_controller"

    def post_screencap(self):
        """模拟截图操作"""
        time.sleep(0.001)  # 模拟截图延迟
        return self

    def wait(self):
        """模拟等待操作"""
        return self

    def get(self):
        """模拟获取结果"""
        return b"mock_image_data"  # 返回模拟的图片数据

    def post_touch_down(self, x, y, contact=0):
        """模拟触摸按下操作"""
        time.sleep(0.001)
        return self

    def post_touch_up(self, contact=0):
        """模拟触摸抬起操作"""
        time.sleep(0.001)
        return self

    def post_swipe(self, start_x, start_y, end_x, end_y, duration):
        """模拟滑动操作"""
        time.sleep(duration / 1000.0 * 0.1)  # 模拟滑动延迟，实际时间的1/10
        return self

    def post_input_text(self, text):
        """模拟输入文本操作"""
        time.sleep(len(text) * 0.0005)  # 模拟输入每个字符的延迟
        return self

    def post_key_down(self, key):
        """模拟按键按下操作"""
        time.sleep(0.001)
        return self

    def post_key_up(self, key):
        """模拟按键抬起操作"""
        time.sleep(0.001)
        return self

    def post_scroll(self, x, y):
        """模拟滚动操作"""
        time.sleep(0.001)
        return self

    @property
    def succeeded(self):
        """模拟操作成功状态"""
        return True


class TestStressPerformance:
    """压力测试类 - 测试关键函数在高负载下的性能"""

    def setup_class(self):
        """测试类初始化，获取实际控制器"""
        self.config = StressTestConfig()
        self.benchmarker = PerformanceBenchmarker()
        self.controller_id = None
        self.device_name = None
        self.window_name = None

        # 尝试获取ADB设备
        try:
            device_list = find_adb_device_list.fn()
            if device_list:
                self.device_name = device_list[0]  # 使用第一个设备
                self.controller_id = connect_adb_device.fn(self.device_name)
                print(
                    f"  使用ADB设备: {self.device_name}, 控制器ID: {self.controller_id}"
                )
        except Exception as e:
            print(f"  获取ADB设备失败: {e}")

        # 如果没有ADB设备，尝试获取Windows窗口
        if not self.controller_id:
            try:
                window_list = find_window_list.fn()
                if window_list:
                    self.window_name = window_list[0]  # 使用第一个窗口
                    self.controller_id = connect_window.fn(self.window_name)
                    print(
                        f"  使用Windows窗口: {self.window_name}, 控制器ID: {self.controller_id}"
                    )
            except Exception as e:
                print(f"  获取Windows窗口失败: {e}")

        # 如果仍然没有控制器，将使用模拟数据
        if not self.controller_id:
            print("  未找到实际设备或窗口，部分测试将使用模拟数据")

    def test_stress_find_adb_device_list(self):
        """压力测试 - find_adb_device_list 函数"""
        print(f"\n=== 压力测试: find_adb_device_list ({self.config.iterations}次) ===")

        # 预热
        for _ in range(self.config.warmup_iterations):
            find_adb_device_list.fn()

        # 执行压力测试
        results = self.benchmarker.run_multiple(
            find_adb_device_list.fn,
            iterations=self.config.iterations,
            print_stats=False,
        )

        # 打印详细统计信息
        self._print_stress_test_stats(results, "find_adb_device_list")

    def test_stress_find_window_list(self):
        """压力测试 - find_window_list 函数"""
        print(f"\n=== 压力测试: find_window_list ({self.config.iterations}次) ===")

        # 预热
        for _ in range(self.config.warmup_iterations):
            find_window_list.fn()

        # 执行压力测试
        results = self.benchmarker.run_multiple(
            find_window_list.fn,
            iterations=self.config.iterations,
            print_stats=False,
        )

        # 打印详细统计信息
        self._print_stress_test_stats(results, "find_window_list")

    def test_stress_ocr(self):
        """压力测试 - OCR 函数"""
        print(f"\n=== 压力测试: ocr ({self.config.iterations}次) ===")

        if not self.controller_id:
            print("  没有有效的控制器ID，无法执行OCR测试")
            return

        # 预热
        for _ in range(self.config.warmup_iterations):
            ocr.fn(self.controller_id)

        # 执行压力测试
        results = self.benchmarker.run_multiple(
            ocr.fn,
            iterations=self.config.iterations,
            print_stats=False,
            controller_id=self.controller_id,
        )

        # 打印详细统计信息
        self._print_stress_test_stats(results, "ocr")

    def test_stress_screencap(self):
        """压力测试 - 截图函数"""
        print(f"\n=== 压力测试: screencap ({self.config.iterations}次) ===")

        if not self.controller_id:
            print("  没有有效的控制器ID，无法执行截图测试")
            return

        # 预热
        for _ in range(self.config.warmup_iterations):
            screencap.fn(self.controller_id)

        # 执行压力测试
        results = self.benchmarker.run_multiple(
            screencap.fn,
            iterations=self.config.iterations,
            print_stats=False,
            controller_id=self.controller_id,
        )

        # 打印详细统计信息
        self._print_stress_test_stats(results, "screencap")

    def test_stress_click(self):
        """压力测试 - 点击函数"""
        print(f"\n=== 压力测试: click ({self.config.iterations}次) ===")

        if not self.controller_id:
            print("  没有有效的控制器ID，无法执行点击测试")
            return

        # 预热
        for _ in range(self.config.warmup_iterations):
            click.fn(self.controller_id, 100, 100)

        # 执行压力测试
        results = self.benchmarker.run_multiple(
            click.fn,
            iterations=self.config.iterations,
            print_stats=False,
            controller_id=self.controller_id,
            x=100,
            y=100,
        )

        # 打印详细统计信息
        self._print_stress_test_stats(results, "click")

    def test_stress_swipe(self):
        """压力测试 - 滑动函数"""
        print(f"\n=== 压力测试: swipe ({self.config.iterations}次) ===")

        if not self.controller_id:
            print("  没有有效的控制器ID，无法执行滑动测试")
            return

        # 预热
        for _ in range(self.config.warmup_iterations):
            swipe.fn(self.controller_id, 100, 100, 200, 200, 500)

        # 执行压力测试
        results = self.benchmarker.run_multiple(
            swipe.fn,
            iterations=self.config.iterations,
            print_stats=False,
            controller_id=self.controller_id,
            start_x=100,
            start_y=100,
            end_x=200,
            end_y=200,
            duration=500,
        )

        # 打印详细统计信息
        self._print_stress_test_stats(results, "swipe")

    def test_stress_input_text(self):
        """压力测试 - 输入文本函数"""
        print(f"\n=== 压力测试: input_text ({self.config.iterations}次) ===")

        if not self.controller_id:
            print("  没有有效的控制器ID，无法执行输入文本测试")
            return

        # 预热
        for _ in range(self.config.warmup_iterations):
            input_text.fn(self.controller_id, "test")

        # 执行压力测试
        results = self.benchmarker.run_multiple(
            input_text.fn,
            iterations=self.config.iterations,
            print_stats=False,
            controller_id=self.controller_id,
            text="test",
        )

        # 打印详细统计信息
        self._print_stress_test_stats(results, "input_text")

    def test_stress_click_key(self):
        """压力测试 - 按键点击函数"""
        print(f"\n=== 压力测试: click_key ({self.config.iterations}次) ===")

        if not self.controller_id:
            print("  没有有效的控制器ID，无法执行按键点击测试")
            return

        # 预热
        for _ in range(self.config.warmup_iterations):
            click_key.fn(self.controller_id, 13)  # 13 是回车键的虚拟键码

        # 执行压力测试
        results = self.benchmarker.run_multiple(
            click_key.fn,
            iterations=self.config.iterations,
            print_stats=False,
            controller_id=self.controller_id,
            key=13,  # 13 是回车键的虚拟键码
        )

        # 打印详细统计信息
        self._print_stress_test_stats(results, "click_key")

    def test_stress_scroll(self):
        """压力测试 - 滚动函数"""
        print(f"\n=== 压力测试: scroll ({self.config.iterations}次) ===")

        if not self.controller_id:
            print("  没有有效的控制器ID，无法执行滚动测试")
            return

        # 检查是否为 ADB 控制器
        info = controller_info_registry.get(self.controller_id)
        if info and info.controller_type == ControllerType.ADB:
            print("  当前控制器为 ADB，跳过 scroll 压力测试 (仅支持 Windows)")
            return

        # 预热
        for _ in range(self.config.warmup_iterations):
            scroll.fn(self.controller_id, 0, -120)

        # 执行压力测试
        results = self.benchmarker.run_multiple(
            scroll.fn,
            iterations=self.config.iterations,
            print_stats=False,
            controller_id=self.controller_id,
            x=0,
            y=-120,
        )

        # 打印详细统计信息
        self._print_stress_test_stats(results, "scroll")

    def test_stress_double_click(self):
        """压力测试 - 双击函数"""
        print(f"\n=== 压力测试: double_click ({self.config.iterations}次) ===")

        if not self.controller_id:
            print("  没有有效的控制器ID，无法执行双击测试")
            return

        # 预热
        for _ in range(self.config.warmup_iterations):
            double_click.fn(self.controller_id, 100, 100)

        # 执行压力测试
        results = self.benchmarker.run_multiple(
            double_click.fn,
            iterations=self.config.iterations,
            print_stats=False,
            controller_id=self.controller_id,
            x=100,
            y=100,
        )

        # 打印详细统计信息
        self._print_stress_test_stats(results, "double_click")

    def _print_stress_test_stats(self, results: List, function_name: str):
        """打印压力测试的详细统计信息"""
        if not results:
            print(f"  未获取到测试结果")
            return

        # 筛选成功的测试结果
        success_results = [r for r in results if r.success]
        if not success_results:
            print(f"  所有测试都失败了")
            return

        # 计算统计数据
        execution_times = [r.execution_time for r in success_results]
        avg_time = sum(execution_times) / len(execution_times)
        min_time = min(execution_times)
        max_time = max(execution_times)
        median_time = sorted(execution_times)[len(execution_times) // 2]

        # 计算每秒处理次数（TPS）
        tps = len(success_results) / sum(execution_times)

        print(f"\n[压力测试统计] {function_name}")
        print(f"  总执行次数: {len(results)}")
        print(f"  成功次数: {len(success_results)}")
        print(f"  平均时间: {avg_time * 1000:.3f} 毫秒")
        print(f"  最小时间: {min_time * 1000:.3f} 毫秒")
        print(f"  最大时间: {max_time * 1000:.3f} 毫秒")
        print(f"  中位数时间: {median_time * 1000:.3f} 毫秒")
        print(f"  每秒处理次数 (TPS): {tps:.2f}")
        print(f"  总耗时: {sum(execution_times) * 1000:.2f} 毫秒")


# 性能测试接口 - 为关键函数添加性能测试装饰器
class PerformanceTestInterface:
    """性能测试接口类 - 提供性能测试的统一接口"""

    @staticmethod
    def measure_function_performance(
        func: Callable, iterations: int = 1000, *args, **kwargs
    ) -> Dict[str, Any]:
        """测量函数在指定次数迭代下的性能

        Args:
            func: 要测试的函数
            iterations: 迭代次数
            *args: 函数参数
            **kwargs: 函数关键字参数

        Returns:
            包含性能统计数据的字典
        """
        benchmarker = PerformanceBenchmarker()

        # 预热
        for _ in range(10):
            func(*args, **kwargs)

        # 执行测试
        results = benchmarker.run_multiple(func, iterations, *args, **kwargs)

        # 计算统计数据
        success_results = [r for r in results if r.success]
        if not success_results:
            return {
                "function_name": func.__name__,
                "iterations": iterations,
                "success": False,
                "message": "所有测试都失败了",
            }

        success_times = [r.execution_time for r in success_results]
        avg_time = sum(success_times) / len(success_times)
        min_time = min(success_times)
        max_time = max(success_times)
        median_time = sorted(success_times)[len(success_times) // 2]
        tps = len(success_results) / sum(success_times)

        return {
            "function_name": func.__name__,
            "iterations": iterations,
            "success": True,
            "total_executions": len(results),
            "successful_executions": len(success_results),
            "average_time": avg_time,
            "minimum_time": min_time,
            "maximum_time": max_time,
            "median_time": median_time,
            "tps": tps,
            "total_time": sum(success_times),
        }

    @staticmethod
    def compare_function_performances(
        functions: List[Callable], iterations: int = 1000
    ):
        """比较多个函数的性能"""
        results = []

        for func in functions:
            result = PerformanceTestInterface.measure_function_performance(
                func, iterations
            )
            if result:
                results.append(result)

        # 按平均时间排序
        results.sort(key=lambda x: x["average_time"])

        return results


# 压力测试示例脚本（可直接运行）
if __name__ == "__main__":
    """压力测试示例 - 展示如何使用压力测试模块"""

    print("MaaMCP 压力测试示例")
    print("=" * 60)

    # 创建压力测试配置
    config = StressTestConfig()
    config.iterations = 1000  # 使用1000次迭代进行完整的压力测试

    # 创建测试实例
    test = TestStressPerformance()
    test.setup_class()

    # 运行部分压力测试
    print("\n1. 运行 find_adb_device_list 压力测试:")
    test.test_stress_find_adb_device_list()

    print("\n2. 运行 OCR 压力测试:")
    test.test_stress_ocr()

    print("\n3. 运行 click 压力测试:")
    test.test_stress_click()

    print("\n4. 运行 input_text 压力测试:")
    test.test_stress_input_text()

    print("\n5. 运行 scroll 压力测试:")
    test.test_stress_scroll()

    print("\n6. 运行 double_click 压力测试:")
    test.test_stress_double_click()

    print("\n" + "=" * 60)
    print("压力测试示例执行完成！")
    print("要运行完整的1000次迭代测试，请使用 pytest 执行:")
    print("pytest tests/test_performance_stress.py -v")
