"""FastAPI web app."""
import logging
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import storage, response_generator, image_extractor

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
INSTRUCTIONS_PATH = BASE_DIR / "instructions" / "framework.md"

app = FastAPI(title="LinkedIn Responder")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

UPLOADS_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


@app.on_event("startup")
async def startup():
    storage.init_db()
    storage.fail_stuck_sessions()


# --- Index ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    pending = [dict(r) for r in storage.get_pending_sessions()]
    conversations = [dict(r) for r in storage.list_conversations()]
    return templates.TemplateResponse(request, "index.html", {
        "pending": pending,
        "conversations": conversations,
    })


# --- New message ---

@app.get("/new", response_class=HTMLResponse)
async def new_message_form(request: Request, conv_id: int = None):
    conversations = [dict(r) for r in storage.list_conversations()]
    selected_conv = None
    if conv_id:
        row = storage.get_conversation(conv_id)
        if row:
            selected_conv = dict(row)
    return templates.TemplateResponse(request, "new_message.html", {
        "conversations": conversations,
        "selected_conv": selected_conv,
    })


def _process_message(
    session_id: int,
    msg_id: int,
    conv_id: int,
    body: str,
    sender_name: str,
    screenshot_path: str,
    history: list,
    feedback_history: list,
):
    """Background thread: extract name/body if needed, generate responses, mark ready."""
    try:
        # Extract from screenshot if no body yet
        if not body and screenshot_path:
            extracted = image_extractor.extract_from_screenshot(screenshot_path)
            body = extracted["message_body"]
            if not sender_name or sender_name == "Unknown":
                sender_name = extracted["sender_name"] or "Unknown"
            storage.update_message(msg_id, body, sender_name)
            storage.update_conversation_participant(conv_id, sender_name)

        if not body:
            storage.update_session_status(session_id, "error", "Could not extract message text from screenshot")
            return

        # Always try to extract name from text if still unknown
        if sender_name == "Unknown":
            extracted_name = image_extractor.extract_name_from_text(body)
            if extracted_name:
                sender_name = extracted_name
                storage.update_message(msg_id, body, sender_name)
                storage.update_conversation_participant(conv_id, sender_name)

        responses = response_generator.generate_responses(
            message_body=body,
            sender_name=sender_name,
            conversation_history=history,
            feedback_history=feedback_history,
        )
        storage.save_generated_responses(session_id, responses)
        storage.update_session_status(session_id, "ready")
    except Exception as e:
        logger.error("Background processing failed for session %s: %s", session_id, e)
        storage.update_session_status(session_id, "error", str(e))


@app.post("/new")
async def submit_new_message(
    request: Request,
    message_body: str = Form(""),
    sender_name: str = Form(""),
    conversation_id: str = Form(""),   # existing conv id or ""
    new_conv_name: str = Form(""),     # name if creating new conv
    screenshot: UploadFile = File(None),
):
    screenshot_path = ""

    # Handle screenshot upload (fast — just saves file to disk)
    if screenshot and screenshot.filename:
        suffix = Path(screenshot.filename).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            raise HTTPException(status_code=400, detail="Unsupported image type")
        fname = f"{uuid.uuid4()}{suffix}"
        dest = UPLOADS_DIR / fname
        with dest.open("wb") as f:
            shutil.copyfileobj(screenshot.file, f)
        screenshot_path = str(dest)

    body = message_body.strip()
    final_sender = sender_name.strip() or "Unknown"

    if not body and not screenshot_path:
        raise HTTPException(status_code=400, detail="Message body or screenshot is required")

    # Resolve or create conversation
    if conversation_id.strip():
        conv_id = int(conversation_id)
    elif new_conv_name.strip():
        existing = storage.find_conversation_by_name(new_conv_name.strip())
        conv_id = existing["id"] if existing else storage.create_conversation(new_conv_name.strip())
    else:
        # Don't reuse an "Unknown" conversation — always create a fresh one so
        # the background thread can rename it once the real name is extracted.
        if final_sender != "Unknown":
            existing = storage.find_conversation_by_name(final_sender)
            conv_id = existing["id"] if existing else storage.create_conversation(final_sender)
        else:
            conv_id = storage.create_conversation("Unknown")

    # Save message immediately (placeholder body if screenshot-only)
    msg_id = storage.add_message(
        conversation_id=conv_id,
        sender_name=final_sender,
        body=body or "(extracting...)",
        is_mine=False,
        screenshot_path=screenshot_path,
    )

    # Create session in processing state
    session_id = storage.create_response_session(msg_id)

    # Snapshot history before starting thread
    history = [dict(m) for m in storage.get_conversation_messages(conv_id)]
    feedback_history = storage.get_feedback_history()

    # Start background processing and redirect immediately
    threading.Thread(
        target=_process_message,
        args=(session_id, msg_id, conv_id, body, final_sender, screenshot_path, history, feedback_history),
        daemon=True,
    ).start()

    return RedirectResponse(url=f"/session/{session_id}", status_code=303)


# --- Session (response picker) ---

@app.get("/session/{session_id}", response_class=HTMLResponse)
async def view_session(request: Request, session_id: int):
    session, responses = storage.get_session_with_responses(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # Load conversation history for context display
    history = [dict(m) for m in storage.get_conversation_messages(session["conversation_id"])]
    return templates.TemplateResponse(request, "session.html", {
        "session": dict(session),
        "responses": [dict(r) for r in responses],
        "history": history,
    })


@app.post("/session/{session_id}/choose")
async def choose_response(
    session_id: int,
    response_index: int = Form(...),
    custom_body: str = Form(""),
    feedback: str = Form(""),
):
    session, responses = storage.get_session_with_responses(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    custom = custom_body.strip()
    if custom:
        matched_index = next(
            (i for i, r in enumerate(responses) if r["body"].strip() == custom), -1
        )
        body = custom
        storage.record_choice(session_id, matched_index, body, feedback)
    elif 0 <= response_index < len(responses):
        body = responses[response_index]["body"]
        storage.record_choice(session_id, response_index, body, feedback)
    else:
        raise HTTPException(status_code=400, detail="No response selected")

    # Save the chosen reply as a message in the conversation
    storage.add_message(
        conversation_id=session["conversation_id"],
        sender_name="Me",
        body=body,
        is_mine=True,
    )

    return RedirectResponse(url=f"/session/{session_id}?chosen=1", status_code=303)


# --- Conversation view ---

@app.get("/conversation/{conv_id}", response_class=HTMLResponse)
async def view_conversation(request: Request, conv_id: int):
    conv = storage.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = [dict(m) for m in storage.get_conversation_messages(conv_id)]
    return templates.TemplateResponse(request, "conversation.html", {
        "conv": dict(conv),
        "messages": messages,
    })


# --- Delete conversation ---

@app.post("/conversation/{conv_id}/delete")
async def delete_conversation(conv_id: int):
    storage.delete_conversation(conv_id)
    return RedirectResponse(url="/", status_code=303)


# --- Instructions ---

@app.get("/instructions", response_class=HTMLResponse)
async def get_instructions(request: Request):
    content = INSTRUCTIONS_PATH.read_text() if INSTRUCTIONS_PATH.exists() else ""
    return templates.TemplateResponse(request, "instructions.html", {
        "content": content,
    })


@app.post("/instructions")
async def save_instructions(content: str = Form(...)):
    INSTRUCTIONS_PATH.parent.mkdir(exist_ok=True)
    INSTRUCTIONS_PATH.write_text(content)
    return RedirectResponse(url="/instructions", status_code=303)
