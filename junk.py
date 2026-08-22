import ollama

while True:
    user_input = input("You: ")

    if user_input.lower() in {"exit", "quit"}:
        break

    response = ollama.chat(
            model="llama3.2",
            messages=[
                {"role": "user", "content": user_input}
            ],
    )

print("AI:", response["message"]["content"])
