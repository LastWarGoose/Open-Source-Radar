import re
from urllib.parse import urlsplit


def github_name(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.netloc.lower() != "github.com"
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Only canonical HTTPS GitHub repository URLs are allowed")
    name = parts.path.strip("/")
    if name.endswith(".git"):
        name = name[:-4]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", name):
        raise ValueError("Invalid GitHub repository path")
    if name.split("/")[1] in (".", ".."):
        raise ValueError("Invalid repository name")
    return name.lower()
