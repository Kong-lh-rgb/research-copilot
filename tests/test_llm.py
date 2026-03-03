from app.infrastructure.llm.llm import get_llm

def test_llm():
    llm = get_llm()
    messages = [
        {"role": "user", "content": "你是谁?"},
    ]
    response = llm.chat(messages)
    print(response)

if __name__ == "__main__":
    test_llm()