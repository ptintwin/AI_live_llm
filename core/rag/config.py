"""RAG 配置加载（§十二：Spring 是 SSoT，YAML 仅作冷启动兜底）。

合并优先级（从低到高）：
  1. DEFAULT_RAG_CONFIG      —— 代码内硬编码兜底
  2. config.yaml `rag:` 段   —— 冷启动 / Spring 不可达时的本地兜底
  3. Spring `GET /api/config/rag` —— 运行态真值（只保留 Spring 明确返回的键）

路径字段统一展开为绝对路径（基于 BASE_DIR）。
"""
import asyncio
from typing import Optional
from yaml import safe_load
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "config.yaml"

DEFAULT_RAG_CONFIG = {
    "enabled": True,
    "docs_path": "docs/organized_Q&A.txt",
    "vector_db_path": "data/chroma_db",
    "embedding_model_path": "core/rag/embedding_models/bge-base-zh-v1dot5",
    "retrieve_k": 3,
    "enable_reranker": False,
    "rerank_top_n": 2,
    "reranker_model_path": "core/rag/embedding_models/bge-reranker-base",
    "trigger_mode": "hybrid",
    "rule_keywords": [
        "福利", "东西", "有什么", "有啥", "代金", "代金券",
        "版本", "无解版", "纯享版", "新区", "哪个区",
        "怎么玩", "如何进", "进游", "上线", "下载",
        "职业", "角色", "什么职业",
        "氪", "钱", "花多少", "微氪", "0氪",
        "画面", "打击", "特效", "画质",
        "真实", "真的", "所见即所得",
        "有没有", "什么游戏", "好玩", "类型",
        "坐骑", "羽毛", "翅膀", "装备",
        "怎么搞", "如何弄", "在哪",
        "多少", "几个", "多久",
        "能吗", "可以吗", "要吗"
    ],
    "semantic_threshold": 0.5,
    "similarity_threshold": 0.5
}

# 有必要以绝对路径形式交给下游的字段（embedding 加载、chroma 目录、文档解析）
_PATH_FIELDS = ("docs_path", "vector_db_path", "embedding_model_path", "reranker_model_path")

_config: Optional[dict] = None


def _read_yaml_rag() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            yaml_config = safe_load(f) or {}
            return yaml_config.get("rag", {}) or {}
    except Exception as e:
        print(f"警告：加载 config.yaml 失败，忽略 YAML 段：{e}")
        return {}


def _absolutize_paths(cfg: dict) -> dict:
    for key in _PATH_FIELDS:
        val = cfg.get(key)
        if not val:
            continue
        p = Path(val)
        if not p.is_absolute():
            cfg[key] = str(BASE_DIR / val)
    return cfg


def _build_config(spring_overrides: Optional[dict] = None) -> dict:
    """DEFAULT → YAML → Spring 三层合并；Spring 明确给的键才覆盖。"""
    cfg = DEFAULT_RAG_CONFIG.copy()
    cfg.update(_read_yaml_rag())
    if spring_overrides:
        for k, v in spring_overrides.items():
            if v is None:
                continue
            cfg[k] = v
    return _absolutize_paths(cfg)


def load_rag_config() -> dict:
    """同步版：仅 DEFAULT + YAML，不查 Spring。

    专供以下场景：
      - 模块首次 import 时的冷启动（无事件循环 / Spring 可能尚未就绪）
      - Spring 不可达时的降级兜底
    """
    global _config
    if _config is not None:
        return _config
    _config = _build_config(spring_overrides=None)
    return _config


async def load_rag_config_async() -> dict:
    """推荐入口：拉取 Spring 的 cfg_rag → 合并 DEFAULT + YAML + Spring。

    Spring 不可达时自动降级到 load_rag_config()（YAML 兜底）。
    """
    global _config
    try:
        # 延迟 import，避免循环依赖
        from utils.spring_llm_config import fetch_rag_config
        overrides = await fetch_rag_config()
    except Exception as e:
        # 打印而非 logger，防止 utils.logger 未就绪时递归
        print(f"警告：拉取 Spring cfg_rag 失败，降级使用 YAML：{e}")
        overrides = {}
    _config = _build_config(spring_overrides=overrides)
    return _config


def get_rag_config() -> dict:
    """获取当前缓存；缓存为空则退化到同步 load。"""
    if _config is None:
        return load_rag_config()
    return _config


def reload_rag_config() -> dict:
    """同步 reload（仅 DEFAULT + YAML）。

    若当前在事件循环上下文，尽量改用 reload_rag_config_async() 以同步 Spring 值。
    """
    global _config
    _config = None
    return load_rag_config()


async def reload_rag_config_async() -> dict:
    """异步 reload：重新拉 Spring 合并；供 /reload_rag_config 接口使用。"""
    global _config
    _config = None
    return await load_rag_config_async()


def _running_loop_or_none():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None
