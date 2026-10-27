import numpy as np

from sentence_transformers import SentenceTransformer

from openai import OpenAI

from app.analysis.anomalies import format_anomaly_result
from app.config import settings
from app.data.query import query_equipment_data


# =====================================
# 1. 加载环境变量
# =====================================


_client = None


def _get_client():
    global _client
    if _client is None:
        if not settings.deepseek_api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY")
        _client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
    return _client



# =====================================
# 2. 路径设置
# =====================================


BASE_DIR = settings.project_root


KNOWLEDGE_DIR = (

    settings.knowledge_dir

)



# =====================================
# 3. 加载知识库
# =====================================


def load_documents():

    """
    读取半导体知识文档
    """

    documents = []


    for file_path in KNOWLEDGE_DIR.glob("*.txt"):


        content = file_path.read_text(
            encoding="utf-8"
        )


        chunks = content.split(
            "\n\n"
        )


        for chunk in chunks:

            chunk = chunk.strip()


            if chunk:

                documents.append({

                    "source":
                    file_path.name,

                    "content":
                    chunk

                })


    return documents



# =====================================
# 4. 建立向量索引
# =====================================


def build_embeddings(
        documents,
        model
):


    texts = [

        item["content"]

        for item in documents

    ]


    embeddings = model.encode(

        texts,

        normalize_embeddings=True

    )


    return embeddings



# =====================================
# 5. 语义检索
# =====================================


def search_knowledge(

        question,

        documents,

        embeddings,

        model

):


    question_vector = model.encode(

        [question],

        normalize_embeddings=True

    )[0]



    scores = np.dot(

        embeddings,

        question_vector

    )


    # 从高到低排序

    index_list = np.argsort(
        scores
    )[::-1]



    results = []


    for index in index_list[:3]:


        results.append({

            "source":

            documents[index]["source"],


            "content":

            documents[index]["content"],


            "score":

            float(scores[index])

        })


    return results


# =====================================
# 6.1 格式化设备生产数据
# =====================================


def format_equipment_data(equipment_id):

    """
    将数据库中的设备数据
    转换成AI可以理解的文本
    """


    rows = query_equipment_data(
        equipment_id
    )


    if not rows:

        return "没有找到该设备数据"



    text = f"""

设备编号：
{equipment_id}


生产数据：

"""


    for row in rows:


        text += f"""

批次：
{row[1]}

工艺：
{row[3]}

温度：
{row[4]} ℃

压力：
{row[5]} kPa

良率：
{row[6]} %

------------------

"""


    return text


import re


def extract_equipment_id(question):

    """
    从用户问题中提取设备编号

    例如：
    分析ETCH-02异常

    返回：
    ETCH-02
    """


    result = re.search(
        r"ETCH-\d+",  # ETCH- + 数字
        question
    )


    if result:

        return result.group()


    return None


# =====================================
# 6. 构造Prompt
# =====================================


def build_prompt(

        question,

        knowledge,

        equipment_data=None,

        anomaly_result=None

):


    context = ""


    for item in knowledge:


        context += (

            "\n来源："

            + item["source"]

            + "\n"

            + item["content"]

            + "\n"

        )


#告诉模型：不要凭空回答，要参考这些资料" 这就是RAG核心。
    if equipment_data:

        production_context = f"""

以下是设备生产数据：

{equipment_data}

"""

    else:

        production_context = ""

    if anomaly_result:


        anomaly_context = f"""

以下是异常分析结果：

{anomaly_result}

"""


    else:


        anomaly_context = ""

    prompt = f"""         

你是一名半导体设备分析助手。

请根据提供的知识资料回答问题。

要求：

1. 只能依据资料回答。
2. 不确定的信息需要明确说明。
3. 不要编造真实工厂经验。
4. 当前数据属于模拟学习项目。

设备生产数据：

{production_context}


异常分析结果：

{anomaly_context}


知识资料：

{context}


用户问题：

{question}

"""


    return prompt



# =====================================
# 7. 调用DeepSeek
# =====================================


def ask_deepseek(prompt):


    response = _get_client().chat.completions.create(


        model=settings.deepseek_model,


        messages=[


            {

                "role":

                "system",


                "content":

                "你是半导体AI助手"

            },


            {

                "role":

                "user",


                "content":

                prompt

            }

        ],


        temperature=settings.llm_temperature

    )



    return response.choices[0].message.content



# =====================================
# 8. 主程序
# =====================================


def main():


    documents = load_documents()


    print(

        f"加载知识片段：{len(documents)}"

    )



    print(

        "加载Embedding模型..."

    )


    model = SentenceTransformer(settings.embedding_model)



    embeddings = build_embeddings(

        documents,

        model

    )


    print(

        "RAG系统启动完成！"

    )



    while True:


        question = input(

            "\n请输入问题(q退出)："

        )


        if question == "q":

            break



        knowledge = search_knowledge(

            

            question,

            documents,

            embeddings,

            model

        )

        equipment_id = extract_equipment_id(
            question
        )


        equipment_data = None


        if equipment_id:


            equipment_data = format_equipment_data(
                equipment_id
            )

        anomaly_result = None


        if equipment_id:


            anomaly_result = format_anomaly_result(
                equipment_id
            )


        prompt = build_prompt(

            question,

            knowledge,

            equipment_data,

            anomaly_result

        )



        answer = ask_deepseek(

            prompt

        )



        print(

            "\n========== AI回答 =========="

        )


        print(answer)



if __name__ == "__main__":

    main()
