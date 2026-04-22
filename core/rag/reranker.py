import os
from typing import List, Optional, Any
from langchain_core.documents import Document

from core.rag.config import get_rag_config

_reranker_model = None
_reranker_available = None


def _check_reranker_available() -> bool:
    """检查reranker是否可用"""
    global _reranker_available
    if _reranker_available is not None:
        return _reranker_available

    try:
        import torch
        from sentence_transformers import CrossEncoder
        _reranker_available = True
        return True
    except ImportError as e:
        print(f"警告：reranker依赖未安装，将使用备选方案: {e}")
        _reranker_available = False
        return False


def get_reranker_model() -> Optional[Any]:
    """
    获取Reranker模型（单例），根据配置决定是否加载

    Returns:
        CrossEncoder模型实例，若禁用则返回None
    """
    global _reranker_model

    config = get_rag_config()

    if not config.get("enable_reranker", False):
        return None

    if _reranker_model is not None:
        return _reranker_model

    model_path = config.get("reranker_model_path", "core/rag/embedding_models/bge-reranker-base")

    if not _check_reranker_available():
        return None

    if not os.path.exists(model_path):
        print(f"警告：Reranker模型路径不存在: {model_path}，将跳过重排")
        return None

    try:
        import torch
        from sentence_transformers import CrossEncoder
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _reranker_model = CrossEncoder(
            model_name=model_path,
            device=device,
            max_length=512
        )
        print(f"Reranker模型加载成功: {model_path}, 设备: {device}")
    except Exception as e:
        print(f"警告：Reranker模型加载失败: {e}，将跳过重排")
        return None

    return _reranker_model


def rerank_documents(
    query: str,
    documents: List[Document],
    top_n: Optional[int] = None,
    score_threshold: float = 0.0
) -> List[Document]:
    """
    对检索到的文档进行重排序

    Args:
        query: 用户查询
        documents: 待重排的文档列表
        top_n: 重排后保留数量，默认使用配置
        score_threshold: 分数阈值

    Returns:
        重排后的文档列表
    """
    config = get_rag_config()

    if not config.get("enable_reranker", False):
        return documents

    reranker = get_reranker_model()
    if reranker is None:
        return documents

    if not documents:
        return []

    if top_n is None:
        top_n = config.get("rerank_top_n", 2)

    try:
        pairs = [(query, doc.page_content) for doc in documents]
        scores = reranker.predict(pairs)

        doc_score_pairs = list(zip(documents, scores))
        doc_score_pairs.sort(key=lambda x: x[1], reverse=True)

        reranked = []
        for doc, score in doc_score_pairs:
            if score >= score_threshold and len(reranked) < top_n:
                doc.metadata["rerank_score"] = float(score)
                reranked.append(doc)
            elif len(reranked) >= top_n:
                break

        print(f"Rerank: {len(documents)} -> {len(reranked)}")
        return reranked

    except Exception as e:
        print(f"Rerank失败: {e}")
        return documents


def reset_reranker_model():
    """重置Reranker模型"""
    global _reranker_model
    _reranker_model = None
