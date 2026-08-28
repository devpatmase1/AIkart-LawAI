import os
import traceback
import json

from flask import current_app, jsonify, request
from openai import OpenAI
import ollama

from olaw.utils import list_available_models, get_limiter

API_EXTRACT_SEARCH_STATEMENT_RATE_LIMIT = os.environ["API_EXTRACT_SEARCH_STATEMENT_RATE_LIMIT"]


@current_app.route("/api/extract-search-statement", methods=["POST"])
@get_limiter().limit(API_EXTRACT_SEARCH_STATEMENT_RATE_LIMIT)
def post_extract_search_statement():
    """
    [POST] /api/extract-search-statement

    Uses an LLM to analyze a message and, if a legal question is detected:
    - Indicate what API is best suited for that query
    - Returns a search statement for said API.

    Edit EXTRACT_SEARCH_STATEMENT_PROMPT to alter behavior.

    Accepts JSON body with the following properties:
    - "model": One of the models /api/models lists (required)
    - "message": User prompt (required)
    - "temperature": Defaults to 0.0

    Returns JSON:
    - {"search_target": str, "search_statement": str}
    """
    available_models = list_available_models()
    input = request.get_json()
    model = ""
    message = ""
    temperature = 0.0
    prompt = os.environ["EXTRACT_SEARCH_STATEMENT_PROMPT"]
    output = ""
    timeout = 30

    #
    # Check that "model" was provided and is available
    #
    if "model" not in input:
        return jsonify({"error": "No model provided."}), 400

    if input["model"] not in available_models:
        return jsonify({"error": "Requested model is invalid or not available."}), 400

    model = input["model"]

    #
    # Check that "message" was provided
    #
    if "message" not in input:
        return jsonify({"error": "No message provided."}), 400

    message = str(input["message"]).strip()

    if not message:
        return jsonify({"error": "Message cannot be empty."}), 400

    #
    # Validate "temperature" if provided
    #
    if "temperature" in input:
        try:
            temperature = float(input["temperature"])
            assert temperature >= 0.0
        except Exception:
            return (
                jsonify({"error": "temperature must be a float superior or equal to 0.0."}),
                400,
            )

    #
    # Ask model to filter out and extract search query
    #
    prompt = f"{prompt}\n{message}"

    try:
        # Ollama
        if model.startswith("ollama"):
            ollama_client = ollama.Client(
                host=os.environ["OLLAMA_API_URL"],
                timeout=timeout,
            )

            response = ollama_client.chat(
                model=model.replace("ollama/", ""),
                options={"temperature": temperature},
                format="json",
                messages=[{"role": "user", "content": prompt}],
            )

            output = response["message"]["content"]
        # Gemini API
        elif model.startswith("gemini"):
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY"))
            target_model = model.replace("gemini/", "")
            config = types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json"
            )
            response = client.models.generate_content(
                model=target_model,
                contents=prompt,
                config=config
            )
            output = response.text
        # OpenAI / OpenAI-compatible
        else:
            openai_client = OpenAI()

            response = openai_client.chat.completions.create(
                model=model.replace("openai/", ""),
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                timeout=timeout,
            )

            output = json.loads(response.model_dump_json())["choices"][0]["message"]["content"]

    except Exception:
        current_app.logger.error(traceback.format_exc())
        return jsonify({"error": f"Could not run completion against {model}."}), 500

    #
    # Check output format
    #
    try:
        clean_output = str(output).strip()
        if clean_output.startswith("```"):
            lines = clean_output.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_output = "\n".join(lines).strip()

        parsed_json = json.loads(clean_output)

        target = parsed_json.get("search_target") or parsed_json.get("searchTarget") or parsed_json.get("target")
        statement = parsed_json.get("search_statement") or parsed_json.get("searchStatement") or parsed_json.get("query") or parsed_json.get("statement")

        output = {
            "search_target": target if isinstance(target, str) else None,
            "search_statement": statement if isinstance(statement, str) else None
        }
    except Exception:
        current_app.logger.error(f"Failed to parse LLM output: {output}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({"error": f"{model} returned invalid JSON."}), 500

    return jsonify(output), 200
