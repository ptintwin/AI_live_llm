import os
from typing import List, Optional
from pathlib import Path

from core.rag.config import get_rag_config

_embedding_model = None


class LocalEmbeddingModel:
    """本地embedding模型封装，直接使用sentence-transformers"""

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model = None
        self._load_model()

    def _load_model(self):
        """加载模型"""
        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(self.model_path)
            print(f"Embedding模型加载成功: {self.model_path}")
        except Exception as e:
            raise RuntimeError(f"模型加载失败: {e}")

    def embed_query(self, text: str) -> List[float]:
        """对单个文本进行向量化"""
        embedding = self.model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """对多个文本进行向量化"""
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()


def get_embedding_model() -> LocalEmbeddingModel:
    """
    获取Embedding模型（单例）

    使用 bge-base-zh-v1.5 模型
    """
    global _embedding_model

    if _embedding_model is not None:
        return _embedding_model

    config = get_rag_config()
    model_path = config["embedding_model_path"]

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Embedding模型路径不存在: {model_path}")

    try:
        _embedding_model = LocalEmbeddingModel(model_path)
    except Exception as e:
        raise RuntimeError(f"Embedding模型加载失败: {e}")

    return _embedding_model


def embed_query(text: str) -> List[float]:
    """
    对单个文本进行向量化

    Args:
        text: 待向量化的文本

    Returns:
        向量列表
    """
    model = get_embedding_model()
    return model.embed_query(text)


def embed_documents(texts: List[str]) -> List[List[float]]:
    """
    对多个文本进行向量化

    Args:
        texts: 待向量化的文本列表

    Returns:
        向量列表
    """
    model = get_embedding_model()
    return model.embed_documents(texts)


def get_embedding_dimension() -> int:
    """
    获取Embedding向量的维度

    Returns:
        向量维度
    """
    model = get_embedding_model()
    test_embedding = model.embed_query("测试")
    return len(test_embedding)


def reset_embedding_model():
    """重置Embedding模型（用于重新加载）"""
    global _embedding_model
    _embedding_model = None
