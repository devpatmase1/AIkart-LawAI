"""
WSGI entrypoint for AIkart-LawAI.
Supports Gunicorn, Render health checks (HEAD/GET /), plain JSON /health endpoint,
APScheduler keep-alive ping job, and non-streaming MCP (Model Context Protocol) for Claude Desktop.
"""
import os
import json
import logging
import requests
from flask import request, Response, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

from olaw import create_app
from olaw.utils import list_available_models
from olaw.search_targets import route_search, SEARCH_TARGETS

logger = logging.getLogger(__name__)

# Initialize native Flask application
app = create_app()


# 1. Plain JSON immediate health check
@app.route("/health", methods=["GET", "HEAD"])
def health():
    """Immediate, non-streaming plain JSON health check."""
    return jsonify({"status": "ok"}), 200


@app.route("/mcp/health", methods=["GET", "HEAD"])
def mcp_health():
    """Health check for MCP server."""
    return jsonify({"status": "ok", "service": "AIkart-LawAI MCP Server"}), 200


# 2. APScheduler background ping job to prevent Render free tier sleep
def ping_self_health():
    """Pings the /health endpoint every 10 minutes to keep service alive."""
    url = os.environ.get("SELF_PING_URL", "https://aikart-lawai.onrender.com/health")
    try:
        resp = requests.get(url, timeout=10)
        logger.info(f"Keep-alive self-ping {url} status: {resp.status_code}")
    except Exception as e:
        logger.warning(f"Keep-alive self-ping {url} error: {e}")


scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(ping_self_health, "interval", minutes=10, id="render_keep_alive_ping", replace_existing=True)
try:
    scheduler.start()
    logger.info("APScheduler keep-alive background job started (10 minute interval).")
except Exception as e:
    logger.warning(f"Failed to start APScheduler: {e}")


# 3. MCP Server Endpoints (Non-streaming Plain JSON tool responses)
@app.route("/mcp", methods=["GET", "HEAD", "POST"])
def mcp_endpoint():
    """
    MCP Server endpoint for Claude Desktop.
    Supports SSE streaming for connection handshake and JSON-RPC on POST.
    """
    if request.method == "HEAD":
        return Response("", mimetype="text/event-stream", status=200)
    if request.method == "POST":
        return handle_mcp_rpc(request.get_json(silent=True) or {})

    # SSE Stream for Claude Desktop endpoint discovery
    def event_stream():
        yield "event: endpoint\ndata: /mcp/messages/\n\n"

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.route("/mcp/messages/", methods=["POST"])
@app.route("/mcp/messages", methods=["POST"])
def mcp_messages():
    """Handle incoming JSON-RPC messages from Claude Desktop."""
    body = request.get_json(silent=True) or {}
    return handle_mcp_rpc(body)


def handle_mcp_rpc(body):
    """Process MCP JSON-RPC 2.0 requests returning immediate plain JSON responses."""
    req_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    if method == "initialize":
        return jsonify({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False}
                },
                "serverInfo": {
                    "name": "AIkart-LawAI",
                    "version": "1.0.0"
                }
            }
        })
    elif method in ("notifications/initialized", "initialized"):
        return Response("", status=200)
    elif method == "ping":
        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {}})
    elif method == "tools/list":
        return jsonify({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "search_legal_databases",
                        "description": "Search US court opinions and legal filings using CourtListener. Returns matched cases, citations, snippet text, and court details.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "The legal query, case name, citation, or legal question to search for."
                                },
                                "target": {
                                    "type": "string",
                                    "description": "Target legal database. Options: 'CourtListener_opinion' (court opinions) or 'CourtListener_recap' (court dockets/filings).",
                                    "enum": ["CourtListener_opinion", "CourtListener_recap"],
                                    "default": "CourtListener_opinion"
                                }
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "list_available_models",
                        "description": "List all configured AI models available in LawAI (Gemini, Ollama, OpenAI).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                ]
            }
        })
    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})
        if tool_name == "search_legal_databases":
            query = args.get("query", "")
            target = args.get("target", "CourtListener_opinion")
            target = target if target in SEARCH_TARGETS else "CourtListener_opinion"
            try:
                res = route_search(target, query)
                # Return immediate plain JSON MCP response
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({target: res}, indent=2)}]
                    }
                })
            except Exception as e:
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": str(e)}
                }), 500
        elif tool_name == "list_available_models":
            models = list_available_models()
            return jsonify({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"models": models}, indent=2)}]
                }
            })
        else:
            return jsonify({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}
            }), 404
    else:
        return jsonify({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
