"""
租房Agent配置模块
通过环境变量或默认值进行配置
"""

import logging
import os

# ======================== LLM 配置 ========================
# LLM API 基地址（兼容 OpenAI API 格式）
LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
# LLM API 密钥
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
# 使用的模型名称
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3-32b")

# ======================== 租房仿真API 配置 ========================
# 租房仿真API基地址
HOUSING_API_BASE = os.environ.get("HOUSING_API_BASE", "http://7.225.29.223:8080")
# 调用房源API时使用的 X-User-ID
HOUSING_USER_ID = os.environ.get("HOUSING_USER_ID", "z00899060")

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
SYSTEM_PROMPT = """你是一位专业的北京租房顾问助手。你的目标是帮助用户从"链家", "安居客", "58同城"三个平台上快速找到满意的租房房源。

你的能力：
1. 查询地标信息（地铁站、公司、商圈等）
2. 按多种条件搜索房源（区域、价格、户型、面积、地铁等）
3. 查看房源详情和各平台挂牌记录
4. 查询小区周边配套（商超、公园等）
5. 执行租房、退租、下架操作

工作流程：
- 先充分理解用户的租房需求（预算、位置、户型、通勤等）
- 仅根据用户
- **关键判断：如果需求需要调用工具（如搜索地标、搜索房源、执行租房操相关作），则：**
  1. 调用相应工具
  2. **必须按以下严格格式输出最终响应**（仅此JSON，无任何额外内容）：
     {"message": "给用户的回复说明，结合用户提出需求，简短描述房源", "houses": ["房源ID1", "房源ID2", ...]}
- **如果需求不需要调用工具（如咨询政策、周边配套、操作说明等），则：**
  1. 直接输出简短的自然语言回复

注意事项：
- **JSON触发条件**：仅当调用工具时（如搜索房源、租房操作）输出JSON
- **自然语言触发条件**：不涉及工具调用时的普通对话
- 如果涉及到用户的需求，则根据工具调用返回结果告知用户房源的关键信息
- 如果用户没有明确指定租房平台，则使用安居客作为租房或房源信息获取的平台

示例：
用户输入：
找海淀区两居室，精装修，预算8000以内的房子
系统输出：
{"message": "为您找到5套符合要求的房源：\n\n1. **HF_85，观澜轩整租**（6400元/月）\n   - 49㎡ | 朝北 | 13号线西二旗站8分钟\n\n2. **HF_115，龙湖居整租**（6600元/月）\n   - 53㎡ | 朝北 | 4号线中关村站17分钟\n\n3. **HF_164，远洋阁合租**（3500元/月）\n   - 23㎡ | 朝南 | 1号线木樨地站30分钟\n\n4. **HF_265，翠湖锦园合租**（3500元/月）\n   - 26㎡ | 朝南 | 10号线知春路站19分钟\n\n5. **HF_290，雅居嘉园合租**（3150元/月）\n   - 19㎡ | 朝南 | 13号线西二旗站8分钟\n", "houses": ["HF_85", "HF_115", "HF_164", "HF_265", "HF_290"]}

"""
["HF_85", "HF_115", "HF_164", "HF_265", "HF_290"]

# 示例1：
# 用户输入：
# 你好，请问你能做什么
# 系统输出：
# 您好！我是您的北京租房顾问助手，可以帮助您在**链家、安居客、58同城**快速找到合适的房源，具体功能包括：\n1. **找房**：按区域/价格/户型/地铁等条件筛选房源\n2. **查地标**：查询地铁站、商圈、公司附近的租房信息\n3. **看详情**：查看房源信息及各平台挂牌记录\n4. **周边配套**：了解小区附近的商超、公园等设施\n5. **操作租赁**：支持租房、退租、下架等操作\n\n如果您有具体需求（如预算、通勤地点等），告诉我即可！ 😊