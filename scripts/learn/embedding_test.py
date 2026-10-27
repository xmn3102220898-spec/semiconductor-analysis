
from sentence_transformers import SentenceTransformer
#加载已经训练好的文本向量模型
from sklearn.metrics.pairwise import cosine_similarity

from app.config import settings


# ==========================================
# 1. 准备测试文本
# ==========================================

sentences = [
    "刻蚀设备温度异常",
    "温控系统出现温度偏移",
    "检查压力控制阀",
    "晶圆封装工艺流程"
]


# ==========================================
# 2. 加载文本向量模型
# ==========================================

# 首次运行可能需要下载模型
# paraphrase-multilingual-MiniLM-L12-v2 支持多语言文本
model = SentenceTransformer(settings.embedding_model)


# ==========================================
# 3. 将文本转换成向量
# ==========================================

# 每句话都会转换为一组数字
# normalize_embeddings=True 将向量归一化，便于比较
embeddings = model.encode(   #把文本转换为向量
    sentences,
    normalize_embeddings=True
)

print("文本数量：", len(sentences))
print("向量矩阵形状：", embeddings.shape)#查看向量矩阵的形状

# 查看第一句话的向量前 5 个数字
print("第一句话的向量前5个数字：")
print(embeddings[0][:5])


# ==========================================
# 4. 计算句子之间的相似度
# ==========================================

# 归一化后的向量可以直接用矩阵乘法计算余弦相似度
similarity_matrix = cosine_similarity(embeddings)
                    #计算文本向量之间的余弦相似度
print("\n========== 语义相似度 ==========")

# 双重循环：逐一比较每两句话
for i in range(len(sentences)):
    for j in range(i + 1, len(sentences)):

        # similarity_matrix[i][j] 表示第 i 句和第 j 句的相似度
        score = similarity_matrix[i][j]

        print(f"\n句子 A：{sentences[i]}")
        print(f"句子 B：{sentences[j]}")
        print(f"相似度：{score:.4f}")#将数字格式化为保留四位小数
