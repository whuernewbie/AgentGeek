"""
test_tools.py - 测试工具定义与执行
包括工具定义格式、路由表完整性、execute_tool 执行逻辑。
"""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import setup_logging

setup_logging()

from tools import TOOLS, _TOOL_ROUTES, execute_tool


class TestToolDefinitions(unittest.TestCase):
    """工具定义格式测试"""

    def test_tools_is_list(self):
        """TOOLS 应是列表"""
        self.assertIsInstance(TOOLS, list)

    def test_tools_count(self):
        """应有 15 个工具定义"""
        self.assertEqual(len(TOOLS), 15)

    def test_each_tool_has_required_fields(self):
        """每个工具应有 type 和 function 字段"""
        for tool in TOOLS:
            self.assertEqual(tool["type"], "function")
            self.assertIn("function", tool)
            func = tool["function"]
            self.assertIn("name", func)
            self.assertIn("description", func)
            self.assertIn("parameters", func)

    def test_each_tool_has_valid_parameters_schema(self):
        """每个工具的 parameters 应为合法的 JSON Schema"""
        for tool in TOOLS:
            params = tool["function"]["parameters"]
            self.assertEqual(params["type"], "object")
            self.assertIn("properties", params)
            self.assertIn("required", params)
            self.assertIsInstance(params["required"], list)

    def test_tool_names_unique(self):
        """工具名应不重复"""
        names = [t["function"]["name"] for t in TOOLS]
        self.assertEqual(len(names), len(set(names)))

    def test_known_tools_exist(self):
        """关键工具名应存在"""
        names = {t["function"]["name"] for t in TOOLS}
        expected = {
            "get_landmarks",
            "get_landmark_by_name",
            "search_landmarks",
            "get_house_by_id",
            "get_houses_by_platform",
            "get_houses_nearby",
            "rent_house",
            "terminate_rental",
            "take_offline",
        }
        for name in expected:
            self.assertIn(name, names, f"缺少工具: {name}")


class TestToolRoutes(unittest.TestCase):
    """工具路由表测试"""

    def test_routes_count_matches_tools(self):
        """路由表条数应与工具定义数一致"""
        self.assertEqual(len(_TOOL_ROUTES), len(TOOLS))

    def test_every_tool_has_route(self):
        """每个工具定义都应有对应路由"""
        for tool in TOOLS:
            name = tool["function"]["name"]
            self.assertIn(name, _TOOL_ROUTES, f"工具 {name} 无路由")

    def test_route_tuple_structure(self):
        """路由元组应为 (method, url_template, path_params, needs_user_id)"""
        for name, route in _TOOL_ROUTES.items():
            self.assertEqual(len(route), 4, f"路由 {name} 元组长度不为4")
            method, url, path_params, needs_uid = route
            self.assertIn(method, ("GET", "POST"), f"{name} 方法无效: {method}")
            self.assertTrue(url.startswith("/api/"), f"{name} URL 格式异常: {url}")
            self.assertIsInstance(path_params, list)
            self.assertIsInstance(needs_uid, bool)

    def test_landmark_routes_no_user_id(self):
        """地标接口不应要求 X-User-ID"""
        landmark_tools = ["get_landmarks", "get_landmark_by_name", "search_landmarks",
                          "get_landmark_by_id", "get_landmark_stats"]
        for name in landmark_tools:
            _, _, _, needs_uid = _TOOL_ROUTES[name]
            self.assertFalse(needs_uid, f"{name} 不应需要 X-User-ID")

    def test_house_routes_need_user_id(self):
        """房源接口应要求 X-User-ID"""
        house_tools = ["get_house_by_id", "get_houses_by_platform",
                       "rent_house", "terminate_rental", "take_offline"]
        for name in house_tools:
            _, _, _, needs_uid = _TOOL_ROUTES[name]
            self.assertTrue(needs_uid, f"{name} 应需要 X-User-ID")

    def test_action_routes_are_post(self):
        """租房/退租/下架操作应为 POST 方法"""
        for name in ["rent_house", "terminate_rental", "take_offline"]:
            method = _TOOL_ROUTES[name][0]
            self.assertEqual(method, "POST", f"{name} 应为 POST")

    def test_query_routes_are_get(self):
        """查询接口应为 GET 方法"""
        query_tools = ["get_landmarks", "get_house_by_id", "get_houses_by_platform",
                       "search_landmarks", "get_houses_nearby"]
        for name in query_tools:
            method = _TOOL_ROUTES[name][0]
            self.assertEqual(method, "GET", f"{name} 应为 GET")


