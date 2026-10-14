
import streamlit as st
from google import genai

st.set_page_config(
    page_title="Cognexa AI",
    page_icon="🧠",
    layout="centered"
)

st.title("🤖 Cognexa AI")
st.caption("Intelligent Conversations")

# Read the API key from Streamlit secrets
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
except Exception:
    st.error("Gemini API key is not configured.")
    st.info("For local use, add GEMINI_API_KEY to .streamlit/secrets.toml.")
    st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []

if st.button("New Chat"):
    st.session_state.messages = []
    st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

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
                response = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=[
                        {
                            "role": "user" if m["role"] == "user" else "model",
                            "parts": [{"text": m["content"]}],
                        }
                        for m in st.session_state.messages
                    ],
                )
                answer = response.text or "I couldn't generate a response."
                st.markdown(answer)
                st.session_state.messages.append(
                    {"role": "assistant", "content": answer}
                )
            except Exception as error:
                st.error(f"Gemini request failed: {error}")
                st.session_state.messages.pop()
