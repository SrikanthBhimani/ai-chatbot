
import base64
import csv
import io
import json
import mimetypes
import uuid
import zipfile
from pathlib import Path, PurePosixPath

import streamlit as st
import streamlit.components.v1 as components
import requests
from google import genai
from google.genai import types
from pypdf import PdfReader
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from supabase import create_client
from datetime import datetime, timezone


st.set_page_config(
    page_title="Cognexa AI",
    page_icon="🧠",
    layout="centered",
)

MODEL = "gemini-3.6-flash"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 100_000
MAX_ZIP_FILES = 30
MAX_ZIP_EXPANDED_BYTES = 20 * 1024 * 1024

TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".xml",
    ".yaml", ".yml", ".log", ".py", ".js", ".ts",
    ".jsx", ".tsx", ".html", ".css", ".sql", ".sh",
    ".ps1", ".bat", ".java", ".kt", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".php",
    ".rb", ".pl", ".r", ".ini", ".cfg", ".conf",
    ".toml", ".properties", ".gitignore", ".env.example",
}

RAW_MIME_TYPES = {
    "image/png", "image/jpeg", "image/webp",
    "audio/webm", "audio/ogg", "audio/mp4",
    "audio/mpeg", "audio/wav", "audio/x-wav",
    "video/mp4", "video/webm", "video/quicktime",
}

st.title("🧠 Cognexa AI")
st.caption("Intelligent Conversations")

composer = components.declare_component(
    "cognexa_composer",
    path=str(Path(__file__).parent / "cognexa_composer"),
)

client = None

try:
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
except Exception:
    pass


if "chats" not in st.session_state:
    st.session_state.chats = {}

if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = None

if "composer_version" not in st.session_state:
    st.session_state.composer_version = 0

if "current_page" not in st.session_state:
    st.session_state.current_page = "chat"

if "image_history" not in st.session_state:
    st.session_state.image_history = []



# Supabase connection
if "supabase_client" not in st.session_state:
    try:
        st.session_state.supabase_client = create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_KEY"],
        )
    except Exception:
        st.error(
            "Could not connect to Supabase. "
            "Check your secrets configuration."
        )
        st.stop()

supabase_client = st.session_state.supabase_client



# Authentication state
if "auth_user_id" not in st.session_state:
    st.session_state.auth_user_id = None

if "auth_email" not in st.session_state:
    st.session_state.auth_email = None


# Authentication screen
if st.session_state.auth_user_id is None:
    st.subheader("Welcome to Cognexa AI")
    st.write("Sign in to access your personal conversations.")

    auth_mode = st.radio(
        "Choose an option",
        ["Log in", "Create account"],
        horizontal=True,
    )

    with st.form("cognexa_auth_form"):
        email = st.text_input("Email address")
        password = st.text_input(
            "Password",
            type="password",
        )

        auth_submit = st.form_submit_button(
            "Log in" if auth_mode == "Log in" else "Create account",
            use_container_width=True,
        )

    if auth_submit:
        if not email.strip() or not password:
            st.error("Please enter your email and password.")
        else:
            try:
                if auth_mode == "Log in":
                    result = supabase_client.auth.sign_in_with_password({
                        "email": email.strip(),
                        "password": password,
                    })

                    if result.user is not None:
                        st.session_state.auth_user_id = str(result.user.id)
                        st.session_state.auth_email = result.user.email
                        st.session_state.chats = {}
                        st.session_state.active_chat_id = None
                        st.rerun()

                else:
                    result = supabase_client.auth.sign_up({
                        "email": email.strip(),
                        "password": password,
                    })

                    if result.session is not None and result.user is not None:
                        st.session_state.auth_user_id = str(result.user.id)
                        st.session_state.auth_email = result.user.email
                        st.rerun()
                    else:
                        st.success(
                            "Account registration submitted. "
                            "Check your email to confirm your account, "
                            "then log in."
                        )

            except Exception:
                st.error(
                    "Authentication failed. Check your credentials "
                    "or account confirmation, and try again."
                )

    st.stop()


def create_chat():
    chat_id = str(uuid.uuid4())
    st.session_state.chats[chat_id] = {
        "title": "New Chat",
        "messages": [],
    }
    st.session_state.active_chat_id = chat_id


def get_active_chat():
    chat_id = st.session_state.active_chat_id
    return st.session_state.chats.get(chat_id)


