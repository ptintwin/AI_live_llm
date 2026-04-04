# -*- coding: utf-8 -*-
"""测试停止会话接口"""
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

def get_session_id():
    """从文件读取session_id"""
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as f:
            session_id = f.read().strip()
            if session_id:
                print(f"从文件读取Session ID: {session_id}")
                return session_id
    print("未找到有效的Session ID")
    return None

def test_stop_session():
    """测试停止会话"""
    session_id = get_session_id()
    if not session_id:
        print("会话ID无效，跳过停止会话测试")
        return
    resp = requests.post(f"{BASE_URL}/stop_session", json={
        "session_id": session_id
    })
    if resp.status_code == 200:
        print("停止会话：", resp.json())
    else:
        print(f"停止会话失败，状态码：{resp.status_code}")

if __name__ == "__main__":
    test_health()
    test_stop_session()