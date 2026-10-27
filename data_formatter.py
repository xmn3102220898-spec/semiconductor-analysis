from database_query import query_equipment_data



def format_equipment_data(equipment_id):

    """
    将数据库查询结果转换成AI容易理解的文本
    """


    rows = query_equipment_data(
        equipment_id
    )


    if not rows:

        return "没有找到该设备生产数据"



    text = f"""
设备编号：
{equipment_id}


生产记录：

"""


    for row in rows:


        batch_id = row[1]

        equipment = row[2]

        process = row[3]

        temperature = row[4]

        pressure = row[5]

        yield_pct = row[6]


        text += f"""

批次：
{batch_id}

工艺：
{process}

温度：
{temperature} ℃

压力：
{pressure} kPa

良率：
{yield_pct} %

------------------

"""


    return text



if __name__ == "__main__":


    result = format_equipment_data(
        "ETCH-02"
    )


    print(result)