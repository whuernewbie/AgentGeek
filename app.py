"""
租房Agent HTTP 服务入口
提供 POST /chat 接口，通过 curl 调试。
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


@app.route("/chat", methods=["POST"])
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
            "reply": "好的，我来帮您查找..."
        }

    curl 调试示例:
        curl -X POST http://localhost:5000/chat \
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

    logger.info(">>> 请求 POST /chat session=%s message=%s", session_id, message[:80])

    try:
        reply = chat(session_id, message)
        elapsed = time.time() - start_time
        logger.info(
            "<<< 响应 session=%s 耗时=%.2fs reply=%s",
            session_id, elapsed, reply[:80],
        )
        return jsonify({"session_id": session_id, "reply": reply})
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            "!!! 异常 session=%s 耗时=%.2fs error=%s", session_id, elapsed, e,
            exc_info=True,
        )
        return jsonify({"error": f"处理失败: {str(e)}"}), 500


if __name__ == "__main__":
    logger.info("租房Agent服务启动 host=0.0.0.0 port=5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
