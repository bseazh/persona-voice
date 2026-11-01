import json

from app.deepseek import DeepSeekConfig, DeepSeekClient


def test_reply_payload_and_result():
    calls = []

    def transport(method, url, headers, body, timeout):
        calls.append((method, url, headers, body, timeout))
        return 200, json.dumps({"choices": [{"message": {"content": "你好，我是小禾。"}}]}).encode()

    client = DeepSeekClient(DeepSeekConfig(api_key="test-key"), transport)
    assert client.reply("你好", []) == "你好，我是小禾。"
    payload = json.loads(calls[0][3])
    assert payload["model"] == "deepseek-chat"
    assert payload["messages"][-1] == {"role": "user", "content": "你好"}
    assert calls[0][2]["Authorization"] == "Bearer test-key"
