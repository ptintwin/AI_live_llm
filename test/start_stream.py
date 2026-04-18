# -*- coding: utf-8 -*-
"""测试开启直播接口"""
import requests
import os

BASE_URL = "http://127.0.0.1:8000"
SESSION_FILE = os.path.join(os.path.dirname(__file__), "session_id.txt")

def test_health():
    """测试健康检查"""
    resp = requests.get(f"{BASE_URL}/health_check")
    if resp.status_code == 200:
        print("健康检查：", resp.json())
    else:
        print(f"健康检查失败，状态码：{resp.status_code}")

def test_start_stream():
    """测试开启直播"""
    resp = requests.post(f"{BASE_URL}/start_stream", json={
        "room_id": "123456"
    })
    if resp.status_code == 200:
        data = resp.json()
        print("开启直播：", data)
        session_id = data.get("session_id")
        if session_id:
            # 保存session_id到文件
            with open(SESSION_FILE, "w") as f:
                f.write(session_id)
            print(f"Session ID已保存到: {SESSION_FILE}")
        return session_id
    else:
        print(f"开启直播失败，状态码：{resp.status_code}")
        return None

if __name__ == "__main__":
    test_health()
    test_start_stream()
