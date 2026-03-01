"""
工具定义与执行模块
将租房仿真API的OpenAPI规范转换为OpenAI function calling格式，
并提供工具执行函数。
"""

import json
import logging
import time

import requests

import config

logger = logging.getLogger(__name__)

# ============================================================
# OpenAI function calling 格式的工具定义
# ============================================================

TOOLS = [
    # -------------------- 地标类接口 --------------------
    {
        "type": "function",
        "function": {
            "name": "get_landmarks",
            "description": "获取地标列表，支持 category、district 同时筛选（取交集）。用于查地铁站、公司、商圈等地标。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "地标类别：subway(地铁)/company(公司)/landmark(商圈等)，不传则不过滤",
                    },
                    "district": {
                        "type": "string",
                        "description": "行政区，如 海淀、朝阳",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_landmark_by_name",
            "description": "按名称精确查询地标，如西二旗站、百度。返回地标 id、经纬度等，用于后续 nearby 查房。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "地标名称，如 西二旗站、国贸",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_landmarks",
            "description": "关键词模糊搜索地标，q 必填。支持 category、district 同时筛选，多条件取交集。",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {
                        "type": "string",
                        "description": "搜索关键词，必填",
                    },
                    "category": {
                        "type": "string",
                        "description": "可选，限定类别：subway/company/landmark",
                    },
                    "district": {
                        "type": "string",
                        "description": "可选，限定行政区，如 海淀、朝阳",
                    },
                },
                "required": ["q"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_landmark_by_id",
            "description": "按地标 id 查询地标详情。",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "地标 ID，如 SS_001、LM_002",
                    },
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_landmark_stats",
            "description": "获取地标统计信息（总数、按类别分布等）。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    # -------------------- 房源查询类接口 --------------------
    {
        "type": "function",
        "function": {
            "name": "get_house_by_id",
            "description": "根据房源 ID 获取单套房源详情。返回一条（安居客），便于解析。",
            "parameters": {
                "type": "object",
                "properties": {
                    "house_id": {
                        "type": "string",
                        "description": "房源 ID，如 HF_2001",
                    },
                },
                "required": ["house_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_house_listings",
            "description": "根据房源 ID 获取该房源在链家/安居客/58同城等各平台的全部挂牌记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "house_id": {
                        "type": "string",
                        "description": "房源 ID，如 HF_2001",
                    },
                },
                "required": ["house_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_houses_by_community",
            "description": "按小区名查询该小区下可租房源。默认每页 10 条、未传 listing_platform 时只返回安居客。",
            "parameters": {
                "type": "object",
                "properties": {
                    "community": {
                        "type": "string",
                        "description": "小区名，与数据一致，如 建清园(南区)、保利锦上(二期)",
                    },
                    "listing_platform": {
                        "type": "string",
                        "enum": ["链家", "安居客", "58同城"],
                        "description": "挂牌平台，不传则默认安居客",
                    },
                    "page": {
                        "type": "integer",
                        "description": "页码，默认 1",
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "每页条数，默认 10，最大 10000",
                    },
                },
                "required": ["community"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_houses_by_platform",
            "description": "查询可租房源，支持按挂牌平台筛选及多种条件过滤（区域、价格、户型、面积、地铁、朝向、电梯、装修、通勤时间等）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "listing_platform": {
                        "type": "string",
                        "enum": ["链家", "安居客", "58同城"],
                        "description": "挂牌平台，可选。不传则默认安居客",
                    },
                    "district": {
                        "type": "string",
                        "description": "行政区，逗号分隔，如 海淀,朝阳",
                    },
                    "area": {
                        "type": "string",
                        "description": "商圈，逗号分隔，如 西二旗,上地",
                    },
                    "min_price": {
                        "type": "integer",
                        "description": "最低月租金（元）",
                    },
                    "max_price": {
                        "type": "integer",
                        "description": "最高月租金（元）",
                    },
                    "bedrooms": {
                        "type": "string",
                        "description": "卧室数，逗号分隔，如 1,2",
                    },
                    "rental_type": {
                        "type": "string",
                        "description": "整租 或 合租",
                    },
                    "decoration": {
                        "type": "string",
                        "description": "精装/简装 等",
                    },
                    "orientation": {
                        "type": "string",
                        "description": "朝向，如 朝南、南北",
                    },
                    "elevator": {
                        "type": "string",
                        "description": "是否有电梯：true/false",
                    },
                    "min_area": {
                        "type": "integer",
                        "description": "最小面积（平米）",
                    },
                    "max_area": {
                        "type": "integer",
                        "description": "最大面积（平米）",
                    },
                    "property_type": {
                        "type": "string",
                        "description": "物业类型，如 住宅",
                    },
                    "subway_line": {
                        "type": "string",
                        "description": "地铁线路，如 13号线",
                    },
                    "max_subway_dist": {
                        "type": "integer",
                        "description": "最大地铁距离（米），近地铁建议 800",
                    },
                    "subway_station": {
                        "type": "string",
                        "description": "地铁站名，如 车公庄站",
                    },
                    "utilities_type": {
                        "type": "string",
                        "description": "水电类型，如 民水民电",
                    },
                    "available_from_before": {
                        "type": "string",
                        "description": "可入住日期上限，YYYY-MM-DD（如 2026-03-10）",
                    },
                    "commute_to_xierqi_max": {
                        "type": "integer",
                        "description": "到西二旗通勤时间上限（分钟）",
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "排序字段：price/area/subway",
                    },
                    "sort_order": {
                        "type": "string",
                        "description": "asc 或 desc",
                    },
                    "page": {
                        "type": "integer",
                        "description": "页码，默认 1",
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "每页条数，默认 10，最大 10000",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_nearby_landmarks",
            "description": "查询某小区周边某类地标（商超/公园），按距离排序。用于回答「附近有没有商场/公园」。",
            "parameters": {
                "type": "object",
                "properties": {
                    "community": {
                        "type": "string",
                        "description": "小区名，用于定位基准点",
                    },
                    "type": {
                        "type": "string",
                        "description": "地标类型：shopping(商超) 或 park(公园)，不传则不过滤",
                    },
                    "max_distance_m": {
                        "type": "number",
                        "description": "最大距离（米），默认 3000",
                    },
                },
                "required": ["community"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_houses_nearby",
            "description": "以地标为圆心，查询在指定距离内的可租房源，返回带直线距离、步行距离、步行时间。需先通过地标接口获得 landmark_id。",
            "parameters": {
                "type": "object",
                "properties": {
                    "landmark_id": {
                        "type": "string",
                        "description": "地标 ID 或地标名称（支持按名称查找）",
                    },
                    "max_distance": {
                        "type": "number",
                        "description": "最大直线距离（米），默认 2000",
                    },
                    "listing_platform": {
                        "type": "string",
                        "enum": ["链家", "安居客", "58同城"],
                        "description": "挂牌平台，不传则默认安居客",
                    },
                    "page": {
                        "type": "integer",
                        "description": "页码，默认 1",
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "每页条数，默认 10，最大 10000",
                    },
                },
                "required": ["landmark_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_house_stats",
            "description": "获取房源统计信息（总套数、按状态/行政区/户型分布、价格区间等）。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    # -------------------- 租房操作类接口 --------------------
    {
        "type": "function",
        "function": {
            "name": "rent_house",
            "description": "将该房源设为已租。需传入房源 ID 与 listing_platform（必填）以明确租赁哪个平台。",
            "parameters": {
                "type": "object",
                "properties": {
                    "house_id": {
                        "type": "string",
                        "description": "房源 ID，如 HF_2001",
                    },
                    "listing_platform": {
                        "type": "string",
                        "enum": ["链家", "安居客", "58同城"],
                        "description": "必填。明确租赁哪个平台",
                    },
                },
                "required": ["house_id", "listing_platform"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminate_rental",
            "description": "将该房源恢复为可租（退租）。需传入房源 ID 与 listing_platform（必填）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "house_id": {
                        "type": "string",
                        "description": "房源 ID，如 HF_2001",
                    },
                    "listing_platform": {
                        "type": "string",
                        "enum": ["链家", "安居客", "58同城"],
                        "description": "必填。明确操作哪个平台",
                    },
                },
                "required": ["house_id", "listing_platform"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_offline",
            "description": "将该房源设为下架。需传入房源 ID 与 listing_platform（必填）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "house_id": {
                        "type": "string",
                        "description": "房源 ID，如 HF_2001",
                    },
                    "listing_platform": {
                        "type": "string",
                        "enum": ["链家", "安居客", "58同城"],
                        "description": "必填。明确操作哪个平台",
                    },
                },
                "required": ["house_id", "listing_platform"],
            },
        },
    },
]

# ============================================================
# 工具路由表：工具名 -> (HTTP方法, URL模板, path参数列表, 是否需要X-User-ID)
# ============================================================

_TOOL_ROUTES = {
    # 地标接口（不需要 X-User-ID）
    "get_landmarks": ("GET", "/api/landmarks", [], False),
    "get_landmark_by_name": ("GET", "/api/landmarks/name/{name}", ["name"], False),
    "search_landmarks": ("GET", "/api/landmarks/search", [], False),
    "get_landmark_by_id": ("GET", "/api/landmarks/{id}", ["id"], False),
    "get_landmark_stats": ("GET", "/api/landmarks/stats", [], False),
    # 房源查询接口（需要 X-User-ID）
    "get_house_by_id": ("GET", "/api/houses/{house_id}", ["house_id"], True),
    "get_house_listings": (
        "GET",
        "/api/houses/listings/{house_id}",
        ["house_id"],
        True,
    ),
    "get_houses_by_community": ("GET", "/api/houses/by_community", [], True),
    "get_houses_by_platform": ("GET", "/api/houses/by_platform", [], True),
    "get_nearby_landmarks": ("GET", "/api/houses/nearby_landmarks", [], True),
    "get_houses_nearby": ("GET", "/api/houses/nearby", [], True),
    "get_house_stats": ("GET", "/api/houses/stats", [], True),
    # 租房操作接口（需要 X-User-ID）
    "rent_house": ("POST", "/api/houses/{house_id}/rent", ["house_id"], True),
    "terminate_rental": (
        "POST",
        "/api/houses/{house_id}/terminate",
        ["house_id"],
        True,
    ),
    "take_offline": ("POST", "/api/houses/{house_id}/offline", ["house_id"], True),
}


def execute_tool(tool_name: str, arguments: dict) -> dict:
    """
    执行指定工具调用，返回包含成功标志和输出内容的字典。

    Args:
        tool_name: 工具名称（对应 operationId）
        arguments: 工具参数字典

    Returns:
        dict: {
            "success": bool,   # 调用是否成功
            "output": str,     # 工具调用的输出内容（JSON 字符串）
        }
    """
    route = _TOOL_ROUTES.get(tool_name)
    if route is None:
        logger.warning("未知工具调用: %s", tool_name)
        output = json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)
        return {"success": False, "output": output}

    method, url_template, path_params, needs_user_id = route

    # 构造 URL：替换路径参数
    url_path = url_template
    query_params = {}

    for key, value in arguments.items():
        if key in path_params:
            url_path = url_path.replace("{" + key + "}", str(value))
        else:
            query_params[key] = value

    url = config.HOUSING_API_BASE.rstrip("/") + url_path

    # 构造请求头
    headers = {"Content-Type": "application/json"}
    if needs_user_id:
        headers["X-User-ID"] = config.HOUSING_USER_ID

    logger.info("工具调用 [%s] %s %s params=%s", tool_name, method, url, query_params)

    # 发送请求
    start_time = time.time()
    try:
        if method == "GET":
            resp = requests.get(url, params=query_params, headers=headers, timeout=30)
        else:  # POST
            resp = requests.post(url, params=query_params, headers=headers, timeout=30)

        elapsed = time.time() - start_time
        logger.info(
            "工具响应 [%s] status=%d 耗时=%.2fs", tool_name, resp.status_code, elapsed
        )

        # 尝试解析 JSON 响应
        try:
            result = resp.json()
        except ValueError:
            result = {"status_code": resp.status_code, "body": resp.text}

        result_str = json.dumps(result, ensure_ascii=False)
        logger.debug("工具结果 [%s] %s", tool_name, result_str[:500])

        success = 200 <= resp.status_code < 300
        return {"success": success, "output": result_str}

    except requests.RequestException as e:
        elapsed = time.time() - start_time
        logger.error("工具调用失败 [%s] 耗时=%.2fs 错误: %s", tool_name, elapsed, e)
        output = json.dumps({"error": f"请求失败: {str(e)}"}, ensure_ascii=False)
        return {"success": False, "output": output}