def load_saved_chats():
    if st.session_state.get("conversations_loaded", False):
        return

    response = (
        supabase_client.table("conversations")
        .select("id, title, messages, updated_at")
        .eq("user_id", st.session_state.auth_user_id)
        .order("updated_at", desc=True)
        .execute()
    )

    for conversation in response.data or []:
        chat_id = str(conversation["id"])

        st.session_state.chats[chat_id] = {
    "title": conversation["title"],
    "messages": conversation["messages"] or [],
    "updated_at": conversation.get("updated_at") or "",
}

    st.session_state.conversations_loaded = True


def save_chat_to_supabase(chat_id):
    active = st.session_state.chats[chat_id]
    updated_at = datetime.now(timezone.utc).isoformat()

    messages_to_save = []
    for message in active["messages"]:
        saved_message = {
            "role": message["role"],
            "content": message["content"],
        }

        if message.get("model_used"):
            saved_message["model_used"] = message["model_used"]

        if message.get("attachments"):
            saved_message["attachments"] = [
                {
                    "name": attachment.get("name", "attachment"),
                    "mime_type": attachment.get(
                        "mime_type", "application/octet-stream"
                    ),
                    "not_persisted": True,
                }
                for attachment in message["attachments"]
            ]

        messages_to_save.append(saved_message)

    supabase_client.table("conversations").upsert(
        {
            "id": chat_id,
            "user_id": st.session_state.auth_user_id,
            "title": active["title"],
            "messages": messages_to_save,
            "updated_at": updated_at,
        },
        on_conflict="id",
    ).execute()
    active["updated_at"] = updated_at


try:
    load_saved_chats()
except Exception:
    st.error("Could not load your saved conversations from Supabase.")
    st.stop()


def extract_text(data, name):
    suffix = Path(name).suffix.lower()

    if suffix in TEXT_EXTENSIONS or name.lower() == ".gitignore":
        return data.decode("utf-8-sig", errors="replace")[:MAX_TEXT_CHARS]

    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages[:100]:
            pages.append(page.extract_text() or "")
        result = "\n".join(pages).strip()

        # Scanned PDFs may need image/OCR processing.
        if not result:
            return None
        return result[:MAX_TEXT_CHARS]

    if suffix == ".docx":
        document = Document(io.BytesIO(data))
        paragraphs = [p.text for p in document.paragraphs if p.text]
        for table in document.tables:
            for row in table.rows:
                paragraphs.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(paragraphs)[:MAX_TEXT_CHARS]

    if suffix == ".xlsx":
        workbook = load_workbook(
            io.BytesIO(data), read_only=True, data_only=True
        )
        output = []
        try:
            for sheet in workbook.worksheets:
                output.append(f"Sheet: {sheet.title}")
                for row in sheet.iter_rows(values_only=True):
                    values = ["" if v is None else str(v) for v in row]
                    if any(values):
                        output.append(" | ".join(values))
                    if len(output) >= 2000:
                        output.append("[Workbook output truncated]")
                        break
                if len(output) >= 2000:
                    break
        finally:
            workbook.close()
        return "\n".join(output)[:MAX_TEXT_CHARS]

    if suffix == ".pptx":
        presentation = Presentation(io.BytesIO(data))
        slides = []
        for number, slide in enumerate(presentation.slides[:100], 1):
            lines = [f"Slide {number}"]
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    if shape.text.strip():
                        lines.append(shape.text.strip())
                if getattr(shape, "has_table", False):
                    for row in shape.table.rows:
                        lines.append(" | ".join(c.text for c in row.cells))
            slides.append("\n".join(lines))
        return "\n".join(slides)[:MAX_TEXT_CHARS]

    return None


def extract_zip(data, name):
    output = []
    expanded_total = 0
    extracted_count = 0

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue

            path = PurePosixPath(item.filename)

            # Reject absolute paths and traversal entries.
            if path.is_absolute() or ".." in path.parts:
                continue

            if item.flag_bits & 0x1:
                continue

            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue

            if item.file_size > 2 * 1024 * 1024:
                continue

            if extracted_count >= MAX_ZIP_FILES:
                output.append("[File count limit reached]")
                break

            if expanded_total + item.file_size > MAX_ZIP_EXPANDED_BYTES:
                output.append("[Archive expansion limit reached]")
                break

            content = archive.read(item)
            expanded_total += len(content)
            extracted_count += 1

            text = content.decode("utf-8-sig", errors="replace")
            output.append(
                f"--- {item.filename} ---\n{text[:20_000]}"
            )

    if not output:
        return "No supported text or source-code files were found in this ZIP."

    return "\n".join(output)[:MAX_TEXT_CHARS]


