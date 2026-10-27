
from pathlib import Path


# ==========================================
# 1. 设置知识库目录
# ==========================================

# __file__ 表示当前 Python 文件的路径
# parent 表示当前文件所在的文件夹
BASE_DIR = Path(__file__).resolve().parent

# 知识库文件夹的完整路径
KNOWLEDGE_DIR = BASE_DIR / "knowledge_base"


# ==========================================
# 2. 读取知识文档
# ==========================================

def load_documents():
    """读取知识库中的所有 txt 文件。"""

    documents = []

    # 如果文件夹不存在，给出明确提示
    if not KNOWLEDGE_DIR.exists():
        print(f"知识库目录不存在：{KNOWLEDGE_DIR}")
        return documents

    # glob("*.txt") 用于查找当前目录下所有 txt 文件
    for file_path in KNOWLEDGE_DIR.glob("*.txt"):

        # encoding="utf-8" 用于按 UTF-8 编码读取中文文本
        content = file_path.read_text(encoding="utf-8")

        # 按空行切分文档，形成多个知识片段
        chunks = content.split("\n\n")

        for chunk in chunks:
            chunk = chunk.strip()  # 去掉片段首尾的空白字符

            if chunk:  # 跳过空片段
                documents.append({
                    "source": file_path.name,  # 记录来源文件名
                    "content": chunk
                })

    return documents


# ==========================================
# 3. 提取问题中的关键词
# ==========================================


def extract_keywords(question):
    """提取关键词，并给关键问题词设置权重。"""

    keyword_weights = {
        "刻蚀": 2,
        "温度": 3,
        "压力": 3,
        "良率": 3,
        "异常": 2,
        "传感器": 2,
        "温控系统": 2,
        "压力控制阀": 2,
        "真空系统": 2,
        "报警": 2,
        "工艺参数": 2,
        "设备": 1,
        "批次": 1,
        "原因": 2,
        "检查": 2,
        "排查": 2,
        "过高": 2,
        "下降": 2,
    }

    # 只保留出现在问题中的关键词，同时保留其权重
    matched_keywords = {
        keyword: weight
        for keyword, weight in keyword_weights.items()
        if keyword in question
    }

    return matched_keywords


#def extract_keywords(question):
    """从问题中识别本项目支持的关键词。"""

    # 第一版使用预先定义的关键词表，便于理解检索原理
    keyword_list = [
        "刻蚀", "温度", "压力", "良率", "异常",
        "传感器", "温控系统", "压力控制阀",
        "真空系统", "报警", "工艺参数",
        "设备", "批次", "根本原因", "安全"
    ]

    # 如果某个关键词出现在问题中，就把它加入结果
    keywords = [
        keyword
        for keyword in keyword_list
        if keyword in question
    ]

    return keywords


# ==========================================
# 4. 检索相关知识
# ==========================================


def search_knowledge(question, documents):
    """根据关键词权重和问题意图检索知识。"""

    keywords = extract_keywords(question)
    results = []

    if not keywords:
        return [], keywords

    # 判断用户更想了解原因，还是排查方法
    asks_reason = any(
        word in question
        for word in ["为什么", "原因", "怎么导致"]
    )

    asks_check = any(
        word in question
        for word in ["检查", "排查", "怎么办", "应该做什么"]
    )

    for document in documents:
        content = document["content"]

        # 基础分：匹配关键词的权重之和
        score = sum(
            weight
            for keyword, weight in keywords.items()
            if keyword in content
        )

        # 问题问原因时，给包含原因分析的内容适当加分
        if asks_reason and any(
            word in content for word in ["可能影响", "可能与", "原因"]
        ):
            score += 2

        # 问题问检查方法时，给排查建议适当加分
        if asks_check and any(
            word in content for word in ["检查", "核对", "排查"]
        ):
            score += 2

        if score > 0:
            results.append({
                "source": document["source"],
                "content": content,
                "score": score
            })

    # 分数相同时，保留原有文档顺序
    results.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return results[:3], keywords



#def search_knowledge(question, documents):

    keywords = extract_keywords(question)

    if not keywords:
        return [], keywords

    results = []

    for document in documents:

        content = document["content"]

        # 统计当前知识片段包含多少个问题关键词
        score = sum(
            1
            for keyword in keywords
            if keyword in content
        )

        # 分数大于 0，表示至少匹配了一个关键词
        if score > 0:
            results.append({
                "source": document["source"],
                "content": content,
                "score": score
            })

    # 按匹配分数从高到低排序
    results.sort(
        key=lambda item: item["score"],
        #lambda 是一个简短的匿名函数。它告诉 Python：排序时看每条结果字典里的 score。
        reverse=True  #从高到低排列。
    )

    # 只返回分数最高的 3 个片段
    return results[:3], keywords


# ==========================================
# 5. 主程序：接收问题并显示结果
# ==========================================

def main():

    documents = load_documents()

    print(f"知识文档读取完成，共加载 {len(documents)} 个知识片段。")

    if not documents:
        print("没有读取到知识内容，请检查 knowledge_base 文件夹。")
        return

    question = input("\n请输入你的问题：").strip()

    if not question:
        print("问题不能为空。")
        return

    results, keywords = search_knowledge(question, documents)
    #分别接收检索结果和关键词列表。

    print("\n========== 检索结果 ==========")
    print(f"识别到的关键词：{keywords}")

    if not results:
        print("没有找到匹配的知识片段。")
        print("可以尝试询问温度、压力、良率、刻蚀或设备报警相关问题。")
        return

    for number, result in enumerate(results, start=1):
        print(f"\n结果 {number}")
        print(f"来源文件：{result['source']}")
        print(f"匹配分数：{result['score']}")
        print(f"知识内容：\n{result['content']}")


if __name__ == "__main__":
    main()
