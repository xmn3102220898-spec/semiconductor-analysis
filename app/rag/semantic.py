#=======================
#        工艺知识
#=======================

import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import settings
from app.observability import get_logger


# ==========================================
# 1. 设置路径和模型
# ==========================================

BASE_DIR = settings.project_root
KNOWLEDGE_DIR = settings.knowledge_dir
MODEL_NAME = settings.embedding_model
logger = get_logger(__name__)


# ==========================================
# 2. 读取并切分知识文档
# ==========================================

def load_documents():
    """读取 txt 文档，并按空行切分成知识片段。"""

    documents = []

    if not KNOWLEDGE_DIR.exists():
        logger.warning(
            "knowledge_directory_missing",
            extra={
                "event": "knowledge_directory_missing",
                "knowledge_dir": str(KNOWLEDGE_DIR),
            },
        )
        return documents

    for file_path in KNOWLEDGE_DIR.glob("*.txt"):

        content = file_path.read_text(encoding="utf-8")

        # 每个片段单独检索，同时保留它的来源文件
        chunks = content.split("\n\n")

        for chunk in chunks:
            chunk = chunk.strip()

            if chunk:
                documents.append({
                    "source": file_path.name,
                    "content": chunk
                })

    return documents


# ==========================================
# 3. 创建语义检索器
# ==========================================

def build_embeddings(documents, model):
    """把所有知识片段转换成向量。"""

    # 提取所有片段的正文，形成文本列表
    texts = [
        document["content"]
        for document in documents
    ]

    # 一次性计算全部文档的向量，避免每次提问都重新计算
    embeddings = model.encode(
        texts,
        normalize_embeddings=True
    )

    return embeddings


# ==========================================
# 4. 根据问题检索知识
# ==========================================

def search_knowledge(question, documents, embeddings, model):

    # 将用户的问题也转换成向量
    question_embedding = model.encode(
        [question],
        normalize_embeddings=True
    )

    # 归一化向量之间的点积等于余弦相似度
    # question_embedding 只有一行，因此 [0] 取出这一行
    
    scores = np.dot(  
        embeddings,
        question_embedding[0]
    )
    #计算问题向量与每条知识向量的相似度。


    # 按相似度从高到低排列文档下标
    ranked_indices = np.argsort(scores)[::-1]

    results = []

    # 最多返回 3 个知识片段
    for index in ranked_indices[:3]:

        results.append({
            "source": documents[index]["source"],
            "content": documents[index]["content"],
            "score": float(scores[index])
        })

    return results


# ==========================================
# 5. 主程序
# ==========================================

def main():

    documents = load_documents()

    if not documents:
        print("没有读取到知识片段，请检查 knowledge_base 文件夹。")
        return

    print(f"成功加载 {len(documents)} 个知识片段。")

    # 加载模型
    print("正在加载文本向量模型……")

    model = SentenceTransformer(MODEL_NAME)

    # 建立知识向量索引
    print("正在计算知识片段的向量……")

    embeddings = build_embeddings(documents, model)

    print("知识向量索引建立完成！")

    while True:

        question = input(
            "\n请输入问题（输入 q 退出）："
        ).strip()

        if question.lower() == "q":
            print("检索程序已退出。")
            break

        if not question:
            print("问题不能为空，请重新输入。")
            continue

        results = search_knowledge(
            question,
            documents,
            embeddings,
            model
        )

        print("\n========== 语义检索结果 ==========")

        for number, result in enumerate(results, start=1):

            print(f"\n结果 {number}")
            print(f"来源文件：{result['source']}")
            print(f"相似度：{result['score']:.4f}")
            print(f"知识内容：{result['content']}")


if __name__ == "__main__":
    main()
