import os
import traceback

from flask import current_app
from openai import OpenAI
import ollama


def list_available_models() -> list:
    """
    Returns a list of the models the pipeline can talk to based on current environment.
    """
    models = []

    # Use case: Using OpenAI's client to interact with a non-OpenAI provider.
    # In that case, the model's name is provided via the environment.
    if os.environ.get("OPENAI_BASE_URL") and os.environ.get("OPENAI_COMPATIBLE_MODEL"):
        models.append(os.environ.get("OPENAI_COMPATIBLE_MODEL"))

    # Use case: OpenAI
    if os.environ.get("OPENAI_API_KEY") and not os.environ.get("OPENAI_BASE_URL"):
        try:
            openai_client = OpenAI()

            for model in openai_client.models.list().data:
                if model.id.startswith("gpt-4"):
                    models.append(f"openai/{model.id}")

        except Exception:
            current_app.logger.error("Could not list OpenAI models.")
            current_app.logger.error(traceback.format_exc())

    # Use case: Ollama
    if os.environ.get("OLLAMA_API_URL"):
        try:
            ollama_client = ollama.Client(
                host=os.environ["OLLAMA_API_URL"],
                timeout=5,
            )

            raw_models = ollama_client.list()
            model_list = raw_models.models if hasattr(raw_models, "models") else raw_models.get("models", [])
            for model in model_list:
                name = getattr(model, "model", None) or getattr(model, "name", None)
                if not name and isinstance(model, dict):
                    name = model.get("model") or model.get("name")
                if not name:
                    try:
                        name = model["model"]
                    except Exception:
                        name = model.get("name") if hasattr(model, "get") else None
                if name:
                    models.append(f"ollama/{name}")

        except Exception as e:
            current_app.logger.info(f"Ollama service not active: {e}")

    # Use case: Gemini API
    if os.environ.get("GEMINI_API_KEY"):
        gemini_count_before = len(models)
        try:
            from google import genai
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            for m in client.models.list():
                model_id = getattr(m, "name", "") or getattr(m, "id", "")
                if model_id:
                    clean_name = model_id.replace("models/", "")
                    if clean_name.startswith("gemini-") and "embed" not in clean_name and "bidi" not in clean_name and "imagen" not in clean_name:
                        models.append(f"gemini/{clean_name}")
        except Exception as e:
            try:
                current_app.logger.error(f"Could not list Gemini models dynamically: {e}")
            except Exception:
                pass

        # Fallback if no Gemini model matched the filter
        if len(models) == gemini_count_before:
            models.extend(["gemini/gemini-1.5-flash", "gemini/gemini-2.0-flash", "gemini/gemini-1.5-pro"])

    return models
