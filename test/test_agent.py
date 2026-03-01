"""
test_agent.py - 测试 Agent 核心逻辑
包括对话存储、消息格式转换、Agent 循环。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import setup_logging

setup_logging()

import config
import agent


class TestConversationStorage(unittest.TestCase):
    """对话存储相关测试"""

    def setUp(self):
        """使用临时目录作为对话存储目录"""
        self.tmp_dir = tempfile.mkdtemp()
        self._original_dir = config.CONVERSATIONS_DIR
        config.CONVERSATIONS_DIR = self.tmp_dir

    def tearDown(self):
        """恢复配置并清理临时目录"""
        config.CONVERSATIONS_DIR = self._original_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_load_empty_session(self):
        """加载不存在的会话应返回空列表"""
        result = agent.load_conversation("nonexistent")
        self.assertEqual(result, [])

    def test_save_and_load(self):
        """保存后应能正确加载"""
        messages = [
            {"role": "user", "timestamp": "2026-03-01 10:00:00", "content": "你好"},
            {"role": "agent", "timestamp": "2026-03-01 10:00:01", "content": "你好！"},
        ]
        agent.save_conversation("sess1", messages)
        loaded = agent.load_conversation("sess1")
        self.assertEqual(loaded, messages)

    def test_save_creates_file(self):
        """保存对话应创建对应的 JSON 文件"""
        agent.save_conversation("sess2", [{"role": "user", "timestamp": "t", "content": "hi"}])
        path = os.path.join(self.tmp_dir, "sess2.json")
        self.assertTrue(os.path.exists(path))

    def test_save_file_is_valid_json(self):
        """保存的文件内容应是合法 JSON"""
        messages = [{"role": "user", "timestamp": "t", "content": "测试中文"}]
        agent.save_conversation("sess3", messages)
        path = os.path.join(self.tmp_dir, "sess3.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data[0]["content"], "测试中文")

    def test_save_file_utf8_no_ascii_escape(self):
        """保存的文件中中文不应被转义"""
        messages = [{"role": "user", "timestamp": "t", "content": "北京租房"}]
        agent.save_conversation("sess4", messages)
        path = os.path.join(self.tmp_dir, "sess4.json")
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertIn("北京租房", raw)
        self.assertNotIn("\\u", raw)

    def test_load_corrupted_file_returns_empty(self):
        """加载损坏的 JSON 文件应返回空列表"""
        path = os.path.join(self.tmp_dir, "bad.json")
        with open(path, "w") as f:
            f.write("not valid json{{{")
        result = agent.load_conversation("bad")
        self.assertEqual(result, [])

    def test_overwrite_existing_session(self):
        """多次保存同一 session 应覆盖"""
        agent.save_conversation("sess5", [{"role": "user", "timestamp": "t", "content": "first"}])
        agent.save_conversation("sess5", [{"role": "user", "timestamp": "t", "content": "second"}])
        loaded = agent.load_conversation("sess5")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["content"], "second")


class TestMessageConversion(unittest.TestCase):
    """消息格式转换测试"""

    def test_user_role_unchanged(self):
        """user 角色应保持不变"""
        stored = [{"role": "user", "timestamp": "t", "content": "hello"}]
        result = agent._stored_to_llm_messages(stored)
        self.assertEqual(result[0]["role"], "user")

    def test_agent_role_to_assistant(self):
        """agent 角色应转为 assistant"""
        stored = [{"role": "agent", "timestamp": "t", "content": "hi"}]
        result = agent._stored_to_llm_messages(stored)
        self.assertEqual(result[0]["role"], "assistant")

    def test_content_preserved(self):
        """content 应完整保留"""
        stored = [{"role": "user", "timestamp": "t", "content": "西二旗租房"}]
        result = agent._stored_to_llm_messages(stored)
        self.assertEqual(result[0]["content"], "西二旗租房")

    def test_timestamp_not_in_llm_message(self):
        """转换后的消息不应包含 timestamp"""
        stored = [{"role": "user", "timestamp": "2026-01-01 00:00:00", "content": "x"}]
        result = agent._stored_to_llm_messages(stored)
        self.assertNotIn("timestamp", result[0])

    def test_multi_turn_conversion(self):
        """多轮对话应正确转换"""
        stored = [
            {"role": "user", "timestamp": "t1", "content": "q1"},
            {"role": "agent", "timestamp": "t2", "content": "a1"},
            {"role": "user", "timestamp": "t3", "content": "q2"},
        ]
        result = agent._stored_to_llm_messages(stored)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(result[1]["role"], "assistant")
        self.assertEqual(result[2]["role"], "user")


class TestTimestamp(unittest.TestCase):
    """时间戳格式测试"""

    def test_timestamp_format(self):
        """时间戳应为 YYYY-MM-DD HH:MM:SS 格式"""
        ts = agent._now_timestamp()
        # 例: 2026-03-01 22:30:32
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class TestChatLoop(unittest.TestCase):
    """Agent chat 循环测试"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self._original_dir = config.CONVERSATIONS_DIR
        config.CONVERSATIONS_DIR = self.tmp_dir

    def tearDown(self):
        config.CONVERSATIONS_DIR = self._original_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("agent._call_llm")
    def test_simple_text_reply(self, mock_llm):
        """LLM 直接返回文本时应正确返回"""
        mock_llm.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "您好，请问有什么需要？",
                    }
                }
            ]
        }
        reply = agent.chat("test_simple", "你好")
        self.assertEqual(reply, "您好，请问有什么需要？")
        mock_llm.assert_called_once()

    @patch("agent._call_llm")
    def test_conversation_saved_after_reply(self, mock_llm):
        """回复后对话应被保存"""
        mock_llm.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        }
        agent.chat("test_save", "hello")
        loaded = agent.load_conversation("test_save")
        self.assertEqual(len(loaded), 2)  # user + agent
        self.assertEqual(loaded[0]["role"], "user")
        self.assertEqual(loaded[0]["content"], "hello")
        self.assertEqual(loaded[1]["role"], "agent")
        self.assertEqual(loaded[1]["content"], "ok")

    @patch("agent.execute_tool")
    @patch("agent._call_llm")
    def test_tool_call_then_reply(self, mock_llm, mock_tool):
        """LLM 先请求工具调用，再返回文本"""
        # 第1次调用：返回 tool_calls
        mock_llm.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_001",
                                    "function": {
                                        "name": "get_houses_by_platform",
                                        "arguments": '{"district": "海淀", "max_price": 5000}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            # 第2次调用：返回最终文本
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "为您找到以下房源...",
                        }
                    }
                ]
            },
        ]
        mock_tool.return_value = '{"data": [{"id": "HF_001", "price": 4500}]}'

        reply = agent.chat("test_tool", "海淀5000以内")
        self.assertEqual(reply, "为您找到以下房源...")
        self.assertEqual(mock_llm.call_count, 2)
        mock_tool.assert_called_once_with(
            "get_houses_by_platform", {"district": "海淀", "max_price": 5000}
        )

    @patch("agent._call_llm")
    def test_max_rounds_fallback(self, mock_llm):
        """达到最大轮次时应返回 fallback 消息"""
        # 每次都返回 tool_calls，永远不停
        mock_llm.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_loop",
                                "function": {
                                    "name": "get_landmark_stats",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                }
            ]
        }
        original_max = config.MAX_TOOL_ROUNDS
        config.MAX_TOOL_ROUNDS = 2  # 限制为2轮方便测试

        with patch("agent.execute_tool", return_value='{"data": []}'):
            reply = agent.chat("test_max_round", "测试")

        config.MAX_TOOL_ROUNDS = original_max
        self.assertIn("轮次过多", reply)

    @patch("agent._call_llm")
    def test_context_continuity(self, mock_llm):
        """同一 session 的第二次请求应包含历史对话"""
        mock_llm.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "reply1"}}]
        }
        agent.chat("test_ctx", "msg1")

        mock_llm.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "reply2"}}]
        }
        agent.chat("test_ctx", "msg2")

        # 检查第二次调用 LLM 时，messages 应包含历史
        second_call_messages = mock_llm.call_args_list[1][0][0]
        # system + user(msg1) + assistant(reply1) + user(msg2)
        self.assertEqual(len(second_call_messages), 4)
        self.assertEqual(second_call_messages[0]["role"], "system")
        self.assertEqual(second_call_messages[1]["content"], "msg1")
        self.assertEqual(second_call_messages[2]["content"], "reply1")
        self.assertEqual(second_call_messages[3]["content"], "msg2")


if __name__ == "__main__":
    unittest.main()
