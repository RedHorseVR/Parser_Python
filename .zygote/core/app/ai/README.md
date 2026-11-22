# app\ai — talking to language models

- `http.py` — one asynchronous HTTP client (Qt network manager: no threads, no timers, no process).
- `ollama.py` — Ollama's API (this computer, or a LAN GPU worker that passes it through), and the pure functions that make the panel's rows.
- `gpu.py` — the NVIDIA cards of this computer through nvidia-ml-py (a library call).
- `download.py` — one file download on Qt's network manager (the Ollama installer).
- `install.py` — Install Ollama (Windows): the one address, and starting the downloaded installer (one process, after a Yes).
- `settings.py` — what the panel remembers per project (`.zygote\user\zygote.json`, key `ai`).

- `panel_logic.py` — the AI panel without a window (standard library only); the layout is data/ai_panel.json, the Qt renderer ui_ux\panel_renderer.py; see app_tree\notes\HANDOFF_ai_panel.md.
- `interface.py` — the three calls for programs of a project (ask, set_model, questions); see app_tree\notes\HANDOFF_ai_interface.md.

The window is `ui_ux\ai_window.py` (File bar > AI). Cloud (frontier) models and keys are not built yet.
