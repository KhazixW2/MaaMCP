# maa_mcp/pipeline/logging_config.py
"""
日志配置模块
============
使用 loguru 配置日志输出到控制台和文件。
"""

import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from maa_mcp.paths import get_logs_dir


# 标记是否已初始化
_initialized = False


def setup_logger(
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    error_retention: str = "30 days",
    log_retention: str = "7 days",
) -> None:
    """
    配置 loguru 日志系统。
    
    Args:
        console_level: 控制台日志级别
        file_level: 文件日志级别
        error_retention: 错误日志保留时间
        log_retention: 普通日志保留时间
    """
    global _initialized
    
    if _initialized:
        return
    
    # 获取日志目录
    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    # 移除默认 handler
    logger.remove()
    
    # 添加控制台输出
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{extra[module]}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=console_level,
        filter=lambda record: "module" in record["extra"],
    )
    
    # 为没有 module 的日志添加默认格式
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=console_level,
        filter=lambda record: "module" not in record["extra"],
    )
    
    # 添加文件输出 - 按日期轮转
    logger.add(
        logs_dir / "pipeline_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        level=file_level,
        rotation="00:00",  # 每天午夜轮转
        retention=log_retention,
        compression="zip",  # 压缩旧日志
        encoding="utf-8",
    )
    
    # 添加错误日志单独文件
    logger.add(
        logs_dir / "pipeline_error_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        level="ERROR",
        rotation="00:00",
        retention=error_retention,
        compression="zip",
        encoding="utf-8",
    )
    
    _initialized = True
    logger.bind(module="Logger").info(f"日志系统初始化完成，日志目录: {logs_dir}")


def get_logger(module: str = "Pipeline"):
    """
    获取带模块标识的 logger。
    
    Args:
        module: 模块名称标识
        
    Returns:
        绑定了模块名的 logger 实例
    """
    # 确保已初始化
    if not _initialized:
        setup_logger()
    
    return logger.bind(module=module)


# 模块级别的便捷导出
__all__ = ["setup_logger", "get_logger", "logger"]
