"""Offline customer target validation. Never follow links or guess misspelled hosts."""
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

PLATFORMS = {
    "instagram": ("instagram.com", "instagr.am"), "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be"), "x": ("x.com", "twitter.com"),
    "twitter": ("x.com", "twitter.com"), "twitch": ("twitch.tv",),
    "kick": ("kick.com",), "facebook": ("facebook.com", "fb.watch"),
    "telegram": ("t.me", "telegram.me"),
}
RESERVED = {"accounts", "login", "signup", "explore", "explore.php", "about", "privacy",
            "terms", "settings", "search", "share", "intent", "home", "help"}


def normalize_panel_link(link, platform=""):
    value = str(link or "").strip()
    if not value or re.search(r"[\s\\\x00-\x1f]", value):
        return ""
    # A handle is useful only on the two platforms where we know its exact form.
    handle = value.lstrip("@")
    pattern = r"[A-Za-z0-9_][A-Za-z0-9._]{0,29}" if platform == "instagram" else r"[A-Za-z0-9_][A-Za-z0-9._]{0,23}"
    if platform in {"instagram", "tiktok"} and re.fullmatch(pattern, handle) and not re.search(
            r"\.(com|net|org|co|io|tv|me|am)$", handle, re.I):
        prefix = "https://www.instagram.com/" if platform == "instagram" else "https://www.tiktok.com/@"
        return prefix + handle
    if "://" not in value:
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or parsed.username or parsed.password or parsed.port:
            return ""
        host = (parsed.hostname or "").lower()
        allowed = PLATFORMS.get(platform, tuple(d for domains in PLATFORMS.values() for d in domains))
        if not any(host == d or host in {"www." + d, "m." + d, "mobile." + d} for d in allowed):
            # Only TikTok short links use these subdomains. They remain held below.
            if not (platform in {"tiktok", "other", ""} and host in {"vt.tiktok.com", "vm.tiktok.com"}):
                return ""
        host = {"instagr.am": "instagram.com", "www.instagr.am": "instagram.com",
                "twitter.com": "x.com", "www.twitter.com": "x.com", "tiktok.com": "www.tiktok.com",
                "m.tiktok.com": "www.tiktok.com", "telegram.me": "t.me", "www.telegram.me": "t.me"}.get(host, host)
        path = unquote(parsed.path).rstrip("/")
        query = parsed.query
        if host.removeprefix("www.") in {"instagram.com", "tiktok.com"}:
            query = ""
        return urlunsplit(("https", host, path, "", "")) if not query else urlunsplit(("https", host, path, query, ""))
    except ValueError:
        return ""


def link_issue(link, platform, target_type="auto"):
    value = normalize_panel_link(link, platform)
    if not value:
        return "link_missing"
    parsed = urlsplit(value)
    host = parsed.hostname.removeprefix("www.").removeprefix("m.").removeprefix("mobile.")
    if host in {"vt.tiktok.com", "vm.tiktok.com"}:
        return "link_short"
    path = unquote(parsed.path).strip("/")
    segments = path.split("/") if path else []
    if not segments or segments[0].lower() in RESERVED or re.search(r"[\s\\?#\x00-\x1f]", path):
        return "link_missing"
    if re.search(r"\.(jpg|jpeg|png|gif|webp|svg|ico|avif)$", path, re.I):
        return "link_missing"
    kind = ""
    if host == "instagram.com":
        if len(segments) == 1 and segments[0].lower() not in {"p", "reel", "reels", "tv", "stories", "direct"} and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._]{0,29}", path) and not path.endswith(".") and ".." not in path:
            kind = "profile"
        elif len(segments) == 2 and segments[0].lower() in {"p", "reel", "tv"} and re.fullmatch(r"[A-Za-z0-9_-]+", segments[1]):
            kind = "content"
    elif host == "tiktok.com":
        if re.fullmatch(r"@[A-Za-z0-9_][A-Za-z0-9._]{0,23}", path) and not path.endswith(".") and ".." not in path:
            kind = "profile"
        elif re.fullmatch(r"@[A-Za-z0-9_][A-Za-z0-9._]{0,23}/video/[0-9]+", path):
            kind = "content"
    elif host in {"youtube.com", "youtu.be"}:
        if (host == "youtu.be" and len(segments) == 1 and re.fullmatch(r"[A-Za-z0-9_-]+", path) or
                host == "youtube.com" and (path == "watch" and re.fullmatch(r"[A-Za-z0-9_-]+", dict(parse_qsl(parsed.query)).get("v", "")) or
                len(segments) == 2 and segments[0] in {"shorts", "embed", "live"} and re.fullmatch(r"[A-Za-z0-9_-]+", segments[1]))):
            kind = "content"
        elif host == "youtube.com" and (path.startswith("@") and len(segments) == 1 and len(path) > 1 or
                len(segments) == 2 and segments[0] in {"channel", "c", "user"}):
            kind = "profile"
    else:
        kind = "profile" if len(segments) == 1 else "content"
    if not kind:
        return "link_missing"
    if target_type in {"profile", "content"} and target_type != kind:
        return "link_type"
    return ""


def valid_link(link, platform, target_type="auto"):
    return not link_issue(link, platform, target_type)


def target_key(link, platform=""):
    value = normalize_panel_link(link, platform)
    if not value:
        return ""
    parsed = urlsplit(value)
    host = parsed.hostname.removeprefix("www.").removeprefix("m.").removeprefix("mobile.")
    path = parsed.path.rstrip("/")
    if host in {"instagram.com", "tiktok.com", "x.com"} and len(path.strip("/").split("/")) == 1:
        path = path.lower()
    query = dict(parse_qsl(parsed.query))
    if host in {"youtu.be", "youtube.com"}:
        video = path.lstrip("/") if host == "youtu.be" else query.get("v") if path == "/watch" else ""
        if path.startswith(("/shorts/", "/embed/", "/live/")):
            video = path.split("/")[2]
        if video:
            return "youtube.com/watch?v=" + video
    kept = [(k, v) for k, v in parse_qsl(parsed.query) if not k.lower().startswith(("utm_", "_")) and k.lower() not in {"si", "igsh", "feature"}]
    return host + path + ("?" + urlencode(sorted(kept)) if kept else "")


def target_type(part, name=""):
    if part.get("target_type") in {"profile", "content"}:
        return part["target_type"]
    # Old mappings can also carry an unambiguous product name.
    text = (str(name) + " " + part.get("name", "")).lower().replace("ı", "i").replace("ç", "c").replace("ğ", "g").replace("ş", "s").replace("ö", "o").replace("ü", "u").replace("\u0307", "")
    profile = bool(re.search(r"\b(takipci|abone|followers?|subscribers?)\b", text))
    content = bool(re.search(r"\b(begeni|izlenme|likes?|views?|yorum)\b", text))
    return "profile" if profile and not content else "content" if content and not profile else "auto"


def old_target_keys(target):
    """Indexed compatibility lookups; old persisted locks are never rewritten."""
    keys = set()
    if target.startswith("instagram.com/"):
        keys.add(target.lower())
        keys.add(target.replace("instagram.com/", "instagr.am/", 1).lower())
    if target.startswith("t.me/"):
        keys.add(target.replace("t.me/", "telegram.me/", 1))
    keys.discard(target)
    return sorted(keys)
