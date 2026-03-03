"""
Agent核心模块
负责对话管理、LLM调用、工具调用循环。
"""

import json
import logging
import os
import time
from datetime import datetime

import requests

import config
from tools import ALL_TOOLS, execute_tool

logger = logging.getLogger(__name__)


# ============================================================
# 对话存储
# ============================================================


def _conversation_path(session_id: str) -> str:
    """获取指定 session_id 对应的对话文件路径。"""
    return os.path.join(config.CONVERSATIONS_DIR, f"{session_id}.json")


def load_conversation(session_id: str) -> list:
    """
    加载对话历史。

    Returns:
        对话消息列表，格式:
        [{"role": "user"/"agent", "timestamp": "...", "content": "..."}]
    """
    path = _conversation_path(session_id)
    if not os.path.exists(path):
        logger.debug("会话 [%s] 无历史记录，创建新会话", session_id)
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            messages = json.load(f)
        logger.info("会话 [%s] 加载历史 %d 条消息", session_id, len(messages))
        return messages
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("会话 [%s] 加载失败: %s", session_id, e)
        return []


def save_conversation(session_id: str, messages: list) -> None:
    """将对话历史保存到文件。"""
    os.makedirs(config.CONVERSATIONS_DIR, exist_ok=True)
    path = _conversation_path(session_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)
    logger.info("会话 [%s] 已保存，共 %d 条消息", session_id, len(messages))


# ============================================================
# 消息格式转换
# ============================================================


def _stored_to_llm_messages(stored_messages: list) -> list:
    """
    将存储格式的消息转换为 OpenAI API 格式。
    存储格式 role: user/agent  ->  OpenAI格式 role: user/assistant
    """
    llm_messages = []
    for msg in stored_messages:
        role = "assistant" if msg["role"] == "agent" else msg["role"]
        llm_messages.append({"role": role, "content": msg["content"]})
    return llm_messages


