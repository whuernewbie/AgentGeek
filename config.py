"""
租房Agent配置模块
通过环境变量或默认值进行配置
"""

import logging
import os

# ======================== LLM 配置 ========================
# LLM API 基地址（兼容 OpenAI API 格式）
LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://api.siliconflow.cn/v1")
# LLM API 密钥
LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-ebdkvwdpgakiqfuuiufhbvhjlxjxyciumjbkoxfwprflcroe")
# 使用的模型名称
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen3-8B")

# ======================== 租房仿真API 配置 ========================
# 租房仿真API基地址
HOUSING_API_BASE = os.environ.get("HOUSING_API_BASE", "http://127.0.0.1:8080")
# 调用房源API时使用的 X-User-ID
HOUSING_USER_ID = os.environ.get("HOUSING_USER_ID", "user_001")

# ======================== 对话存储配置 ========================
# 对话历史存储目录
CONVERSATIONS_DIR = os.environ.get(
    "CONVERSATIONS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "conversations"),
)

# ======================== 日志配置 ========================
# 日志目录
LOG_DIR = os.environ.get(
    "LOG_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"),
)
# 日志级别: DEBUG / INFO / WARNING / ERROR
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


def setup_logging():
    """
    初始化日志配置：同时输出到控制台和文件 logs/agent.log。
    应在应用启动时调用一次。
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, "agent.log")

    fmt = "[%(asctime)s] %(levelname)s [%(name)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # 避免重复添加 handler（Flask debug 模式会重载）
    if not root_logger.handlers:
        # 控制台 handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        root_logger.addHandler(console_handler)

        # 文件 handler（UTF-8 编码，追加模式）
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        root_logger.addHandler(file_handler)


# ======================== Agent 配置 ========================
# 最大工具调用轮次（防止死循环）
MAX_TOOL_ROUNDS = int(os.environ.get("MAX_TOOL_ROUNDS", "10"))

# 系统提示词
SYSTEM_PROMPT = """你是一位专业的北京租房顾问助手。你的目标是帮助用户快速找到满意的租房房源。

你的能力：
1. 查询地标信息（地铁站、公司、商圈等）
2. 按多种条件搜索房源（区域、价格、户型、面积、地铁等）
3. 查看房源详情和各平台挂牌记录
4. 查询小区周边配套（商超、公园等）
5. 执行租房、退租、下架操作

工作流程：
- 先充分理解用户的租房需求（预算、位置、户型、通勤等）
- 如果需求不明确，主动询问关键信息
- 使用工具搜索匹配的房源
- 将结果以清晰、结构化的方式呈现给用户
- 提供专业的租房建议

注意事项：
- 回复使用中文
- 金额单位为人民币元/月
- 面积单位为平方米
- 如果搜索结果较多，优先展示最匹配的几个
- 主动告知房源的关键信息：价格、面积、户型、位置、地铁距离等
"""
