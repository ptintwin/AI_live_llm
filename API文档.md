# 抖音游戏主播直播互动系统 API 文档

## 概述

本文档描述了抖音游戏主播直播互动系统的所有API接口，供前端联调使用。系统基于FastAPI框架开发，提供了直播讲解、弹幕处理、语音合成等核心功能。

## 接口列表

| 接口路径 | 方法 | 功能描述 |
|---------|------|---------|
| `/health_check` | GET | 服务健康检查 |
| `/start_stream` | POST | 开启流式直播讲解 |
| `/live_danmu` | POST | 处理直播间弹幕 |
| `/stop_session` | POST | 停止指定会话 |
| `/shutdown_all` | GET | 关闭所有会话 |
| `/voice_clone` | POST | 语音克隆 |
| `/tts_synthesis` | POST | 语音合成 |

## 详细接口说明

### 1. 服务健康检查

**接口路径**: `/health_check`
**请求方法**: GET
**功能描述**: 检查服务是否正常运行，返回当前会话数量

**响应示例**:
```json
{
  "status": "ok",
  "sessions_count": 0
}
```

### 2. 开启流式直播讲解

**接口路径**: `/start_stream`
**请求方法**: POST
**功能描述**: 开启一个新的直播讲解会话，生成唯一会话ID

**请求参数**:
| 参数名 | 类型 | 必填 | 描述 |
|---------|------|------|---------|
| `room_id` | string | 是 | 直播间ID |
| `background` | string | 否 | 当前直播间专属系统提示词，默认为空 |

**请求示例**:
```json
{
  "room_id": "12345678",
  "background": "这是一个游戏直播间，主播正在玩英雄联盟"
}
```

**响应示例**:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "started"
}
```

### 3. 处理直播间弹幕

**接口路径**: `/live_danmu`
**请求方法**: POST
**功能描述**: 处理直播间弹幕，中断当前讲解并生成互动回复

**请求参数**:
| 参数名 | 类型 | 必填 | 描述 |
|---------|------|------|---------|
| `session_id` | string | 是 | 直播间唯一会话ID |
| `danmu_list` | array | 否 | 观众弹幕内容列表，默认为空 |

**danmu_list 数组元素结构**:
| 参数名 | 类型 | 描述 |
|---------|------|---------|
| `username` | string | 用户名 |
| `content` | string | 弹幕内容 |
| `type` | string | 弹幕类型 |
| `level` | string | 问题等级(可选) |

**请求示例**:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "danmu_list": [
    {
      "username": "观众1",
      "content": "主播好厉害！",
      "type": "question",
      "level": "充值类问题｜专业提问类｜下载类问题｜游戏相关普通问题｜其它闲聊问题（优先级从高到低）"
    },
    {
      "username": "观众2",
      "content": "‘观众2’来了",
      "type": "enter"
    },
    {
      "username": "观众3",
      "content": "‘观众3’关注了主播",
      "type": "follow"
    },
    {
      "username": "观众4",
      "content": "‘观众4’送出超跑/点赞了",
      "type": "gift"
    }
  ]
}
```

**响应示例**:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "answer": "谢谢大家的支持！这个游戏的玩法是..."
}
```

### 4. 停止指定会话

**接口路径**: `/stop_session`
**请求方法**: POST
**功能描述**: 停止指定的直播会话，清理相关资源

**请求参数**:
| 参数名 | 类型 | 必填 | 描述 |
|---------|------|------|---------|
| `session_id` | string | 是 | 直播间唯一会话ID |

**请求示例**:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**响应示例**:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "stopped"
}
```

### 5. 关闭所有会话

**接口路径**: `/shutdown_all`
**请求方法**: GET
**功能描述**: 关闭所有直播会话，清理所有资源

**响应示例**:
```json
{
  "status": "success",
  "message": "所有会话已关闭"
}
```

### 6. 语音克隆

**接口路径**: `/voice_clone`
**请求方法**: POST
**功能描述**: 根据提供的音频URL克隆语音，返回克隆的voice_id

**请求参数**:
| 参数名 | 类型 | 必填 | 描述 |
|---------|------|------|---------|
| `audio_url` | string | 是 | 阿里云OSS的音频URL |

**请求示例**:
```json
{
  "audio_url": "https://example.com/audio.wav"
}
```

**响应示例**:
```json
{
  "voice_id": "voice-123456",
  "status": "success"
}
```

**错误响应**:
```json
{
  "error": "克隆失败的错误信息",
  "status": "failed"
}
```

### 7. 语音合成

**接口路径**: `/tts_synthesis`
**请求方法**: POST
**功能描述**: 根据提供的语音ID和文本生成语音合成文件

**请求参数**:
| 参数名 | 类型 | 必填 | 描述 |
|---------|------|------|---------|
| `voice_id` | string | 是 | 语音ID |
| `instruction` | string | 否 | 效果指令 |
| `text` | string | 否 | 需要播报的文字内容，默认为"恭喜，已成功复刻并合成了属于自己的声音，你觉得听起来怎么样？" |
| `save_mode` | string | 否 | 存储模式：local表示本地存储，upload表示上传到OSS，默认为local |

**请求示例**:
```json
{
  "voice_id": "voice-123456",
  "instruction": "欢快的语气",
  "text": "欢迎来到我的直播间！",
  "save_mode": "upload"
}
```

**响应示例** (local模式):
```json
{
  "status": "success",
  "audio_path": "/path/to/audio.wav"
}
```

**响应示例** (upload模式):
```json
{
  "status": "success",
  "audio_url": "https://oss.example.com/audio.wav"
}
```

**错误响应**:
```json
{
  "error": "合成失败的错误信息",
  "status": "failed"
}
```

## 错误处理

所有接口在遇到错误时，会返回包含`error`字段的响应，同时状态码会相应调整。常见错误包括：

- 会话不存在：`{"error": "会话不存在"}`
- 参数错误：`{"error": "参数错误信息"}`
- 内部服务错误：`{"error": "内部服务错误信息"}`

## 调用示例

以下是使用JavaScript的fetch API调用示例：

```javascript
// 开启直播会话
async function startStream(roomId, background) {
  const response = await fetch('/start_stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      room_id: roomId,
      background: background
    }),
  });
  return await response.json();
}

// 处理弹幕
async function handleDanmu(sessionId, danmuList) {
  const response = await fetch('/live_danmu', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      session_id: sessionId,
      danmu_list: danmuList
    }),
  });
  return await response.json();
}
```

## 注意事项

1. 所有接口都需要使用正确的Content-Type: application/json
2. 会话ID是系统生成的唯一标识符，用于区分不同的直播会话
3. 语音克隆和语音合成接口可能需要较长的处理时间
4. 服务重启后，所有会话会被重置
5. 建议在调用接口时添加适当的错误处理和超时处理

希望这份API文档能帮助前端开发人员顺利与后端服务进行联调。如有任何疑问，请随时与后端开发团队联系。