def attachment_parts(attachment):
    name = attachment["name"]
    data = attachment["data"]
    suffix = Path(name).suffix.lower()

    if suffix in {".exe", ".dll", ".msi", ".bat", ".cmd", ".scr"}:
        return [
            types.Part.from_text(
                text=(
                    f"Attachment '{name}' is an executable or program file. "
                    "Its contents were not executed or uploaded as raw binary. "
                    "Explain that the user can provide source code, a log, "
                    "or a trusted static-analysis report for review."
                )
            )
        ]

    if suffix == ".zip":
        try:
            extracted = extract_zip(data, name)
        except (zipfile.BadZipFile, OSError, RuntimeError):
            raise ValueError(f"Could not safely read ZIP archive: {name}")
        return [
            types.Part.from_text(
                text=f"Contents extracted from ZIP '{name}':\n{extracted}"
            )
        ]

    try:
        text = extract_text(data, name)
    except Exception:
        raise ValueError(
            f"Could not extract readable content from '{name}'. "
            "Check that the file is valid and not password-protected."
        )

    if text is not None:
        if not text.strip():
            text = "[No readable text was found in this file.]"
        return [
            types.Part.from_text(
                text=f"Extracted content from '{name}':\n{text}"
            )
        ]

    mime_type = attachment["mime_type"]

    if suffix == ".pdf":
        mime_type = "application/pdf"

    if mime_type in RAW_MIME_TYPES or suffix == ".pdf":
        return [
            types.Part.from_bytes(
                data=data,
                mime_type=mime_type,
            )
        ]

    return [
        types.Part.from_text(
            text=(
                f"The file '{name}' ({mime_type}) was attached, "
                "but its content format is not yet supported for analysis. "
                "Ask the user for a supported export or readable version."
            )
        )
    ]


# Sidebar
with st.sidebar:
    st.title("🧠 Cognexa AI")

    if st.button("✚  New Chat", use_container_width=True):
        st.session_state.active_chat_id = None
        st.rerun()

    if st.button(":material/photo_library:  Images", use_container_width=True):
       st.session_state.current_page = "images"
       st.rerun()


    if st.button("💻  Code Assistant", use_container_width=True):
        st.session_state.current_page = "code_assistant"
        st.rerun()


    st.divider()
    st.subheader("◷  Chat History")

    chat_ids = [
        chat_id
        for chat_id, chat in st.session_state.chats.items()
        if chat["messages"]
    ]

    chat_ids.sort(
        key=lambda chat_id: st.session_state.chats[chat_id].get(
            "updated_at", ""
        ),
        reverse=True,
    )

    if not chat_ids:
        st.caption("Your saved chats will appear here.")

    for chat_id in chat_ids:
        chat = st.session_state.chats[chat_id]
        if st.button(
            f"💬  {chat['title']}",
            key=f"history_{chat_id}",
            use_container_width=True,
            type="secondary",
        ):
            st.session_state.active_chat_id = chat_id
            st.rerun()

