
import uuid

import streamlit as st
from google import genai


# Page configuration
st.set_page_config(
    page_title="Cognexa AI",
    page_icon="🧠",
    layout="centered"
)

MODEL = "gemini-3.5-flash-lite"

st.title("🤖 Cognexa AI")
st.caption("Intelligent Conversations")


# Gemini configuration — keep the existing secret
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
except Exception:
    st.error("Gemini API key is not configured.")
    st.info(
        "For local use, add GEMINI_API_KEY "
        "to .streamlit/secrets.toml."
    )
    st.stop()


# Create a new conversation
def create_chat():
    chat_id = str(uuid.uuid4())

    st.session_state.chats[chat_id] = {
        "title": "New Chat",
        "messages": []
    }

    st.session_state.active_chat_id = chat_id


# Initialize conversation state
if "chats" not in st.session_state:
    st.session_state.chats = {}

if "active_chat_id" not in st.session_state:
    create_chat()


# Sidebar: New Chat and Chat History
with st.sidebar:
    st.title("🤖 Cognexa AI")

    if st.button("＋ New Chat", use_container_width=True):
        create_chat()
        st.rerun()

    st.divider()
    st.subheader("Chat History")

    # Show only conversations that contain messages
    chat_ids = [
        chat_id
        for chat_id, chat in st.session_state.chats.items()
        if chat["messages"]
    ]

    # Most recently created conversations first
    chat_ids.reverse()

    if not chat_ids:
        st.caption("Your conversations will appear here.")

    for chat_id in chat_ids:
        chat = st.session_state.chats[chat_id]

        if st.button(
            chat["title"],
            key=f"chat_{chat_id}",
            use_container_width=True,
            type=(
                "primary"
                if chat_id == st.session_state.active_chat_id
                else "secondary"
            ),
        ):
            st.session_state.active_chat_id = chat_id
            st.rerun()


# Get the currently selected conversation
active_chat = st.session_state.chats[
    st.session_state.active_chat_id
]


# Display the selected conversation's messages
for message in active_chat["messages"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# Chat input
user_message = st.chat_input("Ask me anything...")

if user_message:
    # Save the user's message
    active_chat["messages"].append({
        "role": "user",
        "content": user_message
    })

    # Automatically name the conversation
    if active_chat["title"] == "New Chat":
        active_chat["title"] = (
            user_message[:35] + "..."
            if len(user_message) > 35
            else user_message
        )

    # Prepare conversation history for Gemini
    contents = [
        {
            "role": (
                "user" if message["role"] == "user"
                else "model"
            ),
            "parts": [{"text": message["content"]}],
        }
        for message in active_chat["messages"]
    ]

    # Generate the response
    try:
        with st.spinner("Cognexa AI is thinking..."):
            response = client.models.generate_content(
                model=MODEL,
                contents=contents,
            )

        answer = (
            response.text
            or "I couldn't generate a response. Please try again."
        )

    except Exception as error:
        st.error(f"Gemini request failed: {error}")
        active_chat["messages"].pop()
        st.stop()

    # Save the assistant's response
    active_chat["messages"].append({
        "role": "assistant",
        "content": answer
    })

    # Refresh the conversation and sidebar
    st.rerun()
