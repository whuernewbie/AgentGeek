"""
租房Agent HTTP 服务入口
提供 POST /api/v2/chat 接口，通过 curl 调试。
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


@app.route("/api/v2/chat", methods=["POST"])
def chat_endpoint():
    """
    问答接口

    请求体 (JSON):
        {
            "session_id": "abc123",   // 可选，不传则自动生成
            "message": "帮我找西二旗附近的两居室"  // 必填
        }

    响应体 (JSON):
        {
            "session_id": "abc123",
            "response": "好的，我来帮您查找...",
            "status": "success",
            "tool_results": [...],
            "timestamp": 1709251200,
            "duration_ms": 1234
        }

    curl 调试示例:
        curl -X POST http://localhost:5000/api/v2/chat \
            -H "Content-Type: application/json" \
            -d "{\"session_id\":\"test1\",\"message\":\"帮我找西二旗附近3000以下的一居室\"}"
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

    logger.info(">>> 请求 POST /api/v2/chat session=%s message=%s", session_id, message[:80])

    try:
        result = chat(session_id, message)
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


if __name__ == "__main__":
    logger.info("租房Agent服务启动 host=0.0.0.0 port=5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
