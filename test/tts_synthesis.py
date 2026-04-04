#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试语音合成接口
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


def test_tts_synthesis(voice_id, instruction, text=None, save_mode="local"):
    """测试语音合成接口"""
    print(f"\n测试语音合成接口，voice_id: {voice_id}")
    print(f"instruction: {instruction}")
    if text:
        print(f"text: {text}")
    print(f"save_mode: {save_mode}")

    # 构造请求数据
    data = {
        "voice_id": voice_id,
        "instruction": instruction,
        "save_mode": save_mode
    }

    if text:
        data["text"] = text

    # 发送请求
    response = requests.post(f"{BASE_URL}/tts_synthesis", json=data)

    # 打印响应
    print(f"响应状态码: {response.status_code}")
    print(f"响应内容: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")

    # 检查响应
    if response.status_code == 200:
        result = response.json()
        if result.get("status") == "success":
            print("\n✅ 语音合成测试成功！")
            print(f"生成的音频路径: {result.get('audio_path')}")
            if result.get('audio_url'):
                print(f"生成的音频URL: {result.get('audio_url')}")
            return result.get("audio_path")
        else:
            print("\n❌ 语音合成测试失败！")
            print(f"错误信息: {result.get('error')}")
    else:
        print("\n❌ 语音合成测试失败！")
        print(f"错误信息: {response.text}")

    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测试语音合成接口")
    parser.add_argument("--voice-id", required=True, help="音色ID")
    parser.add_argument("--instruction", help="语音合成指令")
    parser.add_argument("--text", help="需要播报的文字内容")
    parser.add_argument("--save-mode", choices=["local", "upload"], default="local",
                        help="存储模式: local(本地存储) 或 upload(上传到OSS)")
    args = parser.parse_args()

    test_tts_synthesis(args.voice_id, args.instruction, args.text, args.save_mode)