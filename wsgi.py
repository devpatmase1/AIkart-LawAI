"""
WSGI / ASGI entrypoint for AIkart-LawAI.
Exports app, fastapi_app, and mcp from main.py.
"""
from main import app, fastapi_app, mcp

if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
