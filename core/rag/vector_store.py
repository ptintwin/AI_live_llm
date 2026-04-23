import os
import shutil
from typing import List, Optional, Any
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma

from utils.logger import logger
from core.rag.config import get_rag_config
from core.rag.embedding import get_embedding_model, embed_query, embed_documents

_vector_store = None


class LangChainEmbeddingWrapper(Embeddings):
    """LangChain兼容的Embedding包装器"""

    def __init__(self, local_model):
        self.local_model = local_model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.local_model.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self.local_model.embed_query(text)


def get_vector_store() -> Optional[Chroma]:
    """
    获取向量数据库实例（单例）

    Returns:
        Chroma向量数据库实例，若未初始化则返回None
    """
    global _vector_store
    return _vector_store


def init_vector_store(force_rebuild: bool = False) -> Chroma:
    """
    初始化向量数据库

    Args:
        force_rebuild: 是否强制重建（删除旧库）

    Returns:
        Chroma向量数据库实例
    """
    global _vector_store

    config = get_rag_config()
    persist_directory = config["vector_db_path"]

    if _vector_store is not None and not force_rebuild:
        return _vector_store

    local_model = get_embedding_model()
    embeddings = LangChainEmbeddingWrapper(local_model)

    if os.path.exists(persist_directory) and os.listdir(persist_directory):
        if force_rebuild:
            shutil.rmtree(persist_directory)
            logger.info(f"已删除旧向量库: {persist_directory}")
            _vector_store = None
        else:
            logger.info(f"加载已有向量库: {persist_directory}")
            _vector_store = Chroma(
                embedding_function=embeddings,
                persist_directory=persist_directory
            )
            return _vector_store

    logger.info(f"创建新向量库: {persist_directory}")
    _vector_store = Chroma(
        embedding_function=embeddings,
        persist_directory=persist_directory
    )

    return _vector_store


def add_documents(documents: List[Document]) -> int:
    """
    向向量库添加文档

    Args:
        documents: 文档列表

    Returns:
        添加的文档数量
    """
    global _vector_store

    if _vector_store is None:
        init_vector_store()

    if not documents:
        return 0

    _vector_store.add_documents(documents)
    logg(f"已添加 {len(documents)} 个文档到向量库")
    return len(documents)


def search(query: str, k: int = 3, fetch_score: bool = True) -> List[Document]:
    """
    检索相似文档

    Args:
        query: 查询文本
        k: 返回数量
        fetch_score: 是否获取相似度分数

    Returns:
        相似文档列表
    """
    global _vector_store

    if _vector_store is None:
        init_vector_store()

    if not query:
        return []

    if fetch_score:
        results_with_scores = _vector_store.similarity_search_with_relevance_scores(query, k=k)
        for doc, similarity_score in results_with_scores:
            doc.metadata["similarity_score"] = similarity_score
            if "rerank_score" not in doc.metadata:
                doc.metadata["rerank_score"] = similarity_score
        return [doc for doc, _ in results_with_scores]
    else:
        retriever = _vector_store.as_retriever(
            search_kwargs={"k": k}
        )
        results = retriever.invoke(query)
        return results


def get_document_count() -> int:
    """
    获取向量库中的文档数量

    Returns:
        文档数量
    """
    global _vector_store

    if _vector_store is None:
        return 0

    try:
        return _vector_store._collection.count()
    except Exception:
        return 0


def clear_vector_store() -> bool:
    """
    清空向量库

    Returns:
        是否成功
    """
    global _vector_store

    try:
        if _vector_store is not None:
            _vector_store.delete_collection()
            _vector_store = None

        config = get_rag_config()
        persist_directory = config["vector_db_path"]
        if os.path.exists(persist_directory):
            shutil.rmtree(persist_directory)

        logger.info("向量库已清空")
        return True
    except Exception as e:
        logger.error(f"清空向量库失败: {e}")
        return False


def reset_vector_store():
    """重置向量库实例"""
    global _vector_store
    _vector_store = None
