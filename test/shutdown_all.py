# -*- coding: utf-8 -*-
"""测试关闭所有会话接口"""
import requests
import os
from yaml import safe_load

# 加载配置
config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
with open(config_path, "r", encoding="utf-8") as f:
    config = safe_load(f)

# 构建BASE_URL
BASE_URL = f"http://{config['server']['host']}:{config['server']['port']}"

def test_health():
    """测试健康检查"""
    resp = requests.get(f"{BASE_URL}/health_check")
    if resp.status_code == 200:
        print("健康检查：", resp.json())
    else:
        print(f"健康检查失败，状态码：{resp.status_code}")

def test_shutdown_all():
    """测试关闭所有会话"""
    resp = requests.get(f"{BASE_URL}/shutdown_all")
    if resp.status_code == 200:
        print("关闭所有会话：", resp.json())
    else:
        print(f"关闭所有会话失败，状态码：{resp.status_code}")


if __name__ == "__main__":
    test_health()
    test_shutdown_all()