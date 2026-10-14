
import requests

print("Welcome to My Local AI Chatbot!")
print("I can remember our conversation.")
print("Type 'exit' to quit.\n")

# Store the conversation
messages = []

while True:
    user_message = input("You: ")

    if user_message.lower() == "exit":
        print("Chatbot: Goodbye!")
        break

    # Add the user's message to conversation history
    messages.append({
        "role": "user",
        "content": user_message
    })

    try:
        response = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "llama3.2:1b",
                "messages": messages,
                "stream": False
            },
            timeout=120
        )

        response.raise_for_status()
        answer = response.json()["message"]["content"]

        print(f"\nChatbot: {answer}\n")

        # Save the chatbot's response for future context
        messages.append({
            "role": "assistant",
            "content": answer
        })

    except requests.RequestException as error:
        print(f"Error connecting to Ollama: {error}")
        messages.pop()  # Remove the unanswered user message
