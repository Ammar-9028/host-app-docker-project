import os
from pathlib import Path


class Config:
    """All settings come from environment variables (see .env.example)."""

    def __init__(self, env=None):
        e = os.environ if env is None else env
        self.base_domain = e.get("BASE_DOMAIN", "localhost").lower().strip()
        self.scheme = e.get("PUBLIC_SCHEME", "http")
        self.port_suffix = e.get("PUBLIC_PORT", "")          # e.g. ":8000" when running locally
        self.brand = e.get("BRAND", "NestHost")
        self.data_dir = Path(e.get("DATA_DIR", "./data")).resolve()
        self.server_ip = e.get("SERVER_IP", "").strip()      # used to verify custom-domain DNS
        self.admin_email = e.get("ADMIN_EMAIL", "").lower().strip()
        self.max_sites = int(e.get("MAX_SITES_PER_USER", "3"))
        self.max_site_mb = int(e.get("MAX_SITE_MB", "50"))
        self.max_files = int(e.get("MAX_FILES", "1000"))
        self.trust_proxy = e.get("TRUST_PROXY", "0") == "1"
        self.signup_open = e.get("SIGNUP_OPEN", "1") == "1"

    @property
    def secure(self):
        return self.scheme == "https"

    def site_url(self, sub):
        return f"{self.scheme}://{sub}.{self.base_domain}{self.port_suffix}"

    @property
    def home_url(self):
        return f"{self.scheme}://{self.base_domain}{self.port_suffix}"