# Images workspace
if st.session_state.current_page == "images":
    st.title("🎨 Images")
    st.caption("Create new images or transform images with Gemini.")

    if st.button("← Back to Chat", key="back_to_chat"):
        st.session_state.current_page = "chat"
        st.rerun()

    st.divider()

    image_mode = st.radio(
        "Choose an action",
        ["Generate image", "Edit image"],
        horizontal=True,
        key="image_mode",
    )

    prompt_examples = {
        "Product photography": (
            "Create a premium product photograph of a modern smartwatch "
            "on a clean studio background with soft lighting."
        ),
        "Nature landscape": (
            "Create a photorealistic mountain landscape at sunrise, "
            "with misty valleys and warm golden light."
        ),
        "Minimalist illustration": (
            "Create a clean, modern illustration with elegant shapes, "
            "balanced composition, and a sophisticated look."
        ),
        "Social media poster": (
            "Create a polished social media poster with a modern layout, "
            "strong visual hierarchy, and attractive colors."
        ),
    }

    selected_example = st.selectbox(
        "Prompt examples",
        ["Choose an example..."] + list(prompt_examples.keys()),
        key="image_prompt_example",
    )

    if st.button("Use selected example", key="use_image_example"):
        if selected_example in prompt_examples:
            st.session_state.image_prompt = prompt_examples[selected_example]

    prompt = st.text_area(
        "Describe the image you want",
        placeholder=(
            "Example: A premium product photo of wireless headphones "
            "on a dark studio background..."
        ),
        key="image_prompt",
        height=120,
    )

    col1, col2 = st.columns(2)

    with col1:
        aspect_ratio = st.selectbox(
            "Aspect ratio",
            ["1:1", "16:9", "9:16", "4:3", "3:4"],
            index=0,
            key="image_aspect_ratio",
        )

    with col2:
        image_size = st.selectbox(
            "Image size",
            ["1K", "2K", "4K"],
            index=0,
            key="image_size",
        )

    uploaded_image = None

    if image_mode == "Edit image":
        uploaded_image = st.file_uploader(
            "Upload an image to edit",
            type=["png", "jpg", "jpeg", "webp"],
            key="image_to_edit",
        )

    generate_clicked = st.button(
        "✨ Generate image" if image_mode == "Generate image"
        else "✨ Edit image",
        type="primary",
        use_container_width=True,
        key="generate_or_edit_image",
    )

    if generate_clicked:
        if not prompt.strip():
            st.warning("Please enter a prompt first.")
        elif image_mode == "Edit image" and uploaded_image is None:
            st.warning("Please upload an image to edit.")
        else:

            try:
                with st.spinner("Creating your image..."):
                    if image_mode == "Generate image":
                        cloudflare_token = st.secrets[
                            "CLOUDFLARE_API_TOKEN"
                        ]
                        cloudflare_account_id = (
                            "411e02c2ac15dacd76fcf716a409ea6a"
                        )
                        cloudflare_url = (
                            "https://api.cloudflare.com/client/v4/accounts/"
                            f"{cloudflare_account_id}/ai/run/"
                            "@cf/black-forest-labs/flux-1-schnell"
                        )

                        response = requests.post(
                            cloudflare_url,
                            headers={
                                "Authorization": (
                                    f"Bearer {cloudflare_token}"
                                ),
                                "Content-Type": "application/json",
                            },
                            json={"prompt": prompt.strip()},
                            timeout=90,
                        )

                        if response.status_code == 429:
                            raise RuntimeError(
                                "Cloudflare image-generation rate limit "
                                "reached. Please try again later."
                            )

                        response.raise_for_status()
                        result = response.json().get("result", {})
                        image_data = result.get("image")

                        if not image_data:
                            raise RuntimeError(
                                "Cloudflare returned no image. "
                                "Please try again."
                            )

                        image_bytes = base64.b64decode(image_data)
                        image_mime_type = "image/png"

                    else:
                        image_input = [
                            {
                                "type": "text",
                                "text": prompt.strip(),
                            },
                            {
                                "type": "image",
                                "data": base64.b64encode(
                                    uploaded_image.getvalue()
                                ).decode("utf-8"),
                                "mime_type": uploaded_image.type,
                            },
                        ]

                        interaction = client.interactions.create(
                            model="gemini-3.1-flash-image",
                            input=image_input,
                            response_format={
                                "type": "image",
                                "mime_type": "image/jpeg",
                                "aspect_ratio": aspect_ratio,
                                "image_size": image_size,
                            },
                            timeout=120,
                        )

                        generated_image = interaction.output_image

                        if (
                            not generated_image
                            or not generated_image.data
                        ):
                            raise RuntimeError(
                                "The model did not return an image. "
                                "Please try a different prompt."
                            )

                        image_bytes = base64.b64decode(
                            generated_image.data
                        )
                        image_mime_type = "image/jpeg"

                    st.session_state.image_history.insert(
                        0,
                        {
                            "prompt": prompt.strip(),
                            "mode": image_mode,
                            "data": base64.b64encode(
                                image_bytes
                            ).decode("utf-8"),
                            "mime_type": image_mime_type,
                            "aspect_ratio": aspect_ratio,
                            "image_size": image_size,
                        },
                    )

            except Exception as error:
                error_message = str(error).lower()

                if "timeout" in error_message or "timed out" in error_message:
                    st.error(
                        "Image generation timed out. "
                        "Please try again later."
                    )
                else:
                    st.error(f"Image request failed: {error}")


    st.divider()
    st.subheader("Your image history")

    if not st.session_state.image_history:
        st.caption(
            "Your generated and edited images will appear here."
        )

    for index, image_item in enumerate(
        st.session_state.image_history
    ):
        st.markdown(f"**{image_item['mode']}**")
        st.caption(image_item["prompt"])

        image_bytes = base64.b64decode(image_item["data"])
        st.image(image_bytes, use_container_width=True)

        st.caption(
            f"{image_item['aspect_ratio']} · "
            f"{image_item['image_size']}"
        )

        st.download_button(
            "⬇️ Download image",
            data=image_bytes,
            file_name=f"cognexa_image_{index + 1}.{'png' if image_item['mime_type'] == 'image/png' else 'jpg'}",
            mime=image_item["mime_type"],
            key=f"download_image_{index}",
            use_container_width=True,
        )

        st.divider()

    st.stop()


