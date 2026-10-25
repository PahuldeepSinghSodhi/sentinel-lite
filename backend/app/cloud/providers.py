"""Fixed hosted-provider adapters; no caller-supplied URLs or browser-side keys."""
import requests

from app.cloud import db
from app.cloud.auth import current_user
from app.cloud.settings import PROVIDER

MODELS = {
    # Direct ollama.com API names come from GET /api/tags; the -cloud suffix
    # belongs to the local Ollama app/CLI and is not used for this endpoint.
    "ollama_cloud": ("gpt-oss:20b", "gpt-oss:120b"),
    "groq": ("openai/gpt-oss-20b", "openai/gpt-oss-120b"),
    "openai": ("gpt-4.1-mini", "gpt-4.1-nano"),
}
ENDPOINTS = {
    "ollama_cloud": "https://ollama.com/api/generate",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
}


def validate_choice(provider: str, model: str) -> None:
    if provider not in MODELS or model not in MODELS[provider]:
        raise ValueError("Choose a supported provider and model")


class HostedClient:
    def __init__(self, provider: str, model: str, key: str):
        validate_choice(provider, model)
        self.provider, self.model_name, self._key = provider, model, key
        self.timeout = 120

    def generate(self, prompt: str, temperature: float = 0.3, max_output_tokens: int = 1024) -> str:
        return self.generate_with_stats(prompt, temperature, max_output_tokens)["response"]

    def generate_with_stats(self, prompt: str, temperature: float = 0.3,
                            max_output_tokens: int = 1024, json_format: bool = False) -> dict:
        if len(prompt) > 40000:
            raise ValueError("Too much document context for this cloud request")
        max_output_tokens = min(max_output_tokens, 1024)
        if self.provider == "ollama_cloud":
            body = {"model": self.model_name, "prompt": prompt, "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_output_tokens}}
            if json_format:
                body["format"] = "json"
        else:
            body = {"model": self.model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature, "max_completion_tokens": max_output_tokens}
            if json_format:
                body["response_format"] = {"type": "json_object"}
        try:
            response = requests.post(ENDPOINTS[self.provider], json=body,
                                     headers={"Authorization": f"Bearer {self._key}",
                                              "Content-Type": "application/json"}, timeout=self.timeout)
        except requests.RequestException as exc:
            raise RuntimeError("AI provider is unreachable") from exc
        if response.status_code in (401, 403):
            raise RuntimeError("AI provider rejected the saved key")
        if response.status_code == 429:
            raise RuntimeError("AI provider rate limit reached; try again later")
        if not response.ok:
            raise RuntimeError(f"AI provider request failed ({response.status_code})")
        data = response.json()
        if self.provider == "ollama_cloud":
            return {"response": data.get("response", ""),
                    "prompt_eval_count": data.get("prompt_eval_count"),
                    "eval_count": data.get("eval_count"),
                    "total_duration": data.get("total_duration"),
                    "load_duration": data.get("load_duration")}
        choices = data.get("choices") or []
        content = (choices[0].get("message") or {}).get("content", "") if choices else ""
        usage = data.get("usage") or {}
        return {"response": content, "prompt_eval_count": usage.get("prompt_tokens"),
                "eval_count": usage.get("completion_tokens"),
                "total_duration": None, "load_duration": None}


def current_client() -> HostedClient:
    if PROVIDER == "aws":
        from app.cloud.aws_providers import load
        provider, model, key = load()
        return HostedClient(provider, model, key)
    with db.connect() as conn:
        row = conn.execute("""SELECT m.provider, m.model, v.decrypted_secret AS api_key
                              FROM model_settings m JOIN vault.decrypted_secrets v ON v.id = m.vault_id
                              WHERE m.owner_id = %s""", (current_user()["id"],)).fetchone()
    if not row:
        raise RuntimeError("Choose and test an AI provider in Settings first")
    return HostedClient(row["provider"], row["model"], row["api_key"])


def settings() -> dict:
    with db.connect() as conn:
        row = conn.execute("SELECT provider, model FROM model_settings WHERE owner_id = %s",
                           (current_user()["id"],)).fetchone()
        configured = bool(row)
        if not row and PROVIDER == "aws":
            row = conn.execute("SELECT provider,model FROM recovery_model_preferences WHERE owner_id=%s",
                               (current_user()["id"],)).fetchone()
    return {"configured": configured, "provider": row["provider"] if row else None,
            "model": row["model"] if row else None, "choices": MODELS}


def save(provider: str, model: str, key: str) -> dict:
    validate_choice(provider, model)
    if not 8 <= len(key) <= 500 or "\n" in key:
        raise ValueError("Enter a valid provider API key")
    # Test once before persisting. The provider may count or charge for this call.
    probe = HostedClient(provider, model, key)
    probe.timeout = 15
    probe.generate("Reply with OK.", max_output_tokens=8)
    if PROVIDER == "aws":
        from app.cloud.aws_providers import save as save_aws
        save_aws(provider, model, key)
        return settings()
    with db.connect() as conn:
        old = conn.execute("SELECT vault_id FROM model_settings WHERE owner_id = %s FOR UPDATE",
                           (current_user()["id"],)).fetchone()
        if old:
            conn.execute("SELECT vault.update_secret(%s, %s)", (old["vault_id"], key))
            vault_id = old["vault_id"]
        else:
            vault_id = conn.execute("SELECT vault.create_secret(%s) AS id", (key,)).fetchone()["id"]
        conn.execute("""INSERT INTO model_settings (owner_id, provider, model, vault_id)
                        VALUES (%s, %s, %s, %s) ON CONFLICT (owner_id) DO UPDATE SET
                        provider = EXCLUDED.provider, model = EXCLUDED.model,
                        vault_id = EXCLUDED.vault_id, updated_at = now()""",
                     (current_user()["id"], provider, model, vault_id))
    return settings()


def delete() -> None:
    if PROVIDER == "aws":
        from app.cloud.aws_providers import delete as delete_aws
        return delete_aws()
    with db.connect() as conn:
        row = conn.execute("DELETE FROM model_settings WHERE owner_id = %s RETURNING vault_id",
                           (current_user()["id"],)).fetchone()
        if row:
            conn.execute("DELETE FROM vault.secrets WHERE id = %s", (row["vault_id"],))
