"""
test_app.py - 测试 Flask HTTP 接口
"""

import json
import sys
import os
import time
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
        """正常请求应返回 200 和新格式响应"""
        mock_chat.return_value = {
            "response": "你好，有什么可以帮您？",
            "status": "success",
            "tool_results": [],
        }
        resp = self.client.post(
            "/chat",
            json={"session_id": "s1", "message": "你好"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["session_id"], "s1")
        self.assertEqual(data["response"], "你好，有什么可以帮您？")
        self.assertEqual(data["status"], "success")
        self.assertIsInstance(data["tool_results"], list)
        mock_chat.assert_called_once_with("s1", "你好")

    @patch("app.chat")
    def test_auto_generate_session_id(self, mock_chat):
        """不传 session_id 时应自动生成"""
        mock_chat.return_value = {
            "response": "hello",
            "status": "success",
            "tool_results": [],
        }
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
        """响应体应包含所有必需字段"""
        mock_chat.return_value = {
            "response": "回复内容",
            "status": "success",
            "tool_results": [],
        }
        resp = self.client.post(
            "/chat",
            json={"session_id": "abc", "message": "测试"},
        )
        data = resp.get_json()
        # 验证所有必需字段存在
        self.assertIn("session_id", data)
        self.assertIn("response", data)
        self.assertIn("status", data)
        self.assertIn("tool_results", data)
        self.assertIn("timestamp", data)
        self.assertIn("duration_ms", data)

    @patch("app.chat")
    def test_timestamp_is_int(self, mock_chat):
        """timestamp 应为 int 类型"""
        mock_chat.return_value = {
            "response": "ok",
            "status": "success",
            "tool_results": [],
        }
        resp = self.client.post(
            "/chat",
            json={"session_id": "ts_test", "message": "时间"},
        )
        data = resp.get_json()
        self.assertIsInstance(data["timestamp"], int)
        # 时间戳应在合理范围内（2020年之后）
        self.assertGreater(data["timestamp"], 1577836800)

    @patch("app.chat")
    def test_duration_ms_is_int(self, mock_chat):
        """duration_ms 应为 int 类型且非负"""
        mock_chat.return_value = {
            "response": "ok",
            "status": "success",
            "tool_results": [],
        }
        resp = self.client.post(
            "/chat",
            json={"session_id": "dur_test", "message": "耗时"},
        )
        data = resp.get_json()
        self.assertIsInstance(data["duration_ms"], int)
        self.assertGreaterEqual(data["duration_ms"], 0)

    @patch("app.chat")
    def test_tool_results_in_response(self, mock_chat):
        """工具调用结果应正确返回 {name, success, output} 格式"""
        mock_chat.return_value = {
            "response": "找到房源",
            "status": "success",
            "tool_results": [
                {
                    "name": "get_houses_by_platform",
                    "success": True,
                    "output": '{"data": []}',
                }
            ],
        }
        resp = self.client.post(
            "/chat",
            json={"session_id": "tool_test", "message": "找房"},
        )
        data = resp.get_json()
        self.assertEqual(len(data["tool_results"]), 1)
        tr = data["tool_results"][0]
        self.assertEqual(tr["name"], "get_houses_by_platform")
        self.assertTrue(tr["success"])
        self.assertIn("output", tr)

    # --------------------------------------------------
    # 异常处理
    # --------------------------------------------------

    @patch("app.chat")
    def test_internal_error_returns_500(self, mock_chat):
        """agent.chat 抛异常时应返回 500 且响应体包含所有字段"""
        mock_chat.side_effect = RuntimeError("LLM 连接失败")
        resp = self.client.post(
            "/chat",
            json={"session_id": "s2", "message": "你好"},
        )
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("LLM 连接失败", data["error"])
        # 500 响应也应包含标准字段
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["session_id"], "s2")
        self.assertIsInstance(data["timestamp"], int)
        self.assertIsInstance(data["duration_ms"], int)
        self.assertEqual(data["tool_results"], [])
        self.assertEqual(data["response"], "")


if __name__ == "__main__":
    unittest.main()