# Code Assistant workspace
if st.session_state.current_page == "code_assistant":
    st.title("💻 Code Assistant")
    st.caption("Generate, explain, debug, and improve code with Gemini.")

    if st.button("← Back to Chat", key="code_back_to_chat"):
        st.session_state.current_page = "chat"
        st.rerun()

    st.divider()

    task = st.selectbox(
        "What would you like to do?",
        ["Generate code", "Explain code", "Debug errors", "Improve code"],
        key="code_assistant_task",
    )

    language = st.selectbox(
        "Programming language",
        [
            "Python", "JavaScript", "TypeScript", "Java", "C#",
            "C++", "Go", "Rust", "SQL", "PowerShell", "Bash",
            "HTML/CSS", "Ansible", "Other",
        ],
        key="code_assistant_language",
    )

    request = st.text_area(
        "Describe what you need",
        placeholder="Describe the program, explain your goal, or paste the error message...",
        height=120,
        key="code_assistant_request",
    )

    source_code = st.text_area(
        "Your existing code (not required for Generate code)",
        placeholder="Paste your code here...",
        height=220,
        key="code_assistant_source",
    )

    if st.button(
        "✨ Run Code Assistant",
        type="primary",
        use_container_width=True,
        key="run_code_assistant",
    ):
        if client is None:
            st.error("Gemini is unavailable. Check your GEMINI_API_KEY configuration.")
        elif not request.strip():
            st.warning("Please describe what you want the Code Assistant to do.")
        elif task != "Generate code" and not source_code.strip():
            st.warning("Please paste your existing code for this task.")
        else:
            prompt = f"""
You are Cognexa AI's programming assistant.

Task: {task}
Programming language: {language}

User's requirements or error description:
{request}

Existing code:
{source_code if source_code.strip() else "No existing code provided."}

Instructions:
- For Generate code, provide a complete solution where practical.
- For Explain code, explain the code clearly, step by step.
- For Debug errors, identify likely causes and provide corrected code.
- For Improve code, suggest improvements while preserving intended behavior.
- Use Markdown headings and fenced code blocks for code.
- Explain important changes and assumptions.
- If essential information is missing, state your assumptions.
- Never claim you executed or tested code unless you actually did.
- Do not execute the supplied code.
"""

            try:
                with st.spinner("Cognexa AI is working on your code..."):
                    response = client.models.generate_content(
                        model=MODEL,
                        contents=prompt,
                    )

                answer = response.text

                if answer:
                    st.session_state.code_assistant_result = answer
                    st.success("Code Assistant completed!")
                else:
                    st.error("Gemini returned an empty response.")

            except Exception as error:
                st.error(f"Code Assistant failed: {error}")

    result = st.session_state.get("code_assistant_result")


    if result:
        st.divider()
        st.subheader("Result")

        extension_map = {
            "Python": "py",
            "JavaScript": "js",
            "TypeScript": "ts",
            "Java": "java",
            "C#": "cs",
            "C++": "cpp",
            "Go": "go",
            "Rust": "rs",
            "SQL": "sql",
            "PowerShell": "ps1",
            "Bash": "sh",
            "HTML/CSS": "html",
            "Ansible": "yml",
            "Other": "txt",
        }

        language_aliases = {
            "python": "python", "py": "python",
            "javascript": "javascript", "js": "javascript",
            "typescript": "typescript", "ts": "typescript",
            "java": "java", "csharp": "csharp", "cs": "csharp",
            "cpp": "cpp", "c++": "cpp", "go": "go",
            "rust": "rust", "sql": "sql",
            "powershell": "powershell", "ps1": "powershell",
            "bash": "bash", "sh": "bash", "html": "html",
            "css": "css", "yaml": "yaml", "yml": "yaml",
            "json": "json", "xml": "xml",
        }

        parts = result.split("```")
        has_code = False
        code_number = 0

        for index, part in enumerate(parts):
            if index % 2 == 0:
                if part.strip():
                    st.markdown(part)
            else:
                lines = part.splitlines()
                code_text = part.strip("\n")
                fence_language = ""

                if lines:
                    first_line = lines[0].strip().lower()
                    first_word = first_line.split()[0] if first_line else ""

                    if first_word in language_aliases:
                        fence_language = language_aliases[first_word]
                        code_text = "\n".join(lines[1:]).strip("\n")

                if code_text.strip():
                    has_code = True
                    code_number += 1

                    display_language = (
                        fence_language
                        or language_aliases.get(language.lower(), "")
                    )

                    st.code(
                        code_text,
                        language=display_language or None,
                        line_numbers=True,
                    )

                    extension = extension_map.get(language, "txt")

                    st.download_button(
                        "⬇️ Download code file",
                        data=code_text,
                        file_name=f"cognexa_code_{code_number}.{extension}",
                        mime="text/plain",
                        key=f"download_code_block_{code_number}",
                    )

        if not has_code:
            st.info("No formatted code block was detected.")
            st.download_button(
                "⬇️ Download full response",
                data=result,
                file_name="cognexa_code_assistant_result.md",
                mime="text/markdown",
                key="download_code_response_markdown",
            )
    st.stop()


