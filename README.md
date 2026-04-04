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

## 部署步骤
1. 安装依赖：`pip install -r requirements.txt`
2. 配置`config/config.yaml`：填入阿里云百炼API Key
3. 克隆音色：运行`audio_design/voice_clone.py`
4. 启动服务：运行`main.py`
5. 接口测试：运行`test/test_api.py`

## 核心接口
- `GET /health_check`：健康检查
- `POST /start_stream`：开启直播
- `POST /send_question`：观众互动
- `POST /stop_session`：停止会话