# 抖音游戏主播直播互动系统

## 项目简介
基于**阿里云百炼**实现的抖音游戏主播自动化直播系统，支持：
1. 流式生成游戏讲解文案（通义千问3.5 Plus）
2. 实时抓取抖音弹幕+观众进场提醒
3. 自然中断讲解+互动回复
4. 流式TTS语音合成（CosyVoice v3.5）+ 实时扬声器播放
5. 声音克隆定制主播音色
6. 异步高并发服务（FastAPI+uvicorn）

## 核心特性
✅ 工程级代码架构 | ✅ 阿里云临时缓存 | ✅ 自然语音中断
✅ 段落式流式生成 | ✅ 实时弹幕互动 | ✅ 克隆音色TTS
✅ 多会话管理 | ✅ 自动循环讲解 | ✅ 日志监控

## 项目结构
```
AI-voice/
├── audio_design/       # 语音克隆相关
├── audio_output/       # 音频输出目录
├── config/             # 配置文件
├── core/               # 核心服务（LLM和TTS）
├── logs/               # 日志文件
├── test/               # 测试文件
├── utils/              # 工具函数
├── API文档.md          # API接口文档
├── README.md           # 项目说明文档
├── main.py             # 服务主入口
└── requirements.txt    # 依赖包列表
```

## 部署步骤
1. **安装依赖**：`pip install -r requirements.txt`
2. **配置文件**：修改`config/config.yaml`，填入阿里云百炼API Key
3. **克隆音色**：调用`/voice_clone`接口或运行相关测试脚本
4. **启动服务**：`python main.py`
5. **接口测试**：运行`test`目录下的测试脚本

## 核心接口
| 接口路径 | 方法 | 功能描述 |
|---------|------|---------|
| `/health_check` | GET | 服务健康检查 |
| `/start_stream` | POST | 开启流式直播讲解 |
| `/live_danmu` | POST | 处理直播间弹幕 |
| `/stop_session` | POST | 停止指定会话 |
| `/shutdown_all` | GET | 关闭所有会话 |
| `/voice_clone` | POST | 语音克隆 |
| `/tts_synthesis` | POST | 语音合成 |

## 接口使用说明

### 1. 开启直播会话
```bash
curl -X POST "http://localhost:8000/start_stream" \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": "12345678",
    "background": "这是一个游戏直播间，主播正在玩英雄联盟"
  }'
```

### 2. 处理弹幕
```bash
curl -X POST "http://localhost:8000/live_danmu" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "danmu_list": [
      {
        "username": "观众1",
        "content": "主播好厉害！",
        "type": "question"
      }
    ]
  }'
```

### 3. 停止会话
```bash
curl -X POST "http://localhost:8000/stop_session" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

### 4. 语音克隆
```bash
curl -X POST "http://localhost:8000/voice_clone" \
  -H "Content-Type: application/json" \
  -d '{
    "audio_url": "https://example.com/audio.wav"
  }'
```

### 5. 语音合成
```bash
curl -X POST "http://localhost:8000/tts_synthesis" \
  -H "Content-Type: application/json" \
  -d '{
    "voice_id": "voice-123456",
    "instruction": "欢快的语气",
    "text": "欢迎来到我的直播间！",
    "save_mode": "local"
  }'
```

## 技术栈
- **后端框架**：FastAPI + uvicorn
- **LLM服务**：阿里云百炼（通义千问3.5 Plus）
- **TTS服务**：CosyVoice v3.5
- **语音克隆**：基于阿里云音频服务
- **存储**：本地文件系统 + 阿里云OSS
- **日志**：自定义日志系统

## 注意事项
1. 服务启动前请确保配置文件中的API Key已正确设置
2. 语音克隆和语音合成接口可能需要较长的处理时间
3. 服务重启后，所有会话会被重置
4. 建议在生产环境中配置适当的错误处理和监控

## 测试
测试脚本位于`test`目录，包括：
- `live_danmu.py`：测试弹幕处理
- `start_stream.py`：测试开启直播
- `stop_session.py`：测试停止会话
- `tts_synthesis.py`：测试语音合成
- `voice_clone.py`：测试语音克隆

## 许可证
本项目仅供学习和研究使用。