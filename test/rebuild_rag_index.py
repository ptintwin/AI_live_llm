#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试重建RAG向量库接口
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


def test_rebuild_rag_index(force=True):
    """测试重建RAG向量库接口"""
    print(f"\n测试重建RAG向量库接口，force: {force}")
    print(f"force=True: 强制重建（删除旧库，重新从文档解析入库）")
    print(f"force=False: 仅在向量库为空时构建")

    # 构造请求数据
    data = {
        "force": force
    }

    # 发送POST请求
    response = requests.post(f"{BASE_URL}/rebuild_rag_index", json=data)

    # 打印响应
    print(f"响应状态码: {response.status_code}")
    print(f"响应内容: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")

    # 检查响应
    if response.status_code == 200:
        result = response.json()
        if result.get("status") == "success":
            print("\n✅ 重建RAG向量库测试成功！")
            print(f"文档数量: {result.get('document_count')}")
            return result
        else:
            print("\n❌ 重建RAG向量库测试失败！")
            print(f"错误信息: {result.get('error')}")
    else:
        print("\n❌ 重建RAG向量库测试失败！")
        print(f"错误信息: {response.text}")

    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测试重建RAG向量库接口")
    parser.add_argument("--force", action="store_true", default=True,
                        help="是否强制重建（默认为True）")
    parser.add_argument("--no-force", action="store_false", dest="force",
                        help="仅在向量库为空时构建")
    args = parser.parse_args()

    test_rebuild_rag_index(args.force)