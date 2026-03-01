# AgentGeek 详细设计文档

## 1. 软件架构

### 1.1 整体架构

系统采用分层架构，共四层，每层职责单一：

```
┌──────────────────────────────────────────────────┐
│                   客户端 (curl)                    │
│              POST /chat {session_id, message}     │
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│                 app.py (HTTP 层)                  │
│  · Flask 路由                                     │
│  · 参数校验 (JSON格式、message非空)               │
│  · session_id 自动生成                            │
│  · 请求/响应日志                                  │
│  · 异常捕获 → 500                                 │
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│                agent.py (Agent 核心层)             │
│  · 对话存储 (load/save JSON文件)                  │
│  · 消息格式转换 (存储格式 ↔ OpenAI格式)           │
│  · LLM 调用 (OpenAI Chat Completion API)          │
│  · Agent 循环 (文本回复 / tool_calls → 执行 → 回传)│
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│                tools.py (工具层)                   │
│  · 15 个工具定义 (OpenAI function calling 格式)   │
│  · 工具路由表 (工具名 → HTTP方法/URL/参数位置)    │
│  · execute_tool() 执行引擎                        │
│  · 调用租房仿真 API 并返回结果                    │
└──────────────────────┬───────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
   ┌─────────────┐          ┌─────────────┐
   │  LLM API    │          │  租房仿真API │
   │ (SiliconFlow │          │ (8080端口)  │
   │  /OpenAI等)  │          │             │
   └─────────────┘          └─────────────┘
```

### 1.2 请求处理流程

一次完整的用户请求经历以下流程：

```
用户发送 POST /chat
    │
    ▼
app.py: 参数校验 → 提取 session_id 和 message
    │
    ▼
agent.py: 加载 conversations/{session_id}.json 历史对话
    │
    ▼
agent.py: 构造 LLM 消息 = [system_prompt] + [历史对话] + [新消息]
    │
    ▼
agent.py: ──────── Agent 循环开始 ────────
    │
    ├─→ 调用 LLM API (带 tools 定义)
    │       │
    │       ├─ 返回 tool_calls → 逐个执行工具 → 将结果追加 → 回到循环
    │       │       │
    │       │       └─ tools.py: 构造HTTP请求 → 调用租房仿真API → 返回JSON
    │       │
    │       └─ 返回文本 → 跳出循环
    │
    ▼
agent.py: 保存对话到 conversations/{session_id}.json
    │
    ▼
app.py: 返回 JSON {"session_id", "response", "status", "tool_results", "timestamp", "duration_ms"}
```

### 1.3 模块依赖关系

```
config.py ← (被所有模块引用)
    ↑
tools.py ← (被 agent.py 引用)
    ↑
agent.py ← (被 app.py 引用)
    ↑
app.py    (入口)
```

依赖方向为单向，无循环依赖。

---

## 2. 软件设计与实现

### 2.1 config.py — 配置管理

**职责**：集中管理所有配置项和日志初始化。

