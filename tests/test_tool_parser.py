from src.tools.parser import parse_response_with_tools


def test_parse_tool_call_primary_wrapper():
    response = (
        "<tool_call>\n"
        '{"name":"hangup_call","arguments":{"farewell_message":"Thank you, goodbye!"}}\n'
        "</tool_call>\n"
        "Thank you, goodbye!"
    )
    clean_text, tool_calls = parse_response_with_tools(response)

    assert clean_text == "Thank you, goodbye!"
    assert tool_calls == [
        {"name": "hangup_call", "parameters": {"farewell_message": "Thank you, goodbye!"}}
    ]


def test_parse_tool_call_named_tag_wrapper_with_name_field():
    response = (
        "<hangup_call>\n"
        '{"name":"hangup_call","arguments":{"farewell_message":"Bye"}}\n'
        "</hangup_call>\n"
        "Bye"
    )
    clean_text, tool_calls = parse_response_with_tools(response)

    assert clean_text == "Bye"
    assert tool_calls == [{"name": "hangup_call", "parameters": {"farewell_message": "Bye"}}]


def test_parse_tool_call_named_tag_wrapper_compact_params():
    response = (
        "<hangup_call>\n"
        '{"farewell_message":"Bye"}\n'
        "</hangup_call>\n"
        "Bye"
    )
    clean_text, tool_calls = parse_response_with_tools(response)

    assert clean_text == "Bye"
    assert tool_calls == [{"name": "hangup_call", "parameters": {"farewell_message": "Bye"}}]


def test_named_tag_without_json_is_not_parsed_as_tool_call():
    response = "<hangup_call>not-json</hangup_call>\nBye"
    clean_text, tool_calls = parse_response_with_tools(response)

    assert clean_text == response
    assert tool_calls is None

