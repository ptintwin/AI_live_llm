# -*- coding: utf-8 -*-
"""测试互动接口"""
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

def test_live_danmu():
    """测试直播间弹幕处理"""
    session_id = get_session_id()
    if not session_id:
        print("会话ID无效，跳过弹幕测试")
        return
    import datetime
    # 生成不同的时间戳，整体时差不超过3秒
    base_time = datetime.datetime.now()
    danmu_times = [
        base_time.strftime("%Y-%m-%d %H:%M:%S"),
        (base_time + datetime.timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S"),
        (base_time + datetime.timedelta(seconds=1.5)).strftime("%Y-%m-%d %H:%M:%S"),
        (base_time + datetime.timedelta(seconds=2)).strftime("%Y-%m-%d %H:%M:%S"),
        (base_time + datetime.timedelta(seconds=2.5)).strftime("%Y-%m-%d %H:%M:%S")
    ]
    resp = requests.post(f"{BASE_URL}/live_danmu", json={
        "session_id": session_id,
        "danmu_list": [
        {
          "username": "王哥",
          "content": "游戏怎么下载？",
          "type": "question",
          "danmu_time": danmu_times[0]
        },
        {
          "username": "李哥",
          "content": "主播好厉害！",
          "type": "question",
          "danmu_time": danmu_times[1]
        },
        {
          "username": "大英雄",
          "content": "点亮了粉丝灯牌",
          "type": "gift",
          "danmu_time": danmu_times[2]
        },
        {
            "username": "小飞飞",
            "content": "来了",
            "type": "enter",
            "danmu_time": danmu_times[3]
        },
        {
            "username": "土豪哥",
            "content": "送出了豪华游艇！",
            "type": "gift",
            "danmu_time": danmu_times[4]
        }]
    })
    if resp.status_code == 200:
        print("弹幕处理回复：", resp.json())
    else:
        print(f"弹幕处理失败，状态码：{resp.status_code}")

if __name__ == "__main__":
    test_health()
    test_live_danmu()