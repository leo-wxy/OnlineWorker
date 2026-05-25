from core.providers.interactions import (
    ProviderQuestionRequest,
    parse_standard_question_request,
)


def test_parse_standard_question_request_uses_fixed_core_shape():
    request = parse_standard_question_request(
        {
            "questionId": "que-1",
            "threadId": "thread-1",
            "header": "Runtime",
            "question": "Pick options",
            "options": [
                {"label": "A", "description": "Alpha"},
                {"label": "B", "description": "Beta"},
            ],
            "multiple": True,
            "custom": False,
            "subIndex": 1,
            "subTotal": 2,
        },
        provider_id="claude",
        default_thread_id="thread-fallback",
        question_source="app_server",
    )

    assert request == ProviderQuestionRequest(
        question_id="que-1",
        thread_id="thread-1",
        header="Runtime",
        question="Pick options",
        options=[
            {"label": "A", "description": "Alpha"},
            {"label": "B", "description": "Beta"},
        ],
        multiple=True,
        custom=False,
        sub_index=1,
        sub_total=2,
        tool_type="claude",
        question_source="app_server",
    )
