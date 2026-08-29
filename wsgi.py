"""
WSGI / ASGI entrypoint for AIkart-LawAI.
Exports app and mcp from main.py.
"""
from main import app, mcp

if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
