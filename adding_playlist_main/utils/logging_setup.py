"""
日志配置
"""

import logging
from datetime import datetime
from pathlib import Path

from config import LOG_DIR, LOG_FILE_BASENAME


def setup_logging(platform: str = "X", mode: str = "run"):
    """配置日志，输出到文件。"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_platform = (platform or "X").upper()
    safe_mode = (mode or "run").lower()
    log_filename = LOG_DIR / f"{LOG_FILE_BASENAME}_{safe_platform}_{safe_mode}_{timestamp}.log"
    
    # 确保目录存在
    log_filename.parent.mkdir(parents=True, exist_ok=True)
    
    # 清理旧处理器，避免同一进程重复添加导致重复输出
    logger = logging.getLogger()
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    # 创建日志格式
    log_format = logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S')
    
    # 创建文件处理器
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.INFO)
    
    # 获取 root logger
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    
    # 第三方库请求异常会重复输出原始HTTP错误，这里做降噪
    tidal_request_logger = logging.getLogger("tidalapi.request")
    tidal_request_logger.setLevel(logging.CRITICAL)
    tidal_request_logger.propagate = False
    
    return log_filename


# 全局 print 函数重定义
_original_print = print


def print(*args, **kwargs):
    """自定义 print 函数，同时输出到控制台和日志文件"""
    message = ' '.join(str(arg) for arg in args)
    logging.info(message)  # 写入日志文件
    _original_print(*args, **kwargs)  # 输出到控制台
