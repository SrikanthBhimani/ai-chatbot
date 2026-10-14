
import streamlit as st
import requests

st.set_page_config(
    page_title="My AI Chatbot",
    page_icon="🤖"
)

st.title("🤖 My Local AI Chatbot")
st.caption("Powered by Ollama — no paid AI API required")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display previous messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
user_message = st.chat_input("Ask me anything...")

if user_message:
    st.session_state.messages.append(
        {"role": "user", "content": user_message}
    )

    with st.chat_message("user"):
        st.markdown(user_message)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response = requests.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": "llama3.2:1b",
                        "messages": st.session_state.messages,
                        "stream": False
                    },
                    timeout=120
                )

                response.raise_for_status()
                answer = response.json()["message"]["content"]
                st.markdown(answer)

                st.session_state.messages.append(
                    {"role": "assistant", "content": answer}
                )

            except requests.RequestException as error:
                st.error(f"Could not connect to Ollama: {error}")
                st.info("Check that Ollama is running on your PC.")
                st.session_state.messages.pop()
