import os
import traceback

from flask import current_app, jsonify, request, Response
from openai import OpenAI
import ollama

from olaw.utils import list_available_models, get_limiter
from olaw.search_targets import SEARCH_TARGETS, SearchTarget, CourtListener


API_COMPLETE_RATE_LIMIT = os.environ["API_COMPLETE_RATE_LIMIT"]


@current_app.route("/api/complete", methods=["POST"])
@get_limiter().limit(API_COMPLETE_RATE_LIMIT)
def post_complete():
    """
    [POST] /api/complete

    Accepts JSON body with the following properties:
    - "message": User prompt (required)
    - "model": One of the models /api/models lists (required)
    - "temperature": Defaults to 0.0
    - "search_results": Output from /api/search.
    - "max_tokens": If provided, caps number of tokens that will be generated in response.
    - "history": A list of chat completion objects representing the chat history. Each object must contain "user" and "content".

    Example of a "history" list:
    ```
    [
        {"role": "user", "content": "Foo bar"},
        {"role": "assistant", "content": "Bar baz"}
    ]
    ```

    Streams text completion directly from LLM API provider.
    """
    available_models = list_available_models()

    input = request.get_json()
    model = None
    message = None
    search_results = {}
    temperature = 0.0
    max_tokens = None

    prompt = os.environ["TEXT_COMPLETION_BASE_PROMPT"]  # Contains {history} and {rag}
    rag_prompt = os.environ["TEXT_COMPLETION_RAG_PROMPT"]  # Template for {rag}
    history_prompt = os.environ["TEXT_COMPLETION_HISTORY_PROMPT"]  # Template for {history}

    history = []  # Chat completion objects keeping track of exchanges

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
    # Validate "search_results" if provided
    #
    if "search_results" in input:
        try:
            # Top-level keys must be part of SEARCH_TARGETS
            for top_level_key in input["search_results"].keys():
                assert top_level_key in SEARCH_TARGETS

                # Validate base format for each entry
                for result in input["search_results"][top_level_key]:
                    result_keys = set(result.keys())
                    base_keys = set(SearchTarget.RESULTS_DATA_FORMAT.keys())
                    assert result_keys == base_keys or base_keys.issubset(result_keys)

            search_results = input["search_results"]
        except Exception:
            return (
                jsonify({"error": "search_results must be the output of /api/search."}),
                400,
            )

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
    # Validate "max_tokens" if provided
    #
    if "max_tokens" in input and input["max_tokens"] is not None:
        try:
            max_tokens = int(input["max_tokens"])
            assert max_tokens > 0
        except Exception:
            return (jsonify({"error": "max_tokens must be an int superior to 0."}), 400)

    #
    # Validate "history" if provided
    #
    if "history" in input:
        try:
            for past_message in input["history"]:
                assert past_message["role"]
                assert past_message["content"]
                history.append(past_message)

        except Exception:
            return (
                jsonify({"error": "past_messages must be an array of chat completion objects."}),
                400,
            )

    #
    # Assemble shell prompt
    #
    history_txt = ""
    search_results_txt = ""

    # History
    for past_message in history:
        history_txt += f"{past_message['role']}: {past_message['content']}\n"

    if history_txt:
        history_prompt = history_prompt.replace("{history}", history_txt)
        prompt = prompt.replace("{history}", history_prompt)
    else:
        prompt = prompt.replace("{history}", "")

    #
    # Assemble context
    #
    for search_target in SEARCH_TARGETS:
        if not search_results.get(search_target):
            continue

        for result in search_results[search_target]:
            search_results_txt += result["prompt_text"] + "\n"
            search_results_txt += result["text"]
            search_results_txt += "\n\n"

    if search_results_txt:
        rag_prompt = rag_prompt.replace("{context}", search_results_txt)
        prompt = prompt.replace("{rag}", rag_prompt)
    else:
        prompt = prompt.replace("{rag}", "")

    # Message
    prompt = prompt.replace("{request}", message)
    prompt = prompt.strip()

    #
    # Run completion
    #
    try:
        # Ollama
        if model.startswith("ollama"):

            ollama_client = ollama.Client(host=os.environ["OLLAMA_API_URL"])

            stream = ollama_client.chat(
                model=model.replace("ollama/", ""),
                options={"temperature": temperature},
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )

            def generate_ollama():
                for chunk in stream:
                    yield chunk["message"]["content"] or ""

            return Response(generate_ollama(), mimetype="text/plain")
        # Gemini API
        elif model.startswith("gemini"):
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY"))
            target_model = model.replace("gemini/", "")
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens if max_tokens else None
            )
            try:
                response = client.models.generate_content_stream(
                    model=target_model,
                    contents=prompt,
                    config=config
                )
            except Exception as gemini_err:
                current_app.logger.warning(f"Target model {target_model} failed streaming ({gemini_err}), trying fallback gemini-3.6-flash...")
                response = client.models.generate_content_stream(
                    model="gemini-3.6-flash",
                    contents=prompt,
                    config=config
                )

            def generate_gemini():
                for chunk in response:
                    if chunk.text:
                        yield chunk.text

            return Response(generate_gemini(), mimetype="text/plain")
        # OpenAI / OpenAI-compatible
        else:
            openai_client = OpenAI()

            stream = openai_client.chat.completions.create(
                model=model.replace("openai/", ""),
                temperature=temperature,
                max_tokens=max_tokens if max_tokens else None,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )

            def generate_openai():
                for chunk in stream:
                    yield chunk.choices[0].delta.content or ""

            return Response(generate_openai(), mimetype="text/plain")
    except Exception:
        current_app.logger.error(traceback.format_exc())
        return jsonify({"error": f"Could not run completion against {model}."}), 500
