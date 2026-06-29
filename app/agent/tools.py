from __future__ import annotations

import json


def format_alarm(record: dict | None) -> str:
    if not record:
        return "结构化故障码库中未找到该代码，将改用手册检索。"
    causes = json.loads(record["causes"]) if record.get("causes", "").startswith("[") else [record.get("causes", "")]
    checks = json.loads(record["checks"]) if record.get("checks", "").startswith("[") else [record.get("checks", "")]
    return (
        f"故障码 {record['code']}：{record['title']}。{record['meaning']}\n"
        f"可能原因：{'；'.join(filter(None, causes))}\n"
        f"建议核对：{'；'.join(filter(None, checks))}\n"
        f"结构化来源：{record.get('source', '')}"
    )


def format_parameter(record: dict | None, value: float | None = None) -> str:
    if not record:
        return "结构化参数库中未找到该参数，将改用手册检索。"
    def display_number(number) -> str:
        value_number = float(number)
        return str(int(value_number)) if value_number.is_integer() else str(value_number)

    minimum = display_number(record["minimum"])
    maximum = display_number(record["maximum"])
    result = f"参数 {record['name']}：允许范围 {minimum}到{maximum} {record['unit']}。{record['notes']}"
    if value is not None:
        inside = record["minimum"] <= value <= record["maximum"]
        result += f" 当前值 {value} {record['unit']} {'在' if inside else '不在'}该演示数据范围内。"
    result += f" 结构化来源：{record['source']}"
    return result


def format_verified_solution(record: dict | None) -> str:
    if not record:
        return ""
    return (
        f"已找到经用户确认的历史方案（方案ID {record['id']}，相似度 {record['similarity']}）：\n"
        f"历史问题：{record['problem']}\n"
        f"已验证方案：{record['solution']}\n"
        "该方案只作为优先参考，仍需核对本次设备型号、固件版本和原始手册证据。"
    )