# Display conversation
active_chat = get_active_chat()

if active_chat is not None:
    for message in active_chat["messages"]:
        with st.chat_message(message["role"]):
            content = message["content"]
            st.markdown(content)

            # Show a real download button for explicitly named text files.
            if message["role"] == "assistant":
                import re

                file_pattern = (
                    r"```text-file:([A-Za-z0-9_.-]+\.txt)\s*\n"
                    r"(.*?)"
                    r"\n```"
                )

                for file_index, match in enumerate(
                    re.finditer(file_pattern, content, re.DOTALL)
                ):
                    file_name = match.group(1)
                    file_content = match.group(2)

                    st.download_button(
                        label=f"📥 Download {file_name}",
                        data=file_content.encode("utf-8"),
                        file_name=file_name,
                        mime="text/plain",
                        key=(
                            f"chat_file_{st.session_state.active_chat_id}_"
                            f"{id(message)}_{file_index}"
                        ),
                    )

            if message["role"] == "assistant" and message.get("model_used"):
                st.caption(f"Powered by {message['model_used']}")

            for attachment in message.get("attachments", []):
                mime_type = attachment.get(
                    "mime_type", "application/octet-stream"
                )
                data = attachment.get("data")
                name = attachment.get("name", "attachment")

                if data is None:
                    st.caption(
                        f"📎 Attached: {name} "
                        "(file contents are not available in this saved message)"
                    )
                    continue

                if mime_type.startswith("image/"):
                    st.image(data, caption=name, use_container_width=True)
                elif mime_type.startswith("audio/"):
                    st.audio(data, format=mime_type)
                else:
                    st.caption(f"📎 Attached: {name}")


st.markdown("#### Chat with Cognexa AI")

submitted = composer(
    key=f"composer_{st.session_state.composer_version}",
    default=None,
    height=150,
)


