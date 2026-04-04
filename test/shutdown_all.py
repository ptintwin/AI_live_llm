# -*- coding: utf-8 -*-
"""测试关闭所有会话接口"""
import requests

BASE_URL = "http://127.0.0.1:8000"

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
