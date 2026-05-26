import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    pass


@dataclass
class Config:
    client_id: str
    client_secret: str
    realm_id: str
    redirect_uri: str
    token_file: str
    environment: str
    anthropic_api_key: str
    confidence_threshold: float

    @property
    def is_sandbox(self) -> bool:
        return self.environment.lower() == "sandbox"

    @property
    def api_base_url(self) -> str:
        host = "sandbox-quickbooks.api.intuit.com" if self.is_sandbox else "quickbooks.api.intuit.com"
        return f"https://{host}/v3/company/{self.realm_id}"


def load_config() -> Config:
    required = {
        "QBO_CLIENT_ID": "client_id",
        "QBO_CLIENT_SECRET": "client_secret",
        "QBO_REALM_ID": "realm_id",
        "ANTHROPIC_API_KEY": "anthropic_api_key",
    }
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")

    raw_threshold = os.getenv("CONFIDENCE_THRESHOLD", "0.90")
    try:
        threshold = float(raw_threshold)
    except ValueError:
        raise ConfigError(f"CONFIDENCE_THRESHOLD must be a float, got: {raw_threshold!r}")

    token_file = os.path.expanduser(os.getenv("QBO_TOKEN_FILE", "~/.qbo_token.json"))

    return Config(
        client_id=os.environ["QBO_CLIENT_ID"],
        client_secret=os.environ["QBO_CLIENT_SECRET"],
        realm_id=os.environ["QBO_REALM_ID"],
        redirect_uri=os.getenv("QBO_REDIRECT_URI", "http://localhost:8080/callback"),
        token_file=token_file,
        environment=os.getenv("QBO_ENVIRONMENT", "production"),
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        confidence_threshold=threshold,
    )
