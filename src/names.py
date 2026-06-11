"""队名归一化：FIFA 官方接口与历史赛果数据集对同一国家队的叫法不同。

这里只做名称翻译，不是数据本身；映射关系已逐一核对过两边数据源中
均真实存在对应条目（见 README「数据校验」一节）。
"""

FIFA_TO_HISTORY = {
    "Cabo Verde": "Cape Verde",
    "Congo DR": "DR Congo",
    "Czechia": "Czech Republic",
    "Côte d'Ivoire": "Ivory Coast",
    "IR Iran": "Iran",
    "Korea Republic": "South Korea",
    "Türkiye": "Turkey",
    "USA": "United States",
}


def normalize(fifa_name):
    return FIFA_TO_HISTORY.get(fifa_name, fifa_name)
