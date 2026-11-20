"""Everything about site files: names, safe ZIP extraction, serving, starter templates."""
import html
import re
import shutil
import socket
import zipfile
from pathlib import Path

from werkzeug.security import safe_join

RESERVED = {"www", "mail", "admin", "api", "app", "ftp", "smtp", "imap", "pop", "ns1", "ns2", "root", "support", "help",
            "billing", "static", "assets", "cdn", "login", "signup", "dashboard", "status", "blog", "docs", "dev",
            "test", "staging", "internal", "secure", "account", "accounts", "webmail", "localhost"}
ALLOWED_EXT = {"html", "htm", "css", "js", "mjs", "json", "txt", "md", "xml", "svg", "png", "jpg", "jpeg", "gif", "webp",
               "avif", "ico", "woff", "woff2", "ttf", "otf", "eot", "mp4", "webm", "mp3", "ogg", "wav", "pdf", "map",
               "webmanifest", "csv"}
SUB_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])$")
STARTERS = {"coming": "Coming soon page", "portfolio": "Portfolio", "business": "Business", "invite": "Event invitation",
            "linkinbio": "Link in bio"}


class SiteError(Exception):
    pass


def valid_subdomain(name):
    n = (name or "").strip().lower()
    if not SUB_RE.match(n):
        return False, "3 se 30 characters: sirf a-z, 0-9 aur hyphen (shuru/ant mein hyphen nahi)."
    if n.startswith("xn--") or "--" in n:
        return False, "Is naam mein double hyphen ya xn-- allowed nahi."
    if n in RESERVED:
        return False, "Ye naam reserved hai."
    return True, ""


def site_root(cfg, site_id):
    return cfg.data_dir / "sites" / str(site_id)


def public_dir(cfg, site_id):
    return site_root(cfg, site_id) / "public"


def dir_stats(path):
    files = size = 0
    for p in Path(path).rglob("*"):
        if p.is_file():
            files += 1
            size += p.stat().st_size
    return files, size


def extract_zip(stream, dest, max_bytes, max_files):
    """Extracts a ZIP into `dest` safely. Returns (files, bytes, skipped, has_index)."""
    try:
        z = zipfile.ZipFile(stream)
    except zipfile.BadZipFile:
        raise SiteError("Ye valid ZIP file nahi hai.")
    infos = [i for i in z.infolist() if not i.is_dir()]
    if not infos:
        raise SiteError("ZIP khali hai.")
    if len(infos) > max_files:
        raise SiteError(f"ZIP mein {max_files} se zyada files hain.")
    if sum(i.file_size for i in infos) > max_bytes:
        raise SiteError(f"Site {max_bytes // 1048576} MB se badi hai.")

    entries = []
    for i in infos:
        name = i.filename.replace("\\", "/")
        if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
            raise SiteError("ZIP mein unsafe path mila.")
        parts = [p for p in name.split("/") if p not in ("", ".")]
        if ".." in parts:
            raise SiteError("ZIP mein unsafe path mila.")
        entries.append((i, parts))
    if all(len(p) > 1 for _, p in entries) and len({p[0] for _, p in entries}) == 1:
        entries = [(i, p[1:]) for i, p in entries]      # zipped a folder: drop the wrapper folder

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    skipped, files, total = [], 0, 0
    for info, parts in entries:
        label = "/".join(parts)
        if any(p.startswith(".") or p == "__MACOSX" for p in parts):
            continue
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            skipped.append(label)
            continue
        ext = parts[-1].rsplit(".", 1)[-1].lower() if "." in parts[-1] else ""
        if ext not in ALLOWED_EXT:
            skipped.append(label)
            continue
        target = (root.joinpath(*parts)).resolve()
        if root not in target.parents:
            raise SiteError("ZIP mein unsafe path mila.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src, open(target, "wb") as out:
            while True:
                chunk = src.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise SiteError(f"Site {max_bytes // 1048576} MB se badi hai.")
                out.write(chunk)
        files += 1
    if files == 0:
        raise SiteError("ZIP mein koi allowed file nahi mili (html, css, js, images, fonts...).")
    return files, total, skipped, (root / "index.html").is_file()


def replace_public(new_dir, public):
    """Swap the live folder for the new one (old one is removed afterwards)."""
    public = Path(public)
    old = public.with_name("public.old")
    shutil.rmtree(old, ignore_errors=True)
    if public.exists():
        public.rename(old)
    Path(new_dir).rename(public)
    shutil.rmtree(old, ignore_errors=True)


def resolve_file(public, rel):
    """Map a URL path to a file inside `public` (clean URLs supported). Returns Path or None."""
    rel = (rel or "").lstrip("/")
    base = str(public)
    full = safe_join(base, rel) if rel else base
    if full is None:
        return None
    p = Path(full)
    if any(part.startswith(".") for part in Path(rel).parts):
        return None
    if p.is_dir():
        p = p / "index.html"
    elif not p.exists() and "." not in p.name:
        for cand in (p.with_name(p.name + ".html"), p / "index.html"):
            if cand.is_file():
                p = cand
                break
    return p if p.is_file() else None


def render_starter(name, fields):
    if name not in STARTERS:
        name = "coming"
    tpl = (Path(__file__).parent / "starters" / f"{name}.html").read_text(encoding="utf-8")
    for k, v in fields.items():
        tpl = tpl.replace(f"[[{k}]]", html.escape(str(v), quote=True))
    initial = (fields.get("title") or "N")[:1].upper()
    return tpl.replace("[[initial]]", html.escape(initial))


def dns_ips(host):
    """IPv4 addresses a hostname resolves to (follows CNAMEs). Empty set if it does not resolve."""
    try:
        return {r[4][0] for r in socket.getaddrinfo(host, None, socket.AF_INET)}
    except OSError:
        return set()
