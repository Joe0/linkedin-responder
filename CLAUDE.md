# LinkedIn Responder — Claude Code Instructions

## Project Overview
A personal LinkedIn DM assistant that generates 10 AI response variants per message using the Claude Code CLI, lets the user pick one, and learns from feedback over time.

**Stack:** Python 3.12, FastAPI, SQLite, `claude -p` subprocess (Claude Code CLI), Jinja2 templates

## Key Files
- `main.py` — uvicorn entry point
- `app/web.py` — all FastAPI routes
- `app/storage.py` — SQLite schema and queries
- `app/response_generator.py` — calls `claude -p` to generate 10 response options
- `app/image_extractor.py` — calls `claude -p` with Read tool to OCR screenshots
- `instructions/framework.md` — the user-editable response framework (editable via /instructions in the UI)

## Docs Folder — Read This for Context
The `docs/` folder contains the **Executive Compensation Negotiation Playbook** (Jacob Warwick / Lenny's Podcast), which is the source material for the `instructions/framework.md` response framework.

When working on anything related to:
- The response framework (`instructions/framework.md`)
- How Claude should respond to recruiter/vendor/networking DMs
- The tone, style, or strategic approach of generated responses

**Read the relevant docs files first:**

| File | Topic |
|------|-------|
| `docs/01-psychology-and-mindset.md` | Greed fallacy, introvert penalty, 20% baseline rule |
| `docs/02-information-asymmetry.md` | Werewolf dynamic, Aristotelian persuasion framework |
| `docs/03-pre-negotiation-positioning.md` | Phase Zero: narrative control, strategic silence |
| `docs/04-environment-and-timing.md` | Synchronous vs async, spatial psychology |
| `docs/05-interview-as-discovery.md` | SWAT framework, selling the vacation, reciprocity |
| `docs/06-anchoring-and-objections.md` | Anchor deflection, bypassing recruiters, objection scripts |
| `docs/07-deal-architecture.md` | Milestone triggers, severance/OTE, creative perks |
| `docs/08-identity-and-authenticity.md` | False personas, shared identity tribe hack |
| `docs/09-closing-rituals.md` | Coaching ritual, boardroom narrative control |
| `docs/10-scaling-and-synthesis.md` | Full synthesis and optimization toolkit |

## Deployment
The app runs on the K3s homelab at `linkedin.172.19.76.103.sslip.io`.

Manifests are in `k8s/`. The private registry is at `172.19.76.103:30500`.

To redeploy:
```bash
docker build -t 172.19.76.103:30500/linkedin-responder:latest .
docker push 172.19.76.103:30500/linkedin-responder:latest
kubectl rollout restart deployment/linkedin-responder -n linkedin-responder
```

## Secrets
`ANTHROPIC_API_KEY` is stored as a Kubernetes secret (`linkedin-responder-secrets`). See `k8s/secret.yaml.example`.

## Development
```bash
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY
pip install -r requirements.txt
python main.py
```
