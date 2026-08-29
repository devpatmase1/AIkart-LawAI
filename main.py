"""
Main FastAPI and MCP entrypoint for AIkart-LawAI.
"""
import os
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException
from fastapi_mcp import FastApiMCP
from starlette.middleware.wsgi import WSGIMiddleware

from olaw import create_app
from olaw.utils import list_available_models
from olaw.search_targets import route_search, SEARCH_TARGETS

# Initialize Flask application for web UI and existing routes
flask_app = create_app()

# Initialize FastAPI application
app = FastAPI(
    title="AIkart-LawAI MCP Server",
    description="Legal AI Search and Court Case Retrieval Agent with MCP support for Claude Desktop",
    version="1.0.0",
)


# Pydantic models for MCP tool inputs
class LegalSearchRequest(BaseModel):
    query: str = Field(
        ...,
        description="The legal research query, case name, statute, or legal question to search for."
    )
    target: str = Field(
        "CourtListener_opinion",
        description="Search target database. Options: 'CourtListener_opinion' (court opinions) or 'CourtListener_recap' (court dockets/filings)."
    )


# MCP / FastAPI Endpoints that will be automatically discovered by Claude Desktop
@app.get("/mcp/health", tags=["MCP"], summary="Health check endpoint for MCP server")
def mcp_health():
    """Health check endpoint to verify MCP server status."""
    return {"status": "ok", "service": "AIkart-LawAI MCP Server"}


@app.post(
    "/api/mcp/search",
    tags=["Legal Search"],
    summary="Search US court opinions and legal filings",
    operation_id="search_legal_databases"
)
def search_legal_databases(req: LegalSearchRequest):
    """
    Search legal records (court opinions, precedents, or RECAP dockets) using CourtListener.
    Returns matched cases, citations, snippet text, and court details.
    """
    target = req.target if req.target in SEARCH_TARGETS else "CourtListener_opinion"
    try:
        results = route_search(target, req.query)
        return {target: results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Legal search failed: {str(e)}")


@app.get(
    "/api/mcp/models",
    tags=["Models"],
    summary="List available AI text completion models",
    operation_id="list_available_models"
)
def get_available_models():
    """Returns a list of all configured and available AI models (Gemini, Ollama, OpenAI)."""
    return {"models": list_available_models()}


# Add MCP support to the FastAPI app:
# - Import FastApiMCP from fastapi_mcp
# - Create mcp = FastApiMCP(app) after the app is initialized
# - Call mcp.mount() to expose the /mcp endpoint
mcp = FastApiMCP(app)
mcp.mount()
try:
    mcp.mount_http(mount_path="/mcp/http")
except Exception:
    pass

# Mount existing Flask application under "/" to preserve UI and all existing routes
app.mount("/", WSGIMiddleware(flask_app))

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
