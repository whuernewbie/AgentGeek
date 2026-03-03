"""
租房Agent HTTP 服务入口
提供 POST /api/v1/chat（自部署模型）和 POST /api/v2/chat（远程LLM）两个接口。
"""

import logging
import time
import uuid

from flask import Flask, request, jsonify

from config import setup_logging
from agent import chat

# 初始化日志（在 import 阶段执行，保证所有模块都能用到）
setup_logging()

logger = logging.getLogger(__name__)

app = Flask(__name__)


def _handle_chat(endpoint_name: str, model_ip: str = None):
    """
    公共的聊天处理逻辑，供 /api/v1/chat 和 /api/v2/chat 共用。

    Args:
        endpoint_name: 端点名称（用于日志）
        model_ip: 自部署模型的 IP 地址（v1 接口传入，v2 为 None）
    """
    start_time = time.time()

    data = request.get_json(silent=True)
    if not data:
        logger.warning("收到非JSON请求 from=%s", request.remote_addr)
        return jsonify({"error": "请求体必须为 JSON 格式"}), 400

    message = data.get("message", "").strip()
    if not message:
        logger.warning("收到空消息请求 from=%s", request.remote_addr)
        return jsonify({"error": "message 字段不能为空"}), 400

    session_id = data.get("session_id", "").strip()
    if not session_id:
        session_id = uuid.uuid4().hex

    logger.info(">>> 请求 POST %s session=%s message=%s model_ip=%s", endpoint_name, session_id, message[:80], model_ip)

    try:
        result = chat(session_id, message, model_ip=model_ip)
        elapsed = time.time() - start_time
        duration_ms = int(elapsed * 1000)

        response_body = {
            "session_id": session_id,
            "response": result["response"],
            "status": result["status"],
            "tool_results": result["tool_results"],
            "timestamp": int(time.time()),
            "duration_ms": duration_ms,
        }

        logger.info(
            "<<< 响应 session=%s status=%s 耗时=%dms tools=%d response=%s",
            session_id, result["status"], duration_ms,
            len(result["tool_results"]),
            result["response"][:80],
        )
        return jsonify(response_body)
    except Exception as e:
        elapsed = time.time() - start_time
        duration_ms = int(elapsed * 1000)
        logger.error(
            "!!! 异常 session=%s 耗时=%dms error=%s", session_id, duration_ms, e,
            exc_info=True,
        )
        return jsonify({
            "session_id": session_id,
            "response": "",
            "status": "error",
            "tool_results": [],
            "timestamp": int(time.time()),
            "duration_ms": duration_ms,
            "error": f"处理失败: {str(e)}",
        }), 500


@app.route("/api/v1/chat", methods=["POST"])
def chat_v1_endpoint():
    """
    问答接口（v1 - 自部署模型）

    请求体 (JSON):
        {
            "session_id": "abc123",   // 可选，不传则自动生成
            "message": "帮我找西二旗附近的两居室",  // 必填
            "model_ip": "192.168.1.100:8000"        // 必填，自部署模型地址
        }

    curl 调试示例:
        curl -X POST http://localhost:5000/api/v1/chat \
            -H "Content-Type: application/json" \
            -d "{\"session_id\":\"test1\",\"model_ip\":\"192.168.1.100:8000\",\"message\":\"帮我找西二旗附近3000以下的一居室\"}"
    """
    data = request.get_json(silent=True)
    logger.info("=================== request start ===================", data)
    logger.info("request json data:%s", data)
    if not data:
        return jsonify({"error": "请求体必须为 JSON 格式"}), 400

    model_ip = data.get("model_ip", "").strip()
    if not model_ip:
        return jsonify({"error": "model_ip 字段不能为空"}), 400

    return _handle_chat("/api/v1/chat", model_ip=model_ip)


@app.route("/api/v2/chat", methods=["POST"])
def chat_v2_endpoint():
    """
    问答接口（v2 - 远程LLM）

    请求体 (JSON):
        {
            "session_id": "abc123",   // 可选，不传则自动生成
            "message": "帮我找西二旗附近的两居室"  // 必填
        }

    curl 调试示例:
        curl -X POST http://localhost:5000/api/v2/chat \
            -H "Content-Type: application/json" \
            -d "{\"session_id\":\"test1\",\"message\":\"帮我找西二旗附近3000以下的一居室\"}"
    """
    return _handle_chat("/api/v2/chat")


if __name__ == "__main__":
    logger.info("租房Agent服务启动 host=0.0.0.0 port=8191")
    time_count = 0
    app.run(host="0.0.0.0", port=8191, debug=False)