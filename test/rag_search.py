#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试RAG检索接口
"""
import json
import requests
import argparse
import os
from yaml import safe_load

# 加载配置
config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
with open(config_path, "r", encoding="utf-8") as f:
    config = safe_load(f)

# 构建BASE_URL
BASE_URL = f"http://{config['server']['host']}:{config['server']['port']}"


def test_rag_search(q, top_k=3):
    """测试RAG检索接口"""
    print(f"\n测试RAG检索接口")
    print(f"查询问题: {q}")
    print(f"返回结果数量: {top_k}")

    # 构造请求参数
    params = {
        "q": q,
        "top_k": top_k
    }

    # 发送GET请求
    response = requests.get(f"{BASE_URL}/rag_search", params=params)

    # 打印响应
    print(f"响应状态码: {response.status_code}")
    print(f"响应内容: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")

    # 检查响应
    if response.status_code == 200:
        result = response.json()
        if result.get("status") == "success":
            print("\n✅ RAG检索测试成功！")
            print(f"问题: {result.get('question')}")
            print(f"是否触发RAG: {result.get('trigger_rag')}")
            print(f"检索到的答案数量: {len(result.get('answers', []))}")
            return result
        else:
            print("\n❌ RAG检索测试失败！")
            print(f"错误信息: {result.get('error')}")
    else:
        print("\n❌ RAG检索测试失败！")
        print(f"错误信息: {response.text}")

    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测试RAG检索接口")
    parser.add_argument("--q", required=True, help="查询问题")
    parser.add_argument("--top-k", type=int, default=3, help="返回结果数量（默认为3）")
    args = parser.parse_args()

    test_rag_search(args.q, args.top_k)