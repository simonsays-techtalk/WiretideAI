# AGENTS.md (WiretideAI)

## Agent information
- You are working on an Ubuntu 24.04 server.
- Always read `ARCHITECTURE.md` before making changes.
- Per-directory Markdown guides (Dutch) describe the scope; read them when relevant.

## Your purpose
Codex is the AI pair‑programmer for **Wiretide**, a fully local, security-first controller for OpenWrt devices. Your role is to suggest safe refactors, tests, coding, and documentation improvements **without changing functional behavior or breaking offline guarantees**. Together with the user you will create a safe, stable and usable product.

## Codebase overview
Wiretide provides a local **controller → UI → OpenWrt agent** pipeline, exposed via FastAPI routes and Nginx.

Project directories:
- `/backend`
- `/installer`
- `/UI`
- `/agent`

## Operating guidelines
- Maintain `CHANGELOG.md`.
- Create a `.plan` file when planning to create code for next sessions.
- Document everything well.
- Use consistent versioning for WiretideAI.
- Related docs: `ARCHITECTURE.md`, `agent/WRTAGENT.md`, `backend/BACKEND.md`, `installer/INSTALLER.md`, `UI/UI.md`.
