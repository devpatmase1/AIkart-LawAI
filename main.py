"""
Main entry point for AIkart-LawAI with FastAPI, MCP, and Flask integration.
All MCP tools and API routes return plain JSON responses (non-streaming).
"""
import os
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from wsgi import app, run_text_completion_sync
from olaw.utils import list_available_models
from olaw.search_targets import route_search, SEARCH_TARGETS

try:
    from fastapi import FastAPI, HTTPException
    from fastapi_mcp import FastApiMCP

    fastapi_app = FastAPI(
        title="AIkart-LawAI MCP Server",
        description="Legal AI Search & Analysis MCP Server for Claude Desktop (Non-streaming JSON responses)",
        version="1.0.0"
    )

    class LegalSearchRequest(BaseModel):
        query: str = Field(..., description="Legal search query, case name, or statute.")
        target: str = Field("courtlistener", description="Target database (courtlistener).")

    class LegalAnalysisRequest(BaseModel):
        message: str = Field(..., description="Legal question or prompt for analysis.")
        model: Optional[str] = Field(None, description="Optional AI model name.")

    @fastapi_app.get("/health", summary="Immediate plain JSON health check")
    def health():
        """Returns plain JSON status immediately without streaming."""
        return {"status": "ok"}

    @fastapi_app.post("/api/mcp/search", summary="Search US court opinions (Plain JSON)", operation_id="search_legal_databases")
    def search_legal_databases(req: LegalSearchRequest):
        """Returns complete CourtListener search results as plain JSON."""
        try:
            results = route_search("courtlistener", req.query)
            return {"courtlistener": results}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @fastapi_app.get("/api/mcp/models", summary="List available AI models", operation_id="list_available_models")
    def get_models():
        """Returns list of models as plain JSON."""
        return {"models": list_available_models()}

    @fastapi_app.post("/api/mcp/analysis", summary="Run legal analysis (Plain JSON)", operation_id="complete_legal_analysis")
    def legal_analysis(req: LegalAnalysisRequest):
        """Returns full legal analysis as a single plain JSON response (no streaming)."""
        try:
            search_res = route_search("courtlistener", req.message)
            answer = run_text_completion_sync(req.message, model=req.model, search_results={"courtlistener": search_res})
            return {"response": answer}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    mcp = FastApiMCP(fastapi_app)
    mcp.mount()

except Exception:
    fastapi_app = None
    mcp = None

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