def _now_timestamp() -> str:
    """获取当前时间戳字符串。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# LLM 调用
# ============================================================


def _call_llm(messages: list, tools: list = None, model_ip: str = None) -> dict:
    """
    调用 OpenAI 兼容的 Chat Completion API。

    当 model_ip 为 None 时，使用 config 中配置的远程 LLM（需要 API Key 和模型名）。
    当 model_ip 不为 None 时，调用用户自部署的模型（不需要 API Key 和模型名）。

    Args:
        messages: OpenAI 格式的消息列表
        tools: 工具定义列表（可选）
        model_ip: 自部署模型的 IP 地址（可选，如 "192.168.1.100:8000"）

    Returns:
        API 响应的 JSON 字典
    """
    if model_ip:
        # 自部署模型：直接用 model_ip 构造 URL，无需 API Key 和模型名
        url = model_ip
        headers = {"Content-Type": "application/json"}
        payload = {"model": config.LLM_MODEL, "messages": messages}
        model_label = f"self-hosted@{model_ip}"
    else:
        # 远程 LLM：使用 config 中的配置
        url = config.LLM_API_BASE.rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.LLM_API_KEY}",
        }
        payload = {"model": config.LLM_MODEL, "messages": messages}
        model_label = config.LLM_MODEL

    if tools:
        payload["tools"] = tools

    logger.info("调用LLM model=%s messages=%d条 tools=%d个", model_label, len(messages), len(tools) if tools else 0)
    logger.debug("LLM请求URL: %s", url)

    start_time = time.time()
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    elapsed = time.time() - start_time

    if resp.status_code != 200:
        logger.error("LLM API错误 status=%d 耗时=%.2fs body=%s", resp.status_code, elapsed, resp.text[:500])
        raise RuntimeError(
            f"LLM API 返回 {resp.status_code}: {resp.text}"
        )

    result = resp.json()
    # 记录 token 使用量（如果返回中有的话）
    usage = result.get("usage", {})
    if usage:
        logger.info(
            "LLM响应 耗时=%.2fs prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            elapsed,
            usage.get("prompt_tokens", "?"),
            usage.get("completion_tokens", "?"),
            usage.get("total_tokens", "?"),
        )
    else:
        logger.info("LLM响应 耗时=%.2fs", elapsed)

    return result


# ============================================================
# Agent 主循环
# ============================================================


def chat(session_id: str, user_message: str, model_ip: str = None) -> dict:
    """
    处理一次用户消息，返回包含 Agent 回复及工具调用详情的字典。

    流程:
    1. 加载历史对话
    2. 追加用户消息
    3. 构造 LLM 消息（含系统提示词）
    4. 循环: 调用 LLM -> 若有 tool_calls 则执行并回传 -> 否则返回文本
    5. 保存对话

    Args:
        session_id: 会话 ID
        user_message: 用户消息文本
        model_ip: 自部署模型的 IP 地址（可选，v1 接口使用）

    Returns:
        dict: {
            "response": str,          # Agent 的回复文本
            "status": str,            # 处理状态: "success" / "max_rounds_exceeded"
            "tool_results": list,     # 工具调用结果列表
        }
    """
    logger.info("===== 会话 [%s] 收到用户消息: %s", session_id, user_message[:100])

    # 收集所有工具调用结果
    all_tool_results = []

    # 1. 加载历史
    conversation = load_conversation(session_id)

    # 2. 追加用户消息到存储
    conversation.append(
        {
            "role": "user",
            "timestamp": _now_timestamp(),
            "content": user_message,
        }
    )

    # 3. 构造发送给 LLM 的消息
    llm_messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]
    llm_messages.extend(_stored_to_llm_messages(conversation))

    # 4. Agent 循环（工具调用）
    for round_idx in range(config.MAX_TOOL_ROUNDS):
        logger.info("会话 [%s] Agent循环 第%d轮", session_id, round_idx + 1)

        response = _call_llm(llm_messages, tools=TOOLS, model_ip=model_ip)

        choice = response["choices"][0]
        message = choice["message"]

        # 4a. 如果没有 tool_calls，说明是最终文本回复
        if not message.get("tool_calls"):
            reply_content = message.get("content", "")
            logger.info(
                "会话 [%s] Agent最终回复（共%d轮）: %s",
                session_id, round_idx + 1, reply_content[:100],
            )

            # 5. 保存 Agent 回复到对话历史
            conversation.append(
                {
                    "role": "agent",
                    "timestamp": _now_timestamp(),
                    "content": reply_content,
                }
            )
            save_conversation(session_id, conversation)

            return {
                "response": reply_content,
                "status": "success",
                "tool_results": all_tool_results,
            }

        # 4b. 有 tool_calls，执行工具并回传结果
        tool_names = [tc["function"]["name"] for tc in message["tool_calls"]]
        logger.info(
            "会话 [%s] 第%d轮 LLM请求调用 %d 个工具: %s",
            session_id, round_idx + 1, len(tool_names), tool_names,
        )

        # 先将 assistant 的 tool_calls 消息追加到 LLM 消息列表
        llm_messages.append(message)

        for tool_call in message["tool_calls"]:
            func_name = tool_call["function"]["name"]

            # 解析参数
            try:
                func_args = json.loads(tool_call["function"]["arguments"])
            except (json.JSONDecodeError, TypeError):
                func_args = {}

            logger.info("会话 [%s] 执行工具 %s(%s)", session_id, func_name, func_args)

            # 执行工具（返回 {"success": bool, "output": str}）
            tool_result = execute_tool(func_name, func_args)

            # 收集工具调用结果（name / success / output）
            all_tool_results.append({
                "name": func_name,
                "success": tool_result["success"],
                "output": tool_result["output"],
            })

            # 将工具输出追加到 LLM 消息
            llm_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_result["output"],
                }
            )

    # 达到最大轮次，返回提示
    logger.warning("会话 [%s] 达到最大工具调用轮次 %d，强制结束", session_id, config.MAX_TOOL_ROUNDS)
    fallback = "抱歉，处理您的请求时工具调用轮次过多，请尝试简化您的问题。"
    conversation.append(
        {
            "role": "agent",
            "timestamp": _now_timestamp(),
            "content": fallback,
        }
    )
    save_conversation(session_id, conversation)
    return {
        "response": fallback,
        "status": "max_rounds_exceeded",
        "tool_results": all_tool_results,
    }
