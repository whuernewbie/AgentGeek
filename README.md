# AgentGeek - 北京租房智能助手

基于 LLM + Function Calling 的租房 Agent 后端服务，能够通过自然语言对话帮助用户快速找到满意的房源。

## 功能特性

- 自然语言对话：理解用户租房需求，主动询问关键信息
- 房源智能搜索：按区域、价格、户型、地铁、通勤时间等多维度筛选
- 地标与周边查询：查询地铁站、商圈、小区周边配套（商超/公园）
- 租房操作：支持租房、退租、下架等操作
- 多轮对话：按 session 隔离存储上下文，支持连续追问
- 全链路日志：请求/LLM调用/工具调用/响应均有详细日志记录

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config.py` 中的默认值，或通过环境变量配置：

```bash
# LLM 配置（兼容 OpenAI API 格式）
set LLM_API_BASE=https://api.siliconflow.cn/v1
set LLM_API_KEY=sk-your-key
set LLM_MODEL=Qwen/Qwen3-8B

# 租房仿真 API
set HOUSING_API_BASE=http://127.0.0.1:8080
set HOUSING_USER_ID=user_001
```

### 3. 启动服务

```bash
python app.py
```

服务默认运行在 `http://localhost:5000`。

### 4. 调试

```bash
curl -X POST http://localhost:5000/api/v2/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"test1\",\"message\":\"帮我找西二旗附近3000以下的一居室\"}"
```

响应示例：

```json
{
    "session_id": "test1",
    "response": "为您找到以下西二旗附近3000元以下的一居室...",
    "status": "success",
    "tool_results": [
        {
            "name": "get_houses_by_platform",
            "success": true,
            "output": "{\"data\": [...]}"
        }
    ],
    "timestamp": 1709251200,
    "duration_ms": 5070
}
```

### 5. 运行测试

```bash
python -m pytest test/ -v
```

## 项目结构

```
AgentGeek/
├── app.py                   # HTTP 服务入口（Flask，POST /api/v2/chat）
├── agent.py                 # Agent 核心（对话管理、LLM 调用、工具调用循环）
├── tools.py                 # 工具定义（OpenAI function 格式）+ 工具执行引擎
├── config.py                # 配置管理 + 日志初始化
├── requirements.txt         # 外部依赖（flask、requests）
├── conversations/           # 对话历史存储（JSON 文件，按 session_id 隔离）
├── logs/                    # 运行日志（agent.log）
├── test/                    # 单元测试（51 个用例）
│   ├── test_app.py          # HTTP 接口测试
│   ├── test_agent.py        # Agent 逻辑测试
│   └── test_tools.py        # 工具定义与执行测试
└── docs/                    # 文档
    ├── design.md            # 详细设计文档（架构、实现、测试）
    ├── demo_description.txt # 需求描述
    └── fake_app_agent_tools.json  # 租房仿真 API 的 OpenAPI 规范
```

## 技术栈

- **语言**：Python 3
- **Web 框架**：Flask
- **HTTP 客户端**：Requests
- **LLM 接口**：OpenAI API 兼容格式（支持 SiliconFlow、DashScope、OpenAI 等）
- **数据存储**：JSON 文件（对话历史）
- **日志**：Python logging（控制台 + 文件双输出）
- **测试**：unittest + unittest.mock

## 详细文档

架构设计、实现细节、服务启动流程、测试覆盖说明等请参阅 [docs/design.md](docs/design.md)。