**配置项**：

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| LLM API 基地址 | `LLM_API_BASE` | `https://api.siliconflow.cn/v1` | 兼容 OpenAI API 格式 |
| LLM API 密钥 | `LLM_API_KEY` | (内置) | Bearer Token |
| LLM 模型名 | `LLM_MODEL` | `Qwen/Qwen3-8B` | 模型标识 |
| 租房 API 基地址 | `HOUSING_API_BASE` | `http://127.0.0.1:8080` | 仿真服务地址 |
| 用户 ID | `HOUSING_USER_ID` | `user_001` | 房源 API 的 X-User-ID |
| 对话存储目录 | `CONVERSATIONS_DIR` | `./conversations/` | JSON 文件目录 |
| 最大工具轮次 | `MAX_TOOL_ROUNDS` | `10` | 防止死循环 |
| 日志目录 | `LOG_DIR` | `./logs/` | 日志文件目录 |
| 日志级别 | `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |

**日志初始化**：`setup_logging()` 函数配置 Python logging 的 root logger，同时添加控制台和文件两个 Handler，文件输出到 `logs/agent.log`（UTF-8 编码，追加模式）。通过检查 `root_logger.handlers` 避免 Flask debug 热重载时重复添加。

**系统提示词**：`SYSTEM_PROMPT` 定义了 Agent 的角色（北京租房顾问）、能力范围、工作流程和回复规范。

### 2.2 tools.py — 工具定义与执行

**职责**：将租房仿真 API 转换为 LLM 可用的工具，并负责执行。

**两大核心数据结构**：

1. **`TOOLS` 列表**：15 个工具定义，遵循 OpenAI function calling 格式：

```python
{
    "type": "function",
    "function": {
        "name": "操作ID",
        "description": "工具描述",
        "parameters": {
            "type": "object",
            "properties": { ... },   # 参数定义
            "required": [ ... ]       # 必填参数
        }
    }
}
```

2. **`_TOOL_ROUTES` 路由表**：将工具名映射到 HTTP 调用信息：

```python
"工具名": (HTTP方法, URL模板, [路径参数名], 是否需要X-User-ID)
```

**15 个工具分三类**：

| 类别 | 工具 | HTTP方法 | X-User-ID |
|------|------|----------|-----------|
| 地标查询 (5个) | get_landmarks, get_landmark_by_name, search_landmarks, get_landmark_by_id, get_landmark_stats | GET | 否 |
| 房源查询 (7个) | get_house_by_id, get_house_listings, get_houses_by_community, get_houses_by_platform, get_nearby_landmarks, get_houses_nearby, get_house_stats | GET | 是 |
| 租房操作 (3个) | rent_house, terminate_rental, take_offline | POST | 是 |

**`execute_tool(tool_name, arguments)` 执行逻辑**：

1. 从路由表查找工具配置
2. 遍历参数：路径参数替换到 URL 模板中的 `{param}`，其余作为 query 参数
3. 拼接完整 URL = `HOUSING_API_BASE` + 替换后的路径
4. 构造请求头（需要时添加 `X-User-ID`）
5. 发送 HTTP 请求（GET 或 POST）
6. 返回结构化字典（异常时不抛异常）：

```python
{
    "success": bool,   # HTTP 2xx 为 True，否则为 False
    "output": str,     # API 响应的 JSON 字符串（或错误信息）
}
```

### 2.3 agent.py — Agent 核心逻辑

**职责**：对话管理 + LLM 交互 + 工具调用循环。

#### 2.3.1 对话存储

- **文件路径**：`conversations/{session_id}.json`
- **存储格式**：

```json
[
    {"role": "user",  "timestamp": "2026-03-01 22:30:32", "content": "你好"},
    {"role": "agent", "timestamp": "2026-03-01 22:30:35", "content": "您好！..."}
]
```

- `load_conversation(session_id)`：读取文件，文件不存在或损坏时返回空列表
- `save_conversation(session_id, messages)`：原子写入，`ensure_ascii=False` 保证中文可读

#### 2.3.2 消息格式转换

存储格式与 OpenAI API 格式的 role 映射：

| 存储格式 | OpenAI 格式 |
|----------|-------------|
| `user` | `user` |
| `agent` | `assistant` |

转换时仅保留 `role` 和 `content`，丢弃 `timestamp`（LLM 不需要）。

#### 2.3.3 LLM 调用

`_call_llm(messages, tools)` 函数：

- 构造 OpenAI Chat Completion 请求：URL = `LLM_API_BASE` + `/chat/completions`
- 请求头包含 `Authorization: Bearer {API_KEY}`
- payload 包含 `model`、`messages`、`tools`（可选）
- 记录耗时和 token 用量
- 非 200 响应时抛出 `RuntimeError` 并携带完整错误信息

#### 2.3.4 Agent 循环

`chat(session_id, user_message)` 是对外唯一入口，流程：

1. 加载历史对话，初始化 `all_tool_results` 收集列表
2. 追加用户新消息（含时间戳）
3. 构造 LLM 消息：`[system_prompt]` + 历史消息(role转换) + 新消息
4. **循环**（最多 `MAX_TOOL_ROUNDS` 轮）：
   - 调用 LLM
   - 若返回 `tool_calls`：逐个解析并执行工具 → 将 `{name, success, output}` 追加到 `all_tool_results` → 将工具输出以 `role: tool` 追加 → 继续循环
   - 若返回文本：作为最终回复跳出循环
5. 保存完整对话（user + agent 回复）
6. 返回结构化字典：

```python
{
    "response": str,          # Agent 的回复文本
    "status": str,            # "success" 或 "max_rounds_exceeded"
    "tool_results": [         # 所有工具调用结果
        {
            "name": str,      # 工具名称（对应 operationId）
            "success": bool,  # 调用是否成功
            "output": str,    # 工具输出内容
        },
        ...
    ],
}
```

**防死循环**：超过 `MAX_TOOL_ROUNDS`（默认10）轮后强制返回 fallback 提示，`status` 为 `"max_rounds_exceeded"`。

### 2.4 app.py — HTTP 服务入口

**职责**：Flask 路由、参数校验、异常处理。

**端点 `POST /chat`**：

- 请求体：`{"session_id": "可选", "message": "必填"}`
- 成功响应体 (200)：

```json
{
    "session_id": "abc123",
    "response": "为您找到以下房源...",
    "status": "success",
    "tool_results": [
        {"name": "get_houses_by_platform", "success": true, "output": "{...}"}
    ],
    "timestamp": 1709251200,
    "duration_ms": 5070
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 会话 ID（未传时自动生成 UUID） |
| `response` | string | Agent 的回复文本 |
| `status` | string | 处理状态：`success` / `max_rounds_exceeded` / `error` |
| `tool_results` | array | 工具调用结果列表，每个元素包含 `name`（工具名）、`success`（是否成功）、`output`（输出内容） |
| `timestamp` | int | 响应时间戳（Unix 秒） |
| `duration_ms` | int | 处理耗时（毫秒） |

**校验规则**：

| 场景 | 状态码 | 说明 |
|------|--------|------|
| 请求体不是 JSON | 400 | 返回 `{"error": "请求体必须为 JSON 格式"}` |
| message 缺失或为空 | 400 | 返回 `{"error": "message 字段不能为空"}` |
| session_id 未传 | 200 | 自动生成 UUID |
| Agent 内部异常 | 500 | 返回统一结构，`status` 为 `"error"`，额外包含 `error` 字段 |

---

## 3. 服务启动流程

### 3.1 启动命令

```bash
python app.py
```

### 3.2 启动过程详解

```
python app.py
    │
    ▼
[1] Python 加载 app.py
    │   from config import setup_logging
    │   from agent import chat
    │
    ▼
[2] setup_logging() 被调用
    │   · 创建 logs/ 目录（不存在时）
    │   · 配置 root logger 级别（默认 INFO）
    │   · 添加控制台 Handler（StreamHandler）
    │   · 添加文件 Handler（logs/agent.log，UTF-8 追加模式）
    │   · 日志格式：[时间] 级别 [模块名] 内容
    │
    ▼
[3] 加载 agent.py → 加载 tools.py → 加载 config.py
    │   · TOOLS 列表（15个工具定义）在模块加载时初始化
    │   · _TOOL_ROUTES 路由表在模块加载时初始化
    │   · 所有配置项在模块加载时从环境变量读取
    │
    ▼
[4] app = Flask(__name__) 创建 Flask 实例
    │
    ▼
[5] app.run(host="0.0.0.0", port=5000, debug=True)
    │   · 监听所有网络接口的 5000 端口
    │   · debug=True 开启热重载（代码修改自动重启）
    │   · 输出启动日志：
    │     [2026-03-01 23:38:08] INFO [__main__] 租房Agent服务启动
    │     * Running on http://127.0.0.1:5000
    │
    ▼
[6] 服务就绪，等待请求
```

### 3.3 运行时目录结构

服务启动后会自动创建以下目录和文件：

```
AgentGeek/
├── logs/
│   └── agent.log          # 首次启动时自动创建
└── conversations/
    ├── session1.json       # 首次对话时自动创建
    └── session2.json
```

### 3.4 日志系统

日志同时输出到控制台和 `logs/agent.log`，各模块记录内容：

| 模块 | 日志内容 |
|------|----------|
| app.py | `>>>` 请求进入（session_id、message 摘要）、`<<<` 响应返回（耗时、reply 摘要）、`!!!` 异常（含堆栈） |
| agent.py | 会话加载/保存、Agent 循环轮次、LLM 调用（model、messages 数、tools 数）、LLM 响应（耗时、token 用量）、工具调度（工具名列表）、最终回复 |
| tools.py | 工具调用（工具名、HTTP方法、URL、参数）、工具响应（状态码、耗时）、调用失败错误 |

**日志示例**（一次完整请求）：

```
[23:38:31] INFO [__main__]  >>> 请求 POST /chat session=test1 message=帮我找西二旗...
[23:38:31] INFO [agent]     ===== 会话 [test1] 收到用户消息: 帮我找西二旗...
[23:38:31] INFO [agent]     会话 [test1] Agent循环 第1轮
[23:38:31] INFO [agent]     调用LLM model=Qwen/Qwen3-8B messages=2条 tools=15个
[23:38:33] INFO [agent]     LLM响应 耗时=2.15s prompt_tokens=2770 completion_tokens=85
[23:38:33] INFO [agent]     会话 [test1] 第1轮 LLM请求调用 1 个工具: ['get_houses_by_platform']
[23:38:33] INFO [tools]     工具调用 [get_houses_by_platform] GET http://127.0.0.1:8080/api/houses/by_platform params={...}
[23:38:33] INFO [tools]     工具响应 [get_houses_by_platform] status=200 耗时=0.12s
[23:38:33] INFO [agent]     会话 [test1] Agent循环 第2轮
[23:38:33] INFO [agent]     调用LLM model=Qwen/Qwen3-8B messages=5条 tools=15个
[23:38:36] INFO [agent]     LLM响应 耗时=2.80s prompt_tokens=3200 completion_tokens=150
[23:38:36] INFO [agent]     会话 [test1] Agent最终回复（共2轮）: 为您找到以下房源...
[23:38:36] INFO [agent]     会话 [test1] 已保存，共 2 条消息
[23:38:36] INFO [__main__]  <<< 响应 session=test1 status=success 耗时=5070ms tools=1 response=为您找到以下房源...
```

---

## 4. 测试覆盖

### 4.1 概览

| 测试文件 | 测试类数 | 用例数 | 测试对象 |
|----------|----------|--------|----------|
| test/test_app.py | 1 | 11 | HTTP 接口 |
| test/test_agent.py | 4 | 18 | Agent 核心逻辑 |
| test/test_tools.py | 3 | 22 | 工具定义与执行 |
| **合计** | **8** | **51** | |

所有外部依赖（LLM API、租房仿真 API）均通过 `unittest.mock` 模拟，测试无需网络连接。

### 4.2 test/test_app.py — HTTP 接口测试

**TestChatEndpoint** (11 个用例)：

| 用例 | 验证内容 |
|------|----------|
| `test_non_json_body_returns_400` | 非 JSON 请求体返回 400 |
| `test_empty_message_returns_400` | message 为空字符串返回 400 |
| `test_missing_message_returns_400` | 缺少 message 字段返回 400 |
| `test_whitespace_only_message_returns_400` | message 仅含空格返回 400 |
| `test_normal_request_returns_200` | 正常请求返回 200，response/status/tool_results 正确 |
| `test_auto_generate_session_id` | 不传 session_id 时自动生成 UUID |
| `test_response_json_structure` | 响应包含全部 6 个必需字段（session_id/response/status/tool_results/timestamp/duration_ms） |
| `test_timestamp_is_int` | timestamp 为 int 类型且在合理范围内 |
| `test_duration_ms_is_int` | duration_ms 为 int 类型且非负 |
| `test_tool_results_in_response` | tool_results 包含 {name, success, output} 格式的工具调用结果 |
| `test_internal_error_returns_500` | Agent 异常返回 500，响应体包含统一结构（status="error"） |

### 4.3 test/test_agent.py — Agent 逻辑测试

**TestConversationStorage** (7 个用例)：

| 用例 | 验证内容 |
|------|----------|
| `test_load_empty_session` | 不存在的会话返回空列表 |
| `test_save_and_load` | 保存后加载数据一致 |
| `test_save_creates_file` | 保存操作创建 JSON 文件 |
| `test_save_file_is_valid_json` | 文件内容为合法 JSON |
| `test_save_file_utf8_no_ascii_escape` | 中文直接存储，无 `\uXXXX` 转义 |
| `test_load_corrupted_file_returns_empty` | 损坏文件不抛异常，返回空列表 |
| `test_overwrite_existing_session` | 重复保存覆盖旧数据 |

**TestMessageConversion** (5 个用例)：

| 用例 | 验证内容 |
|------|----------|
| `test_user_role_unchanged` | `user` 角色保持不变 |
| `test_agent_role_to_assistant` | `agent` 转换为 `assistant` |
| `test_content_preserved` | content 内容完整保留 |
| `test_timestamp_not_in_llm_message` | 转换后不含 timestamp |
| `test_multi_turn_conversion` | 多轮对话角色正确交替 |

**TestTimestamp** (1 个用例)：

| 用例 | 验证内容 |
|------|----------|
| `test_timestamp_format` | 格式为 `YYYY-MM-DD HH:MM:SS` |

**TestChatLoop** (5 个用例)：

| 用例 | 验证内容 |
|------|----------|
| `test_simple_text_reply` | LLM 直接返回文本时返回 dict，status=success，tool_results 为空列表 |
| `test_conversation_saved_after_reply` | 回复后对话历史正确保存（含 user + agent），response 正确 |
| `test_tool_call_then_reply` | LLM 先 tool_call 再文本回复，tool_results 包含 {name, success, output} |
| `test_max_rounds_fallback` | 超过最大轮次返回 fallback 提示，status=max_rounds_exceeded，tool_results 数量正确 |
| `test_context_continuity` | 同一 session 第二次请求包含历史上下文 |

### 4.4 test/test_tools.py — 工具定义与执行测试

**TestToolDefinitions** (6 个用例)：

| 用例 | 验证内容 |
|------|----------|
| `test_tools_is_list` | TOOLS 为列表类型 |
| `test_tools_count` | 共 15 个工具 |
| `test_each_tool_has_required_fields` | 每个工具有 type、function.name/description/parameters |
| `test_each_tool_has_valid_parameters_schema` | parameters 为合法 JSON Schema |
| `test_tool_names_unique` | 工具名不重复 |
| `test_known_tools_exist` | 9 个关键工具名均存在 |

**TestToolRoutes** (7 个用例)：

| 用例 | 验证内容 |
|------|----------|
| `test_routes_count_matches_tools` | 路由表条数 = 工具定义数 |
| `test_every_tool_has_route` | 每个工具都有对应路由 |
| `test_route_tuple_structure` | 元组结构正确 (method, url, path_params, needs_uid) |
| `test_landmark_routes_no_user_id` | 5 个地标接口不要求 X-User-ID |
| `test_house_routes_need_user_id` | 房源接口要求 X-User-ID |
| `test_action_routes_are_post` | 租房/退租/下架为 POST |
| `test_query_routes_are_get` | 查询接口为 GET |

**TestExecuteTool** (9 个用例)：

| 用例 | 验证内容 |
|------|----------|
| `test_unknown_tool_returns_error` | 未知工具返回 `{success: false, output: '{"error": ...}'}` |
| `test_get_landmarks_builds_correct_url` | URL 和 query 参数构造正确 |
| `test_path_param_substitution` | `{house_id}` 被正确替换为实际值 |
| `test_user_id_header_added` | 房源接口带 X-User-ID header |
| `test_no_user_id_for_landmarks` | 地标接口不带 X-User-ID |
| `test_rent_house_uses_post` | rent_house 使用 POST 方法 |
| `test_request_exception_returns_error` | 网络异常返回 `{success: false}`，不抛异常 |
| `test_non_json_response_handled` | API 返回非 JSON 时优雅降级，`success` 为 false |
| `test_mixed_path_and_query_params` | 路径参数与查询参数正确分离 |

### 4.5 运行测试

```bash
# 运行全部测试
python -m pytest test/ -v

# 运行单个文件
python -m pytest test/test_agent.py -v

# 运行单个用例
python -m pytest test/test_tools.py::TestExecuteTool::test_path_param_substitution -v
```
