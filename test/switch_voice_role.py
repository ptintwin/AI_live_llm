# -*- coding: utf-8 -*-
"""测试切换声音角色接口"""
import requests
import os
import argparse
import json
import random
from yaml import safe_load

# 加载配置
config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
with open(config_path, "r", encoding="utf-8") as f:
    config = safe_load(f)

# 构建BASE_URL
BASE_URL = f"http://{config['server']['host']}:{config['server']['port']}"
SESSION_FILE = os.path.join(os.path.dirname(__file__), "session_id.txt")
VOICE_IDS_FILE = os.path.join(os.path.dirname(__file__), "..", "audio_design", "voice_ids.json")

# 声音状态存储文件
VOICE_STATUS_FILE = os.path.join(os.path.dirname(__file__), "..", "audio_design", "voice_status.txt")


def load_voice_ids():
    """加载声音ID列表"""
    if os.path.exists(VOICE_IDS_FILE):
        with open(VOICE_IDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_voice_status():
    """加载声音状态"""
    if os.path.exists(VOICE_STATUS_FILE):
        try:
            with open(VOICE_STATUS_FILE, "r", encoding="utf-8") as f:
                status = {}
                for line in f:
                    line = line.strip()
                    if line:
                        session_id, voice_id = line.split(",", 1)
                        status[session_id] = voice_id
                return status
        except Exception as e:
            print(f"加载声音状态文件失败: {e}")
    return {}


def save_voice_status(status):
    """保存声音状态"""
    try:
        with open(VOICE_STATUS_FILE, "w", encoding="utf-8") as f:
            for session_id, voice_id in status.items():
                f.write(f"{session_id},{voice_id}\n")
    except Exception as e:
        print(f"保存声音状态文件失败: {e}")


def get_random_voice_id(session_id):
    """随机选择一个声音ID，避免与当前使用的相同"""
    voice_ids = load_voice_ids()
    if not voice_ids:
        print("未找到声音ID配置文件")
        return None

    # 获取当前会话的声音ID
    voice_status = load_voice_status()
    current_voice_id = voice_status.get(session_id)

    # 过滤掉当前使用的声音
    available_voices = [(name, voice_id) for name, voice_id in voice_ids.items() if voice_id != current_voice_id]

    if not available_voices:
        # 如果所有声音都被使用过，重新随机选择
        available_voices = list(voice_ids.items())

    # 随机选择一个声音
    name, voice_id = random.choice(available_voices)
    print(f"随机选择声音: {name} (ID: {voice_id})")
    return voice_id


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


def test_switch_voice_role(session_id, voice_id):
    """测试切换声音角色"""
    print(f"\n测试切换声音角色，session_id: {session_id}")
    print(f"voice_id: {voice_id}")

    # 构造请求数据
    data = {
        "session_id": session_id,
        "voice_id": voice_id
    }

    # 发送请求
    resp = requests.post(f"{BASE_URL}/switch_voice_role", json=data)

    # 打印响应
    print(f"响应状态码: {resp.status_code}")
    print(f"响应内容: {resp.json()}")

    # 检查响应
    if resp.status_code == 200:
        result = resp.json()
        if result.get("status") == "switch success!":
            # 更新会话的声音状态
            voice_status = load_voice_status()
            voice_status[session_id] = voice_id
            save_voice_status(voice_status)
            print("\n✅ 切换声音角色测试成功！")
            return True
        else:
            print("❌ 切换声音角色测试失败！\n")
            print(f"错误信息: {result.get('error')}")
    else:
        print("\n❌ 切换声音角色测试失败！\n")
        print(f"错误信息: {resp.text}")

    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测试切换声音角色接口")
    parser.add_argument("--voice-id", help="音色ID，为空时随机选择")
    parser.add_argument("--session-id", help="会话ID，不提供则从文件读取")
    args = parser.parse_args()

    test_health()

    session_id = args.session_id or get_session_id()
    if not session_id:
        print("会话ID无效，跳过切换声音角色测试")
        exit(1)

    # 如果没有指定声音ID，随机选择一个
    voice_id = args.voice_id
    if not voice_id:
        voice_id = get_random_voice_id(session_id)
        if not voice_id:
            print("无法获取声音ID，跳过测试")
            exit(1)

    test_switch_voice_role(session_id, voice_id)