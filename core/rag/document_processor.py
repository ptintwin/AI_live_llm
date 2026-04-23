import re
from typing import List
from langchain_core.documents import Document


def parse_qa_file(file_path: str) -> List[Document]:
    """
    解析QA问答对文件，每个【问】+ 所有【答 N】组合为一个Document

    格式示例：
    【问】：进游有什么福利？【答 1】：正在展示哈，东西都是摆在台面上的
    【问】：什么版本的？【答 1】：无解版本的
    【问】：多少代金？【答 1】：直播间不能说具体哟...【答 2】：老哥格局打开...

    返回：
        List[Document]: 每个问题及其所有答案作为一个Document
        - page_content: 仅存问题Q（用于embedding）
        - metadata.answers: 存所有答案列表
    """
    documents = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"QA文件不存在: {file_path}")
    except Exception as e:
        raise RuntimeError(f"读取QA文件失败: {e}")

    lines = content.strip().split("\n")

    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue

        question_match = re.search(r"【问】[:：]\s*(.+?)\s*【答", line, re.DOTALL)
        if not question_match:
            continue

        question = question_match.group(1).strip()

        answer_matches = re.findall(r"【答\s*(\d+)】[:：]\s*([^【】]+)", line)

        if not answer_matches:
            continue

        answers = []
        for answer_num, answer_content in answer_matches:
            answer = answer_content.strip()
            if answer:
                answers.append(answer)

        if not question or not answers:
            continue

        doc = Document(
            page_content=question,
            metadata={
                "question": question,
                "answers": answers,
                "source": file_path,
                "line_num": line_num
            }
        )
        documents.append(doc)

    return documents


def get_documents_for_indexing(file_path: str) -> List[Document]:
    """
    获取用于索引的文档列表（兼容接口）
    """
    return parse_qa_file(file_path)
