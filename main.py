"""
Main entry point for AIkart-LawAI.
Exports app and mcp, and supports direct execution via uvicorn.
"""
import os
from wsgi import app, fastapi_app, mcp

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 5000))
    uvicorn.run("wsgi:app", host="0.0.0.0", port=port, reload=True)
