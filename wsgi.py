"""
WSGI entrypoint for AIkart-LawAI.
Supports Gunicorn, Render health checks (HEAD/GET /), plain JSON /health endpoint,
APScheduler keep-alive ping job, and non-streaming plain JSON MCP tools for Claude Desktop.
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


# 1. Plain JSON immediate health check (no streaming)
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


def run_text_completion_sync(message: str, model: str = None, search_results: dict = None) -> str:
    """
    Synchronously collects full LLM response text into a single string.
    Never streams or yields, guaranteeing complete plain text for MCP tools.
    """
    available_models = list_available_models()
    if not model or model not in available_models:
        for m in available_models:
            if "gemini" in m or "openai" in m or "ollama" in m:
                model = m
                break
    if not model and available_models:
        model = available_models[0]

    prompt = os.environ.get(
        "TEXT_COMPLETION_BASE_PROMPT",
        "You are an expert legal AI assistant. Provide a comprehensive, accurate legal answer.\n\n{rag}\n\nUser Question: {request}"
    )
    rag_prompt = os.environ.get("TEXT_COMPLETION_RAG_PROMPT", "Context from Legal Precedents:\n{context}")

    search_results_txt = ""
    if search_results and isinstance(search_results, dict):
        for target_key, res_list in search_results.items():
            if isinstance(res_list, list):
                for item in res_list:
                    if isinstance(item, dict):
                        search_results_txt += item.get("prompt_text", "") + "\n"
                        search_results_txt += item.get("text", "") + "\n\n"

    if search_results_txt:
        rag_prompt = rag_prompt.replace("{context}", search_results_txt)
        prompt = prompt.replace("{rag}", rag_prompt)
    else:
        prompt = prompt.replace("{rag}", "")

    prompt = prompt.replace("{history}", "")
    prompt = prompt.replace("{request}", message).strip()

    # Synchronous model execution
    if model and model.startswith("gemini"):
        from google import genai
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY"))
        target_model = model.replace("gemini/", "")
        resp = client.models.generate_content(model=target_model, contents=prompt)
        return resp.text or ""
    elif model and model.startswith("ollama"):
        import ollama
        client = ollama.Client(host=os.environ.get("OLLAMA_API_URL", "http://localhost:11434"))
        resp = client.chat(model=model.replace("ollama/", ""), messages=[{"role": "user", "content": prompt}])
        return resp["message"]["content"] or ""
    else:
        from openai import OpenAI
        client = OpenAI()
        target_model = model.replace("openai/", "") if model else "gpt-4-turbo"
        resp = client.chat.completions.create(model=target_model, messages=[{"role": "user", "content": prompt}])
        return resp.choices[0].message.content or ""


# 3. MCP Server Endpoints (Non-streaming Plain JSON tool responses)
@app.route("/mcp", methods=["GET", "HEAD", "POST"])
def mcp_endpoint():
    """
    MCP Server endpoint for Claude Desktop.
    Supports SSE streaming for endpoint handshake and JSON-RPC on POST.
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
    """Handle incoming JSON-RPC messages from Claude Desktop returning plain JSON."""
    body = request.get_json(silent=True) or {}
    return handle_mcp_rpc(body)


def handle_mcp_rpc(body):
    """
    Process MCP JSON-RPC 2.0 requests returning immediate, complete, non-streaming plain JSON responses.
    """
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
                        "description": "Search US court opinions and legal filings using CourtListener. Returns complete case text, citations, and court details as plain JSON.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "The legal query, case citation, statute, or question to search for."
                                },
                                "target": {
                                    "type": "string",
                                    "description": "Target legal database (default: courtlistener).",
                                    "default": "courtlistener"
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
                    },
                    {
                        "name": "complete_legal_analysis",
                        "description": "Generate a full legal analysis for a query using CourtListener context. Returns complete text as plain JSON (non-streaming).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": "The legal question or analysis prompt."
                                },
                                "model": {
                                    "type": "string",
                                    "description": "Optional model to use (e.g. gemini/gemini-3.6-flash)."
                                }
                            },
                            "required": ["message"]
                        }
                    }
                ]
            }
        })
    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        # Tool 1: Legal Search (Plain JSON response, non-streaming)
        if tool_name == "search_legal_databases":
            query = args.get("query", "")
            target = "courtlistener"
            try:
                res = route_search(target, query)
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"courtlistener": res}, indent=2)}]
                    }
                })
            except Exception as e:
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": str(e)}
                }), 500

        # Tool 2: List Models (Plain JSON response)
        elif tool_name == "list_available_models":
            models = list_available_models()
            return jsonify({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"models": models}, indent=2)}]
                }
            })

        # Tool 3: Complete Legal Analysis (Plain JSON response, non-streaming)
        elif tool_name == "complete_legal_analysis":
            message = args.get("message", "")
            model = args.get("model")
            try:
                # 1. Fetch relevant precedents first
                search_res = route_search("courtlistener", message)
                # 2. Run complete synchronous LLM completion (no streaming)
                completion_text = run_text_completion_sync(message, model=model, search_results={"courtlistener": search_res})
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": completion_text}]
                    }
                })
            except Exception as e:
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": str(e)}
                }), 500

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
