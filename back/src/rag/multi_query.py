import json
import re

from src.const.models import create_openai_model
from src.prompt.multi_query_prompt import MULTI_QUERY_PROMPT

model = create_openai_model()


def parse_queries(content):
    """모델의 답에서 검색어 목록을 꺼낸다. 해석할 수 없거나 검색어가 하나도 없으면 None.

    받아들이는 모양: {"queries": [{"query": "..."}]}, [{"query": "..."}], ["...", "..."], 그리고 ```json 코드 블록으로 감싼 것.
    """
    text = str(content).strip()
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return None
    items = result.get("queries") if isinstance(result, dict) else result
    if not isinstance(items, list):
        return None
    queries = []
    for item in items:
        value = item.get("query") if isinstance(item, dict) else item
        if isinstance(value, str) and value.strip():
            queries.append(value.strip())
    return queries or None


def multi_query(question):
    response = model.invoke(
        [
            {"role": "system", "content": MULTI_QUERY_PROMPT},
            {"role": "user", "content": question},
        ]
    )

    queries = parse_queries(response.content)
    if queries is None:
        # 모델이 약속한 모양과 다르게 답해도(예: queries로 감싸지 않은 목록) 그래프 전체를 죽이지 않는다.
        print("멀티 쿼리 응답을 해석하지 못해 원래 질문으로 검색합니다:", str(response.content)[:200])
        queries = [question.strip()]

    queries = list(dict.fromkeys(queries))[:3]

    print("queries:", queries)

    return queries
