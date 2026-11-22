"""The AI side of Zygote: talking to language models that run on this computer (Ollama), on another computer of the network (the LAN GPU
worker, which speaks the same Ollama API and adds a health report), and later on the cloud (keys, frontier models).

Nothing here draws a window (that is ui_ux\\ai_window.py) and nothing here starts a process: every call is an HTTP request made by Qt's own
network manager (asynchronous, no threads, no timers, no subprocess). The one program that is NOT started by Zygote is Ollama itself."""
