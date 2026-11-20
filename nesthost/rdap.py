"""Is a real domain taken? Uses the public RDAP service (free, no API key)."""
import re
import time
import urllib.error
import urllib.request

FQDN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
_cache = {}


def normalize(domain):
    d = (domain or "").strip().lower().rstrip(".")
    return d if FQDN.match(d) else None


def _fetch(domain):
    req = urllib.request.Request("https://rdap.org/domain/" + domain,
                                 headers={"Accept": "application/rdap+json", "User-Agent": "NestHost/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def status(domain, fetch=None, now=time.time):
    """Returns 'taken', 'available' (likely) or 'unknown'."""
    d = normalize(domain)
    if not d:
        raise ValueError("invalid domain")
    hit = _cache.get(d)
    if hit and hit[0] > now():
        return hit[1]
    code = (fetch or _fetch)(d)
    res = "taken" if code == 200 else "available" if code == 404 else "unknown"
    if res != "unknown":
        _cache[d] = (now() + 600, res)
    return res
