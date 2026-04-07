# 抖音游戏主播直播互动系统

## 项目简介
基于**阿里云百炼**实现的抖音游戏主播自动化直播系统，支持：
1. 流式生成游戏讲解文案（通义千问3.5 Plus）
2. 处理直播间弹幕并进行互动回复
3. 自然中断讲解+互动回复
4. 流式TTS语音合成（CosyVoice v3.5）+ 实时扬声器播放
5. 声音克隆定制主播音色
6. 异步高并发服务（FastAPI+uvicorn）

## 核心特性
✅ 工程级代码架构 | ✅ 阿里云临时缓存 | ✅ 自然语音中断
✅ 段落式流式生成 | ✅ 弹幕互动处理 | ✅ 克隆音色TTS
✅ 多会话管理 | ✅ 自动循环讲解 | ✅ 日志监控

## 项目结构
```
AI_live_llm/
├── audio_design/       # 语音克隆相关
├── config/             # 配置文件
├── core/               # 核心服务（LLM和TTS）
├── test/               # 测试文件
├── utils/              # 工具函数
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

## API接口文档

### 接口列表

| 接口路径 | 方法 | 功能描述 |
|---------|------|--------|
| `/health_check` | GET | 服务健康检查 |
| `/start_stream` | POST | 开启流式直播讲解 |
| `/live_danmu` | POST | 处理直播间弹幕 |
| `/stop_session` | POST | 停止指定会话 |
| `/shutdown_all` | GET | 关闭所有会话 |
| `/voice_clone` | POST | 语音克隆 |
| `/tts_synthesis` | POST | 语音合成 |

### 详细接口说明

#### 1. 服务健康检查

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

#### 2. 开启流式直播讲解

**接口路径**: `/start_stream`
**请求方法**: POST
**功能描述**: 开启一个新的直播讲解会话，生成唯一会话ID

**请求参数**:
| 参数名 | 类型 | 必填 | 描述 |
|---------|------|------|--------|
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

#### 3. 处理直播间弹幕

**接口路径**: `/live_danmu`
**请求方法**: POST
**功能描述**: 处理直播间弹幕，中断当前讲解并生成互动回复

**请求参数**:
| 参数名 | 类型 | 必填 | 描述 |
|---------|------|------|--------|
| `session_id` | string | 是 | 直播间唯一会话ID |
| `danmu_list` | array | 否 | 观众弹幕内容列表，默认为空 |

**danmu_list 数组元素结构**:
| 参数名 | 类型 | 描述 |
|---------|------|--------|
| `username` | string | 用户名 |
| `content` | string | 弹幕内容 |
| `type` | string | 弹幕类型 |

**请求示例**:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "danmu_list": [
    {
      "username": "观众1",
      "content": "主播好厉害！",
      "type": "question"
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

#### 4. 停止指定会话

**接口路径**: `/stop_session`
**请求方法**: POST
**功能描述**: 停止指定的直播会话，清理相关资源

**请求参数**:
| 参数名 | 类型 | 必填 | 描述 |
|---------|------|------|--------|
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

#### 5. 关闭所有会话

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

#### 6. 语音克隆

**接口路径**: `/voice_clone`
**请求方法**: POST
**功能描述**: 根据提供的音频URL克隆语音，返回克隆的voice_id

**请求参数**:
| 参数名 | 类型 | 必填 | 描述 |
|---------|------|------|--------|
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

#### 7. 语音合成

**接口路径**: `/tts_synthesis`
**请求方法**: POST
**功能描述**: 根据提供的语音ID和文本生成语音合成文件

**请求参数**:
| 参数名 | 类型 | 必填 | 描述 |
|---------|------|------|--------|
| `voice_id` | string | 是 | 语音模型ID |
| `speech_rate` | float | 否 | 语音语速，默认1.0 |
| `pitch_rate` | float | 否 | 语音音高，默认1.0 |
| `instruction` | string | 否 | 效果指令 |
| `text` | string | 否 | 需要播报的文字内容，默认为"恭喜，已成功复刻并合成了属于自己的声音，你觉得听起来怎么样？" |
| `save_mode` | string | 否 | 存储模式：local表示本地存储，upload表示上传到OSS，默认为local |

**请求示例**:
```json
{
  "voice_id": "voice-123456",
  "speech_rate": 1.0,
  "pitch_rate": 1.0,
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

### 错误处理

所有接口在遇到错误时，会返回包含`error`字段的响应，同时状态码会相应调整。常见错误包括：

- 会话不存在：`{"error": "会话不存在"}`
- 参数错误：`{"error": "参数错误信息"}`
- 内部服务错误：`{"error": "内部服务错误信息"}`

### 调用示例

以下是使用Java的HttpClient调用示例：

```java
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import com.fasterxml.jackson.databind.ObjectMapper;

// 开启直播会话
public static String startStream(String roomId, String background) throws Exception {
    HttpClient client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();
    
    ObjectMapper mapper = new ObjectMapper();
    
    // 构建请求体
    java.util.Map<String, Object> requestBody = new java.util.HashMap<>();
    requestBody.put("room_id", roomId);
    requestBody.put("background", background);
    
    String requestJson = mapper.writeValueAsString(requestBody);
    
    HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create("http://localhost:8000/start_stream"))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(requestJson))
            .build();
    
    HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
    return response.body();
}

// 处理弹幕
public static String handleDanmu(String sessionId, java.util.List<java.util.Map<String, Object>> danmuList) throws Exception {
    HttpClient client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();
    
    ObjectMapper mapper = new ObjectMapper();
    
    // 构建请求体
    java.util.Map<String, Object> requestBody = new java.util.HashMap<>();
    requestBody.put("session_id", sessionId);
    requestBody.put("danmu_list", danmuList);
    
    String requestJson = mapper.writeValueAsString(requestBody);
    
    HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create("http://localhost:8000/live_danmu"))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(requestJson))
            .build();
    
    HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
    return response.body();
}
```

**注意**：使用此示例需要添加Jackson库依赖，例如在Maven项目的pom.xml中添加：

```xml
<dependency>
    <groupId>com.fasterxml.jackson.core</groupId>
    <artifactId>jackson-databind</artifactId>
    <version>2.15.2</version>
</dependency>
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
5. 所有接口都需要使用正确的Content-Type: application/json
6. 会话ID是系统生成的唯一标识符，用于区分不同的直播会话

## 测试
测试脚本位于`test`目录，包括：
- `live_danmu.py`：测试弹幕处理
- `start_stream.py`：测试开启直播
- `stop_session.py`：测试停止会话
- `tts_synthesis.py`：测试语音合成
- `voice_clone.py`：测试语音克隆

## 许可证
本项目仅供学习和研究使用。