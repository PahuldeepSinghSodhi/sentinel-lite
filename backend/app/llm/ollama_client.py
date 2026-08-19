"""Ollama LLM client -- singleton wrapper for local Ollama API.

This module provides a reusable, singleton Ollama client to communicate
with a local Ollama instance. This replaces the cloud-based Gemini API,
ensuring 100% privacy and zero usage costs.
"""
import requests
import json
from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL

class OllamaClient:
    """Wrapper around the local Ollama REST API for text generation."""
    
    def __init__(self, base_url: str = OLLAMA_BASE_URL, model_name: str = OLLAMA_MODEL):
        """Initialize the Ollama client.
        
        Args:
            base_url: The URL where Ollama is running (default http://localhost:11434).
            model_name: The name of the model to use (default llama3.2).
        """
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        print(f"Ollama client initialized: model={model_name}, url={base_url}")
    
    def generate(self, prompt: str, temperature: float = 0.3, max_output_tokens: int = 1024) -> str:
        """Generate text from a prompt using the local Ollama instance.
        
        Args:
            prompt: The full prompt string.
            temperature: Controls randomness.
            max_output_tokens: Maximum length (Ollama uses num_predict for this).
            
        Returns:
            The generated text string.
            
        Raises:
            RuntimeError: If the API call fails or Ollama is unreachable.
        """
        url = f"{self.base_url}/api/generate"
        
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_output_tokens
            }
        }
        
        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()
            return result.get("response", "")
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Could not connect to Ollama at {self.base_url}. "
                "Is the Ollama app running?"
            )
        except Exception as e:
            raise RuntimeError(f"Ollama API call failed: {e}")

# -- Singleton instance ------------------------------------------------
_client_instance: OllamaClient | None = None

def get_ollama_client() -> OllamaClient:
    """Get the shared Ollama client instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = OllamaClient()
    return _client_instance
