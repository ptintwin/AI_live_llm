from typing import List, Optional

from core.rag.config import get_rag_config
from core.rag.document_processor import get_documents_for_indexing
from core.rag.vector_store import (
    init_vector_store,
    add_documents,
    get_document_count,
    clear_vector_store,
    reset_vector_store
)
from core.rag.retriever import retrieve, retrieve_with_answers, get_vector_store_status
from core.rag.decider import RAGDecider, get_rag_decider, should_use_rag, reset_decider


class RAGService:
    """
    RAG核心服务

    提供文档索引和问答检索功能
    """

    def __init__(self, force_rebuild: bool = False):
        """
        初始化RAG服务

        Args:
            force_rebuild: 是否强制重建向量库
        """
        config = get_rag_config()
        self.config = config
        self.docs_path = config.get("docs_path")

        init_vector_store(force_rebuild=force_rebuild)

        doc_count = get_document_count()
        if doc_count == 0 or force_rebuild:
            self._build_index()

        self.decider = get_rag_decider()

    def _build_index(self):
        """从QA文件构建向量索引"""
        print(f"从 {self.docs_path} 构建向量索引...")
        documents = get_documents_for_indexing(self.docs_path)
        if documents:
            add_documents(documents)
            print(f"索引构建完成，共 {len(documents)} 个文档")
        else:
            print("警告：未能从QA文件解析出文档")

    def get_answer(self, question: str) -> List[str]:
        """
        获取问题的答案

        Args:
            question: 用户问题

        Returns:
            答案列表
        """
        if not question:
            return []

        answers = retrieve_with_answers(question)
        return answers

    def get_answer_with_context(self, question: str) -> dict:
        """
        获取问题答案（含完整上下文）

        Args:
            question: 用户问题

        Returns:
            包含答案和元信息的字典
        """
        if not question:
            return {"answers": [], "docs": []}

        from core.rag.retriever import retrieve
        docs = retrieve(question)

        all_answers = []
        docs_info = []
        for doc in docs:
            answers = doc.metadata.get("answers", [])
            all_answers.extend(answers)
            docs_info.append({
                "content": doc.page_content,
                "question": doc.metadata.get("question", ""),
                "answers": answers,
                "score": doc.metadata.get("rerank_score", 0.0)
            })

        return {
            "answers": all_answers,
            "docs": docs_info
        }

    def should_use_rag(self, question: str) -> bool:
        """
        判断是否应该使用RAG

        Args:
            question: 用户问题

        Returns:
            是否触发RAG
        """
        return self.decider.should_use_rag(question)

    def rebuild_index(self):
        """重建向量索引"""
        clear_vector_store()
        reset_decider()
        init_vector_store(force_rebuild=True)
        self._build_index()

    def get_status(self) -> dict:
        """获取服务状态"""
        status = get_vector_store_status()
        status["decider_mode"] = self.decider.trigger_mode
        return status


_rag_service_instance = None


def get_rag_service(force_rebuild: bool = False) -> RAGService:
    """获取RAGService单例"""
    global _rag_service_instance
    if _rag_service_instance is None:
        _rag_service_instance = RAGService(force_rebuild=force_rebuild)
    return _rag_service_instance


def reset_rag_service():
    """重置RAG服务实例"""
    global _rag_service_instance
    _rag_service_instance = None
    reset_vector_store()
    reset_decider()
