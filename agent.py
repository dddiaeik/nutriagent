"""Ollama connection settings for NutriAgent."""

import ollama

MODEL_NAME = "qwen3:8b"


def is_model_available() -> bool:
    """Check whether the configured Ollama server has the model installed."""
    return any(model.model == MODEL_NAME for model in ollama.list().models)
