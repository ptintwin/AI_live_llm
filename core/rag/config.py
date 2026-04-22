import os
from typing import List, Optional
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

_config = None


def load_rag_config() -> dict:
    """加载RAG配置，优先使用config.yaml，缺失则用默认值"""
    global _config
    if _config is not None:
        return _config

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            yaml_config = safe_load(f)
            rag_config = yaml_config.get("rag", {})
    except Exception as e:
        print(f"警告：加载config.yaml失败，使用默认配置: {e}")
        rag_config = {}

    config = DEFAULT_RAG_CONFIG.copy()
    config.update(rag_config)

    config["docs_path"] = str(BASE_DIR / config["docs_path"])
    config["vector_db_path"] = str(BASE_DIR / config["vector_db_path"])
    config["embedding_model_path"] = str(BASE_DIR / config["embedding_model_path"])
    config["reranker_model_path"] = str(BASE_DIR / config["reranker_model_path"])

    _config = config
    return config


def get_rag_config() -> dict:
    """获取RAG配置（已缓存）"""
    if _config is None:
        return load_rag_config()
    return _config


def reload_rag_config() -> dict:
    """重新加载RAG配置"""
    global _config
    _config = None
    return load_rag_config()
