from typing import List, Optional
from langchain_core.documents import Document

from utils.logger import logger
from core.rag.config import get_rag_config
from core.rag.vector_store import search, get_document_count
from core.rag.reranker import rerank_documents


def _filter_by_similarity(docs: List[Document], threshold: float) -> List[Document]:
    """
    根据相似度阈值过滤文档

    余弦相似度分数范围 [0, 1]：
    - 1.0 = 完全相同
    - 0.5 = 中等相关性（大多数检索任务的标准阈值）
    - 0.0 = 完全不同

    Args:
        docs: 检索到的文档列表
        threshold: 相似度阈值

    Returns:
        过滤后的文档列表
    """
    if not docs:
        return []

    filtered = []
    for doc in docs:
        score = doc.metadata.get("rerank_score", 0.0)
        if score >= threshold:
            filtered.append(doc)
        else:
            logger.info(f"【RAG检索】由于文档相似度低于阈值{threshold}，被过滤掉文档：{doc}")

    return filtered


def retrieve(query: str, k: Optional[int] = None, use_reranker: Optional[bool] = None) -> List[Document]:
    """
    检索相关文档

    Args:
        query: 查询文本
        k: 检索数量，默认使用配置
        use_reranker: 是否使用重排，默认使用配置

    Returns:
        相关文档列表
    """
    config = get_rag_config()

    if k is None:
        k = config.get("retrieve_k", 3)

    if use_reranker is None:
        use_reranker = config.get("enable_reranker", False)

    if not query:
        return []

    logger.info(f"【RAG检索】执行query语句“{query}”")
    docs = search(query, k=k)

    if not docs:
        logger.info(f"【RAG检索】从向量库检索到0条相关文档")
        return []

    if use_reranker:
        docs = rerank_documents(query, docs)

    similarity_threshold = config.get("similarity_threshold", 0.5)
    if similarity_threshold > 0 and len(docs) > 0:
        filtered = _filter_by_similarity(docs, similarity_threshold)
        logger.info(f"【RAG检索】从向量库检索到{len(filtered)}条相关文档，具体为：{filtered}")
        if len(filtered) > 0:
            return filtered
        return []

    return docs


def retrieve_with_answers(query: str) -> List[str]:
    """
    检索并提取答案文本

    Args:
        query: 查询文本

    Returns:
        答案列表
    """
    docs = retrieve(query)

    answers = []
    for doc in docs:
        answer = doc.metadata.get("answer", "")
        if answer:
            answers.append(answer)

    return answers


def get_vector_store_status() -> dict:
    """
    获取向量库状态

    Returns:
        状态信息字典
    """
    config = get_rag_config()
    doc_count = get_document_count()

    return {
        "enabled": config.get("enabled", True),
        "vector_db_path": config.get("vector_db_path"),
        "document_count": doc_count,
        "enable_reranker": config.get("enable_reranker", False),
        "retrieve_k": config.get("retrieve_k", 3),
        "similarity_threshold": config.get("similarity_threshold", 0.5),
        "trigger_mode": config.get("trigger_mode", "hybrid")
    }
