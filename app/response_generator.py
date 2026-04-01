"""Generate response options using Claude Code CLI (claude -p)."""
import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

INSTRUCTIONS_PATH = Path(__file__).parent.parent / "instructions" / "framework.md"

_FALLBACK_CLAUDE_PATHS = [
    Path.home() / ".local/bin/claude",
    Path.home() / ".vscode-server/extensions",  # searched below
]

def _claude_bin() -> str:
    found = shutil.which("claude")
    if found:
        return found
    # Walk VSCode extension dirs for the native binary
    ext_dir = Path.home() / ".vscode-server/extensions"
    for p in sorted(ext_dir.glob("anthropic.claude-code-*/resources/native-binary/claude"), reverse=True):
        if p.exists():
            return str(p)
    raise FileNotFoundError("claude binary not found — run: ln -s <path/to/claude> ~/.local/bin/claude")

TONE_LABELS = [
    "Short & direct",
    "Warm & personal",
    "Formal & professional",
    "Curious / asks a question",
    "Enthusiastic",
    "Polite decline",
    "Defer / not the right time",
    "Playful / light",
    "Detailed & thorough",
    "Open-ended / minimal commitment",
]


def load_framework() -> str:
    if INSTRUCTIONS_PATH.exists():
        return INSTRUCTIONS_PATH.read_text()
    return "Be professional, concise, and genuine."


def generate_responses(
    message_body: str,
    sender_name: str,
    conversation_history: list[dict] | None = None,
    feedback_history: list[dict] | None = None,
) -> tuple[list[dict], str]:
    """
    Generate 10 response options using Claude Code CLI.
    Also extracts sender name from the message when sender_name is "Unknown".
    Returns (responses, resolved_sender_name).
    """
    framework = load_framework()
    extract_name = sender_name == "Unknown"

    feedback_context = ""
    if feedback_history:
        lines = []
        for ex in feedback_history[:5]:
            if ex.get("chosen_body"):
                lines.append(f"- Chose: \"{ex['chosen_body'][:120]}\"")
                if ex.get("feedback"):
                    lines.append(f"  Feedback: {ex['feedback']}")
        if lines:
            feedback_context = "\n\nPast choices (learn from these):\n" + "\n".join(lines)

    history_context = ""
    if conversation_history:
        lines = [
            f"{'Me' if m['is_mine'] else m['sender_name']}: {m['body']}"
            for m in conversation_history[-8:]
        ]
        history_context = "\n\nConversation so far:\n" + "\n".join(lines)

    tones_list = "\n".join(f"{i+1}. {t}" for i, t in enumerate(TONE_LABELS))

    name_instruction = ""
    name_format = ""
    if extract_name:
        name_instruction = """
First, extract the sender's name from the message. Look for:
- Signatures or sign-offs ("Best, Dan", "Thanks, Sarah")
- Self-introductions ("I'm John", "My name is Jane", "This is Alex")
- Name + title lines at the end (e.g. "Daniel Mapstone\\nVice President")
If you cannot determine the name, use "Unknown".
"""
        name_format = '"sender_name": "First Last",\n  '

    prompt = f"""You are helping draft LinkedIn DM replies. Here is the user's response framework:

<framework>
{framework}
</framework>
{feedback_context}
{history_context}

New inbound message from {sender_name}:
<message>
{message_body}
</message>
{name_instruction}
Generate exactly 10 response options. Each should be meaningfully different.
Use these tone targets (one per response, in order):
{tones_list}

Return ONLY a JSON object with exactly this structure — no markdown, no explanation:
{{
  {name_format}"responses": [
    {{"body": "Thanks for reaching out...", "tone": "Short & direct"}},
    ...
  ]
}}"""

    result = subprocess.run(
        [_claude_bin(), "-p", prompt, "--output-format", "json"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed (exit {result.returncode}): {result.stderr[:500]}")

    outer = json.loads(result.stdout)
    raw = outer.get("result", result.stdout).strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    data = json.loads(raw)

    # Support both old array format and new object format
    if isinstance(data, list):
        responses = data
        resolved_name = sender_name
    else:
        responses = data.get("responses", [])
        resolved_name = data.get("sender_name", sender_name) or sender_name
        if resolved_name == "Unknown" and sender_name != "Unknown":
            resolved_name = sender_name

    if not isinstance(responses, list):
        raise ValueError("Expected a JSON array of responses from Claude Code")

    return responses[:10], resolved_name
