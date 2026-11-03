from src.const.models import create_openai_model
from src.prompt.query_rewrite_prompt import QUERY_REWRITE_PROMPT, RETRY_CONTEXT_FUNC

model = create_openai_model()


def query_rewrite(original_question, retry_count, previous_queries):

    retry_context = ""

    if retry_count > 0:
        retry_context = RETRY_CONTEXT_FUNC(retry_count, previous_queries)

    response = model.invoke(
        [
            {"role": "system", "content": QUERY_REWRITE_PROMPT},
            {
                "role": "user",
                "content": f"원본 질문: {original_question}\n\n{retry_context}",
            },
        ]
    )

    return response.content
