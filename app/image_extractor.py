"""Extract DM text from a screenshot using Claude Code's Read tool."""
import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _claude_bin() -> str:
    found = shutil.which("claude")
    if found:
        return found
    ext_dir = Path.home() / ".vscode-server/extensions"
    for p in sorted(ext_dir.glob("anthropic.claude-code-*/resources/native-binary/claude"), reverse=True):
        if p.exists():
            return str(p)
    raise FileNotFoundError("claude binary not found")

PROMPT = """Use the Read tool to open the image file at: {path}

Extract the LinkedIn DM conversation from the screenshot. Return ONLY a JSON object:
{{
  "sender_name": "the name of the person who sent the message",
  "message_body": "the full text of their message"
}}

If there are multiple messages, extract the most recent inbound one.
No explanation, raw JSON only."""


NAME_PROMPT = """This is a LinkedIn DM that was sent TO the user. Identify the name of the person who sent it.

Look for:
- Self-introductions: "I'm John", "My name is Jane", "This is Alex", "I am Sarah"
- Signatures or sign-offs at the end of the message
- Phrases like "I'm a recruiter at...", "I work at...", "I'm the CEO of..."
- Any name they refer to themselves by

Return ONLY a JSON object: {{"sender_name": "First Last"}}
If the sender's name cannot be determined from the text, return {{"sender_name": ""}}.
No explanation, raw JSON only.

Message:
{message_body}"""


def extract_name_from_text(message_body: str) -> str:
    """Try to extract sender name from message body text. Returns empty string if not found."""
    prompt = NAME_PROMPT.format(message_body=message_body[:1000])
    result = subprocess.run(
        [_claude_bin(), "-p", prompt, "--output-format", "json"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return ""
    try:
        outer = json.loads(result.stdout)
        raw = outer.get("result", result.stdout).strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)
        return data.get("sender_name", "").strip()
    except Exception:
        return ""


def extract_from_screenshot(image_path: str) -> dict:
    """
    Given a path to a screenshot, return {sender_name, message_body}.
    Uses `claude -p` with the Read tool so it can view the image.
    """
    prompt = PROMPT.format(path=image_path)

    result = subprocess.run(
        [_claude_bin(), "-p", prompt, "--allowedTools", "Read", "--output-format", "json"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed: {result.stderr[:300]}")

    outer = json.loads(result.stdout)
    raw = outer.get("result", result.stdout).strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    data = json.loads(raw)
    return {
        "sender_name": data.get("sender_name", "Unknown").strip(),
        "message_body": data.get("message_body", "").strip(),
    }
