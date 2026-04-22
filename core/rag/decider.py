import re
from typing import List

from core.rag.config import get_rag_config
from core.rag.embedding import embed_query
from core.rag.vector_store import search


class RAGDecider:
    """
    RAG触发判断器

    支持两种判断模式：
    - rule: 规则模式，通过关键词匹配
    - semantic: 语义模式，通过向量相似度
    - hybrid: 混合模式，规则优先，语义兜底
    """

    def __init__(self):
        config = get_rag_config()
        self.enabled = config.get("enabled", True)
        self.trigger_mode = config.get("trigger_mode", "hybrid")
        self.rule_keywords = config.get("rule_keywords", [])
        self.semantic_threshold = config.get("semantic_threshold", 0.5)
        self.semantic_k = 3

    def should_use_rag(self, question: str) -> bool:
        """
        判断是否应该使用RAG

        Args:
            question: 用户问题

        Returns:
            是否触发RAG
        """
        if not self.enabled:
            return False

        if not question or not question.strip():
            return False

        question = question.strip()

        if self.trigger_mode == "rule":
            return self._rule_match(question)

        elif self.trigger_mode == "semantic":
            return self._semantic_match(question)

        elif self.trigger_mode == "hybrid":
            if self._rule_match(question):
                return True
            return self._semantic_match(question)

        return False

    def _rule_match(self, question: str) -> bool:
        """
        规则模式：关键词匹配

        Args:
            question: 用户问题

        Returns:
            是否匹配
        """
        question_lower = question.lower()

        for keyword in self.rule_keywords:
            if keyword in question:
                return True

        return False

    def _semantic_match(self, question: str) -> bool:
        """
        语义模式：通过向量相似度判断

        Args:
            question: 用户问题

        Returns:
            是否匹配
        """
        try:
            docs = search(question, k=self.semantic_k)

            if not docs:
                return False

            for doc in docs:
                score = doc.metadata.get("rerank_score")
                if score is None:
                    continue

                if score >= self.semantic_threshold:
                    return True

            return False

        except Exception as e:
            print(f"语义匹配失败: {e}")
            return False

    def get_match_reason(self, question: str) -> str:
        """
        获取匹配原因（用于调试）

        Args:
            question: 用户问题

        Returns:
            匹配原因描述
        """
        if not self.enabled:
            return "RAG未启用"

        if not question:
            return "问题为空"

        if self.trigger_mode == "rule":
            if self._rule_match(question):
                return "规则匹配"
            return "规则未匹配"

        elif self.trigger_mode == "semantic":
            if self._semantic_match(question):
                return "语义匹配"
            return "语义未匹配"

        elif self.trigger_mode == "hybrid":
            if self._rule_match(question):
                return "规则匹配"
            if self._semantic_match(question):
                return "语义匹配(兜底)"
            return "混合模式均未匹配"

        return "未知"


_decider_instance = None


def get_rag_decider() -> RAGDecider:
    """获取RAGDecider单例"""
    global _decider_instance
    if _decider_instance is None:
        _decider_instance = RAGDecider()
    return _decider_instance


def should_use_rag(question: str) -> bool:
    """便捷函数：判断是否使用RAG"""
    return get_rag_decider().should_use_rag(question)


def reset_decider():
    """重置Decider实例"""
    global _decider_instance
    _decider_instance = None
