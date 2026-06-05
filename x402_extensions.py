"""
x402 Bazaar Discovery Extension — Python implementation
等效于 @x402/extensions v2.14.0 中的 declareDiscoveryExtension + bazaarResourceServerExtension

关键设计：
  - extensions.bazaar = { info: {...}, schema: {...} }
  - schema 是用来 validate(info) 的，即 ajv.compile(schema)(info)
  - 所以 schema.required = ["input"]，info 必须有 input 字段
  - output 必须有 type: "json" 和可选的 example
"""

import copy


def _create_query_discovery_extension(
    *,
    method: str,
    input_data: dict,
    input_schema: dict,
    output: dict | None = None,
) -> dict:
    """创建 HTTP GET 查询型发现扩展（等效 createQueryDiscoveryExtension）"""
    # --- info ---
    info: dict = {
        "input": {
            "type": "http",
            "method": method,
            "queryParams": input_data,
        }
    }
    if output and "example" in output:
        info["output"] = {
            "type": "json",
            "example": output["example"],
        }

    # --- schema (验证 info 用) ---
    schema_properties: dict = {
        "input": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "const": "http"},
                "method": {"type": "string", "enum": ["GET", "HEAD", "DELETE"]},
                "queryParams": {
                    "type": "object",
                    **input_schema,
                },
            },
            "required": ["type", "method"],
            "additionalProperties": False,
        },
    }

    if output and "example" in output:
        schema_properties["output"] = {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "example": {
                    "type": "object",
                    **(output.get("schema") or {}),
                },
            },
            "required": ["type"],
        }

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": schema_properties,
        "required": ["input"],
    }

    return {"info": info, "schema": schema}


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

    等效 @x402/extensions 的 declareDiscoveryExtension()。
    返回 { bazaar: { info: {...}, schema: {...} } }。

    参数:
        input_data: 示例输入值（GET 为 queryParams 对象）
        input_schema: JSON Schema 描述 queryParams 结构
        body_type: 设置后使用 POST body 模式（暂未完整实现）
        output: 可选 { "example": ..., "schema": ... }
        description: 暂未使用，保留兼容
    """
    if body_type:
        method = "POST"
    else:
        method = "GET"

    ext = _create_query_discovery_extension(
        method=method,
        input_data=input_data,
        input_schema=input_schema,
        output=output,
    )
    return {"bazaar": ext}


def bazaar_resource_server_extension(
    bazaar_ext: dict, request_args: dict
) -> dict:
    """
    在请求时用实际参数丰富 bazaar 发现扩展。
    等效 @x402/extensions 的 bazaarResourceServerExtension。

    参数：
        bazaar_ext: declare_discovery_extension() 返回值
        request_args: 实际请求参数字典

    返回：
        method 被缩小为实际 HTTP method，queryParams 被替换为实际参数
    """
    ext = copy.deepcopy(bazaar_ext)
    info = ext["bazaar"]["info"]
    schema = ext["bazaar"]["schema"]

    input_info = info.get("input", {})
    input_key = "queryParams" if "queryParams" in input_info else "body" if "body" in input_info else None
    if not input_key:
        return ext

    # 类型转换
    typed_args = {}
    for k, v in request_args.items():
        if v is None or v == "":
            continue
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

    # 缩小 schema method 枚举 (bazaarResourceServerExtension 核心逻辑)
    schema_input = schema.get("properties", {}).get("input", {})
    schema_method = schema_input.get("properties", {}).get("method", {})
    if schema_method and "enum" in schema_method:
        schema_method["enum"] = [info["input"]["method"]]

    return ext
