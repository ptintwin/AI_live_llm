# -*- coding: utf-8 -*-
"""测试互动接口"""
import requests
import os
import asyncio
import datetime
from yaml import safe_load

# 加载配置
config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
with open(config_path, "r", encoding="utf-8") as f:
    config = safe_load(f)

# 构建BASE_URL
BASE_URL = f"http://{config['server']['host']}:{config['server']['port']}"
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


async def send_danmu_request(session_id, danmu_list, request_number):
    """发送弹幕请求"""
    print(f"发送第{request_number}次弹幕请求，请求开始时间：{datetime.datetime.now()}")
    print(f"弹幕列表：{danmu_list}")

    resp = requests.post(f"{BASE_URL}/live_danmu", json={
        "session_id": session_id,
        "danmu_list": danmu_list
    })

    if resp.status_code == 200:
        print(f"第{request_number}次弹幕处理回复：", resp.json())
    else:
        print(f"第{request_number}次弹幕处理失败，状态码：{resp.status_code}")
    print(f"第{request_number}次弹幕处理结束时间：{datetime.datetime.now()}")


async def test_live_danmu():
    """测试直播间弹幕处理"""
    session_id = get_session_id()
    if not session_id:
        print("会话ID无效，跳过弹幕测试")
        return

    # 第一次请求：弹幕最高等级为"重要"类，弹幕数5条
    # 重要类包括：礼物灯牌类、专业提问类、游戏相关普通问题
    base_time = datetime.datetime.now()
    danmu_times = [
        base_time.strftime("%Y-%m-%d %H:%M:%S"),
        (base_time + datetime.timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S"),
        (base_time + datetime.timedelta(seconds=1.5)).strftime("%Y-%m-%d %H:%M:%S"),
        (base_time + datetime.timedelta(seconds=2)).strftime("%Y-%m-%d %H:%M:%S"),
        (base_time + datetime.timedelta(seconds=2.5)).strftime("%Y-%m-%d %H:%M:%S")
    ]

    # 第一次请求的弹幕列表（最高等级为"重要"类）
    first_danmu_list = [
        {
            "username": "黑****",
            "content": "这个职业怎么加点？",  # 专业提问类（重要）
            "type": "question",
            "danmu_time": danmu_times[0]
        },
        {
            "username": "向**",
            "content": "点亮了粉丝灯牌",  # 礼物灯牌类（重要）
            "type": "gift",
            "danmu_time": danmu_times[1]
        },
        {
            "username": "累***",
            "content": "游戏内一天能赚多少钱？",  # 游戏相关普通问题（重要）
            "type": "question",
            "danmu_time": danmu_times[2]
        },
        {
            "username": "五*",
            "content": "主播好厉害！",  # 其它闲聊问题（一般）
            "type": "question",
            "danmu_time": danmu_times[3]
        },
        {
            "username": "娃******",
            "content": "来了",  # 进入直播间类（一般）
            "type": "enter",
            "danmu_time": danmu_times[4]
        }
    ]

    # 发送第一次请求
    await send_danmu_request(session_id, first_danmu_list, 1)

    # 等待3秒钟
    print("等待10秒钟...")
    await asyncio.sleep(10)

    # 第二次请求：弹幕最高等级为"非常重要"类，弹幕数3条
    # 非常重要类包括：充值类问题、下载类问题
    second_base_time = base_time + datetime.timedelta(seconds=3)
    second_danmu_times = [
        second_base_time.strftime("%Y-%m-%d %H:%M:%S"),
        (second_base_time + datetime.timedelta(seconds=0.5)).strftime("%Y-%m-%d %H:%M:%S"),
        (second_base_time + datetime.timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    ]

    # 第二次请求的弹幕列表（最高等级为"非常重要"类）
    second_danmu_list = [
        {
            "username": "张**",
            "content": "怎么下载游戏？",  # 下载类问题（非常重要）
            "type": "question",
            "danmu_time": second_danmu_times[0]
        },
        {
            "username": "玩***",
            "content": "充值有什么优惠？",  # 充值类问题（非常重要）
            "type": "question",
            "danmu_time": second_danmu_times[1]
        },
        {
            "username": "我*",
            "content": "送出了超级火箭",  # 礼物灯牌类（重要）
            "type": "gift",
            "danmu_time": second_danmu_times[2]
        }
    ]

    # 发送第二次请求
    await send_danmu_request(session_id, second_danmu_list, 2)


if __name__ == "__main__":
    test_health()
    asyncio.run(test_live_danmu())