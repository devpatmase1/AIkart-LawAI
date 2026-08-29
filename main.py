"""
Main entry point for AIkart-LawAI.
Exports app and mcp, supporting both Uvicorn and Gunicorn.
"""
import os
from wsgi import app

try:
    from fastapi import FastAPI
    from fastapi_mcp import FastApiMCP

    fastapi_app = FastAPI(title="AIkart-LawAI MCP Server")
    mcp = FastApiMCP(fastapi_app)
    mcp.mount()
except Exception:
    fastapi_app = None
    mcp = None

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
