#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试清空RAG向量库接口
"""
import json
import requests
import os
from yaml import safe_load

# 加载配置
config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
with open(config_path, "r", encoding="utf-8") as f:
    config = safe_load(f)

# 构建BASE_URL
BASE_URL = f"http://{config['server']['host']}:{config['server']['port']}"


def test_clear_rag_index():
    """测试清空RAG向量库接口"""
    print("\n测试清空RAG向量库接口")
    print("⚠️  警告：此操作将清空所有RAG向量库数据，请谨慎操作！")

    # 确认操作
    confirm = input("确认要清空RAG向量库吗？(输入 'yes' 确认): ")
    if confirm.lower() != "yes":
        print("操作已取消")
        return None

    # 发送POST请求
    response = requests.post(f"{BASE_URL}/clear_rag_index")

    # 打印响应
    print(f"响应状态码: {response.status_code}")
    print(f"响应内容: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")

    # 检查响应
    if response.status_code == 200:
        result = response.json()
        if result.get("status") == "success":
            print("\n✅ 清空RAG向量库测试成功！")
            print(f"消息: {result.get('message')}")
            return result
        else:
            print("\n❌ 清空RAG向量库测试失败！")
            print(f"错误信息: {result.get('error')}")
    else:
        print("\n❌ 清空RAG向量库测试失败！")
        print(f"错误信息: {response.text}")

    return None


if __name__ == "__main__":
    test_clear_rag_index()