def submit_message(text, attachments):
    active = get_active_chat()

    if active is None:
        create_chat()
        active = get_active_chat()

    if not text:
        if any(a["mime_type"].startswith("audio/") for a in attachments):
            text = (
                "Please transcribe this voice message and answer "
                "the spoken question."
            )
        elif attachments:
            text = "Please analyze the attached file(s)."

    user_message = {
        "role": "user",
        "content": text,
        "attachments": attachments,
    }


    contents = []

    import re

    wants_downloadable_file = bool(
        re.search(
            r"\b(download|downloadable|add lines|modify|edit the file|"
            r"update the file|create a file|return the file|"
            r"give me the file|save as)\b",
            text,
            re.IGNORECASE,
        )
    )

    # Prepare the full conversation, including the new message.
    for message in active["messages"] + [user_message]:
        role = "user" if message["role"] == "assistant" else message["role"]
        role = "model" if role == "assistant" else role
        parts = [types.Part.from_text(text=message["content"])]

        if message is user_message and wants_downloadable_file:
            parts.append(
                types.Part.from_text(
                    text=(
                        "IMPORTANT: Return a real downloadable text file, "
                        "not manual-save instructions. Return the COMPLETE "
                        "file contents in exactly this format:\n"
                        "```text-file:Test_file_this.txt\n"
                        "COMPLETE FILE CONTENT HERE\n"
                        "```\n"
                        "Use the appropriate .txt filename. Preserve all "
                        "existing content when modifying an uploaded file. "
                        "Do not omit any content."
                    )
                )
            )

        for attachment in message.get("attachments", []):
            if "data" not in attachment:
                continue
            parts.extend(attachment_parts(attachment))

        contents.append(types.Content(role=role, parts=parts))

    try:
        with st.spinner("Cognexa AI is thinking..."):
            if client is None:
                raise RuntimeError("Gemini is unavailable.")
            model_used = "Gemini"
            response = client.models.generate_content(
                model=MODEL,
                contents=contents,
            )

        answer = response.text or (
            "I couldn't generate a response. Please try again."
        )

    except ValueError as error:
        st.error(str(error))
        return
    except Exception as gemini_error:
        # Keep attachment processing on Gemini for now.
        if attachments or any(
            message.get("attachments")
            for message in active["messages"]
        ):
            st.error(
                "Gemini is unavailable, and this conversation "
                "contains attachments. Please try again later."
            )
            st.caption(str(gemini_error))
            return

        # Fall back to the local Ollama model for text conversations.
        try:
            ollama_messages = [
                {
                    "role": (
                        "assistant"
                        if message["role"] == "assistant"
                        else message["role"]
                    ),
                    "content": message["content"],
                }
                for message in active["messages"] + [user_message]
            ]

            with st.spinner("Using local Ollama AI..."):
                model_used = "Ollama · llama3.2:1b"
                response = requests.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": "llama3.2:1b",
                        "messages": ollama_messages,
                        "stream": False,
                    },
                    timeout=120,
                )
                response.raise_for_status()
                answer = response.json()["message"]["content"]

            if not answer:
                answer = "I couldn't generate a response. Please try again."

        except Exception as ollama_error:
            st.error(
                "Neither Gemini nor local Ollama could process "
                "this request. Check that Ollama is running."
            )
            st.caption(f"Ollama error: {ollama_error}")
            return


    active["messages"].append(user_message)

    if active["title"] == "New Chat":
        active["title"] = text[:35] + ("..." if len(text) > 35 else "")

    active["messages"].append({
    "role": "assistant",
    "content": answer,
    "model_used": model_used,
    })

    save_chat_to_supabase(st.session_state.active_chat_id)
    st.session_state.composer_version += 1
    st.rerun()


if submitted and isinstance(submitted, dict):
    text = str(submitted.get("text") or "").strip()
    encoded_files = submitted.get("files") or []

    attachments = []
    total_bytes = 0

    for file_info in encoded_files:
        name = str(file_info.get("name") or "attachment")
        raw_mime = str(file_info.get("mime_type") or "").lower()
        mime_type = raw_mime.split(";")[0].strip()

        try:
            data = base64.b64decode(
                file_info.get("data", ""),
                validate=True,
            )
        except Exception:
            st.error(f"Could not read the attachment: {name}")
            st.stop()

        total_bytes += len(data)

        if total_bytes > MAX_UPLOAD_BYTES:
            st.error("Please keep the combined attachment size under 15 MB.")
            st.stop()

        if not mime_type or mime_type == "application/octet-stream":
            mime_type = (
                mimetypes.guess_type(name)[0]
                or "application/octet-stream"
            )

        attachments.append({
            "name": name,
            "mime_type": mime_type,
            "data": data,
        })

    if text or attachments:
        submit_message(text, attachments)

