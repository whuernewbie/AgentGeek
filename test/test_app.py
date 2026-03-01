"""
test_app.py - 测试 Flask HTTP 接口
"""

import json
import sys
import os
import unittest
from unittest.mock import patch

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import setup_logging

setup_logging()

from app import app


class TestChatEndpoint(unittest.TestCase):
    """POST /chat 接口测试"""

    def setUp(self):
        """每个测试前创建 Flask 测试客户端"""
        app.config["TESTING"] = True
        self.client = app.test_client()

    # --------------------------------------------------
    # 参数校验
    # --------------------------------------------------

    def test_non_json_body_returns_400(self):
        """请求体不是 JSON 时应返回 400"""
        resp = self.client.post(
            "/chat",
            data="not json",
            content_type="text/plain",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("JSON", data["error"])

    def test_empty_message_returns_400(self):
        """message 为空时应返回 400"""
        resp = self.client.post(
            "/chat",
            json={"session_id": "test", "message": ""},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("message", data["error"])

    def test_missing_message_returns_400(self):
        """没有 message 字段时应返回 400"""
        resp = self.client.post(
            "/chat",
            json={"session_id": "test"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_whitespace_only_message_returns_400(self):
        """message 仅含空格时应返回 400"""
        resp = self.client.post(
            "/chat",
            json={"session_id": "test", "message": "   "},
        )
        self.assertEqual(resp.status_code, 400)

    # --------------------------------------------------
    # 正常请求
    # --------------------------------------------------

    @patch("app.chat")
    def test_normal_request_returns_200(self, mock_chat):
        """正常请求应返回 200 和 reply"""
        mock_chat.return_value = "你好，有什么可以帮您？"
        resp = self.client.post(
            "/chat",
            json={"session_id": "s1", "message": "你好"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["session_id"], "s1")
        self.assertEqual(data["reply"], "你好，有什么可以帮您？")
        mock_chat.assert_called_once_with("s1", "你好")

    @patch("app.chat")
    def test_auto_generate_session_id(self, mock_chat):
        """不传 session_id 时应自动生成"""
        mock_chat.return_value = "hello"
        resp = self.client.post(
            "/chat",
            json={"message": "hi"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("session_id", data)
        self.assertTrue(len(data["session_id"]) > 0)

    @patch("app.chat")
    def test_response_json_structure(self, mock_chat):
        """响应体应包含 session_id 和 reply 两个字段"""
        mock_chat.return_value = "回复内容"
        resp = self.client.post(
            "/chat",
            json={"session_id": "abc", "message": "测试"},
        )
        data = resp.get_json()
        self.assertIn("session_id", data)
        self.assertIn("reply", data)

    # --------------------------------------------------
    # 异常处理
    # --------------------------------------------------

    @patch("app.chat")
    def test_internal_error_returns_500(self, mock_chat):
        """agent.chat 抛异常时应返回 500"""
        mock_chat.side_effect = RuntimeError("LLM 连接失败")
        resp = self.client.post(
            "/chat",
            json={"session_id": "s2", "message": "你好"},
        )
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("LLM 连接失败", data["error"])


if __name__ == "__main__":
    unittest.main()
