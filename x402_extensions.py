"""
x402 Bazaar Discovery Extension — Python implementation
等效于 @x402/extensions 中的 declareDiscoveryExtension() + bazaarResourceServerExtension()
遵循 JSON Schema 2020-12 格式
"""

import copy


def declare_discovery_extension(
    *,
    input_data: dict,
    input_schema: dict,
    body_type: str | None = None,
    output: dict | None = None,
    description: str = "",
) -> dict:
    """
    创建 Bazaar Discovery Extension 元数据。

    参数：
        input_data: 示例输入值（GET 为 queryParams, POST 为 body）
        input_schema: JSON Schema 描述输入结构
        body_type: "json" | "form-data"（仅 POST/PUT/PATCH 需要）
        output: 可选，包含 "example" 和/或 "schema"
        description: 端点描述

    返回：
        {"bazaar": {"info": {...}, "schema": {...}}}
    """
    if body_type:
        method = "POST"
        input_key = "body"
    else:
        method = "GET"
        input_key = "queryParams"

    info: dict = {
        "input": {
            "type": "http",
            "method": method,
            input_key: input_data,
        }
    }

    if description:
        info["description"] = description

    if output:
        info["output"] = {}
        if "example" in output:
            info["output"]["example"] = output["example"]
        if "schema" in output:
            info["output"]["schema"] = output["schema"]

    # --- 构建 info schema (JSON Schema 2020-12) ---
    input_props = {
        "type": {"const": "http"},
        "method": {"const": method},
        input_key: {
            "type": "object",
            "properties": input_schema.get("properties", {}),
            "required": input_schema.get("required", []),
            "additionalProperties": input_schema.get("additionalProperties", True),
        },
    }
    input_required = ["type", "method", input_key]

    info_properties: dict = {
        "input": {
            "type": "object",
            "properties": input_props,
            "required": input_required,
            "additionalProperties": False,
        }
    }
    info_required = ["input"]

    if description:
        info_properties["description"] = {"type": "string"}

    if output and "schema" in output:
        info_properties["output"] = output["schema"]
        info_required.append("output")

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "info": {
                "type": "object",
                "properties": info_properties,
                "required": info_required,
            },
            "schema": {"type": "object"},
        },
        "required": ["info", "schema"],
    }

    return {
        "bazaar": {
            "info": info,
            "schema": schema,
        }
    }


def bazaar_resource_server_extension(
    bazaar_ext: dict, request_args: dict
) -> dict:
    """
    在请求时用实际参数丰富 bazaar 发现扩展。
    等效于 @x402/extensions 的 bazaarResourceServerExtension。

    参数：
        bazaar_ext: declare_discovery_extension() 返回的扩展字典
        request_args: 实际的请求参数（query params 或 body）

    返回：
        包含具体请求参数值的更新后扩展
    """
    ext = copy.deepcopy(bazaar_ext)
    info = ext["bazaar"]["info"]

    # 判断是 query 还是 body
    input_info = info.get("input", {})
    if "queryParams" in input_info:
        input_key = "queryParams"
    elif "body" in input_info:
        input_key = "body"
    else:
        return ext

    # 用实际请求参数覆盖示例
    filtered_args = {k: v for k, v in request_args.items() if v is not None and v != ""}

    # 类型转换: days -> int, travel -> bool
    typed_args = {}
    for k, v in filtered_args.items():
        if k == "days":
            try:
                typed_args[k] = int(v)
            except ValueError:
                typed_args[k] = v
        elif k == "travel":
            typed_args[k] = v.lower() == "true"
        else:
            typed_args[k] = v

    if typed_args:
        info["input"][input_key] = typed_args

    return ext