class TestExecuteTool(unittest.TestCase):
    """execute_tool 执行逻辑测试"""

    def test_unknown_tool_returns_error(self):
        """调用未知工具应返回 success=False 的字典"""
        result = execute_tool("nonexistent_tool", {})
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        data = json.loads(result["output"])
        self.assertIn("error", data)
        self.assertIn("未知工具", data["error"])

    @patch("tools.requests.get")
    def test_get_landmarks_builds_correct_url(self, mock_get):
        """get_landmarks 应构造正确的 GET 请求"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        execute_tool("get_landmarks", {"category": "subway", "district": "海淀"})

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        self.assertIn("/api/landmarks", call_args[0][0])
        self.assertEqual(call_args[1]["params"], {"category": "subway", "district": "海淀"})

    @patch("tools.requests.get")
    def test_path_param_substitution(self, mock_get):
        """路径参数应正确替换"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {}}
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        execute_tool("get_house_by_id", {"house_id": "HF_2001"})

        url = mock_get.call_args[0][0]
        self.assertIn("/api/houses/HF_2001", url)
        self.assertNotIn("{house_id}", url)

    @patch("tools.requests.get")
    def test_user_id_header_added(self, mock_get):
        """需要 X-User-ID 的接口应带上该 header"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        execute_tool("get_house_by_id", {"house_id": "HF_001"})

        headers = mock_get.call_args[1]["headers"]
        self.assertIn("X-User-ID", headers)

    @patch("tools.requests.get")
    def test_no_user_id_for_landmarks(self, mock_get):
        """地标接口不应带 X-User-ID"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        execute_tool("get_landmarks", {})

        headers = mock_get.call_args[1]["headers"]
        self.assertNotIn("X-User-ID", headers)

    @patch("tools.requests.post")
    def test_rent_house_uses_post(self, mock_post):
        """rent_house 应使用 POST 方法"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": True}
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        execute_tool("rent_house", {"house_id": "HF_001", "listing_platform": "安居客"})

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        self.assertIn("/api/houses/HF_001/rent", url)
        self.assertEqual(mock_post.call_args[1]["params"], {"listing_platform": "安居客"})

    @patch("tools.requests.get")
    def test_request_exception_returns_error(self, mock_get):
        """网络异常时应返回 success=False 而不是抛异常"""
        import requests as req_lib
        mock_get.side_effect = req_lib.ConnectionError("连接被拒绝")

        result = execute_tool("get_landmarks", {})
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        data = json.loads(result["output"])
        self.assertIn("error", data)
        self.assertIn("请求失败", data["error"])

    @patch("tools.requests.get")
    def test_non_json_response_handled(self, mock_get):
        """API 返回非 JSON 时应优雅处理且 success=False"""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("No JSON")
        mock_resp.status_code = 502
        mock_resp.text = "Bad Gateway"
        mock_get.return_value = mock_resp

        result = execute_tool("get_landmarks", {})
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        data = json.loads(result["output"])
        self.assertEqual(data["status_code"], 502)
        self.assertEqual(data["body"], "Bad Gateway")

    @patch("tools.requests.get")
    def test_mixed_path_and_query_params(self, mock_get):
        """同时有路径参数和查询参数时应正确分离"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        execute_tool("get_landmark_by_name", {"name": "西二旗站"})

        url = mock_get.call_args[0][0]
        self.assertIn("/api/landmarks/name/西二旗站", url)
        # name 是路径参数，不应出现在 query_params 中
        self.assertEqual(mock_get.call_args[1]["params"], {})


if __name__ == "__main__":
    unittest.main()
