#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试语音克隆接口
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


def test_voice_clone(audio_url):
    """测试语音克隆接口"""
    print(f"\n测试语音克隆接口，音频URL: {audio_url}")

    # 构造请求数据
    data = {
        "audio_url": audio_url
    }

    # 发送请求
    response = requests.post(f"{BASE_URL}/voice_clone", json=data)

    # 打印响应
    print(f"响应状态码: {response.status_code}")
    print(f"响应内容: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")

    # 检查响应
    if response.status_code == 200:
        result = response.json()
        if result.get("status") == "success":
            print("\n✅ 语音克隆测试成功！")
            print(f"生成的voice_id: {result.get('voice_id')}")
            return result.get("voice_id")
        else:
            print("\n❌ 语音克隆测试失败！")
            print(f"错误信息: {result.get('error')}")
    else:
        print("\n❌ 语音克隆测试失败！")
        print(f"错误信息: {response.text}")

    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测试语音克隆接口")
    parser.add_argument("--audio-url", required=True, help="音频文件URL")
    args = parser.parse_args()

    test_voice_clone(args.audio_url)
    # 示例python命令行：
    # python test_voice_clone.py --audio-url "https://lucastao.oss-cn-beijing.aliyuncs.com/voice-recorder-2026-03-19--15-54-30.wav"
