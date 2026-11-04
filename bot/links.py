"""Offline URL completion; outbound URLs and comparison keys are kept separate."""
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

PLATFORMS = {
    "instagram": ("instagram.com", "instagr.am"), "tiktok": ("tiktok.com",),
    "youtube": ("youtube.com", "youtu.be"), "x": ("x.com", "twitter.com"),
    "twitter": ("x.com", "twitter.com"), "twitch": ("twitch.tv",),
    "kick": ("kick.com",), "facebook": ("facebook.com", "fb.watch"),
    "telegram": ("t.me", "telegram.me", "telegram.dog"),
}
EXTRA_HOSTS = {"tiktok": {"vt.tiktok.com", "vm.tiktok.com"},
               "twitch": {"clips.twitch.tv", "player.twitch.tv"},
               "kick": {"player.kick.com"}, "facebook": {"mbasic.facebook.com", "web.facebook.com"}}
PREFIXES = {"instagram": "https://www.instagram.com/", "tiktok": "https://www.tiktok.com/@",
            "youtube": "https://www.youtube.com/@", "x": "https://x.com/",
            "twitch": "https://www.twitch.tv/", "kick": "https://kick.com/",
            "facebook": "https://www.facebook.com/", "telegram": "https://t.me/"}
RESERVED = {"accounts", "login", "signup", "explore", "explore.php", "about", "privacy",
            "terms", "settings", "search", "share", "intent", "home", "help"}
HANDLES = {"instagram": r"[A-Za-z0-9_][A-Za-z0-9._]{0,29}",
           "tiktok": r"[A-Za-z0-9_][A-Za-z0-9._]{0,23}", "youtube": r"[\w.-]{1,100}",
           "x": r"[A-Za-z0-9_]{1,15}", "twitch": r"[A-Za-z0-9_]{1,25}",
           "kick": r"[A-Za-z0-9_]{1,100}", "facebook": r"[A-Za-z0-9_.-]{1,100}",
           "telegram": r"[A-Za-z][A-Za-z0-9_]{0,63}"}
IDS = r"[A-Za-z0-9_-]+"


def platform_name(platform):
    value = str(platform or "").lower()
    return "x" if value == "twitter" else value


def _base(host):
    return host.removeprefix("www.").removeprefix("m.").removeprefix("mobile.")


def host_platform(host):
    base = _base(host)
    for platform, domains in PLATFORMS.items():
        if base in domains or host in EXTRA_HOSTS.get(platform, ()):
            return platform_name(platform)
    if host.endswith(".t.me") and re.fullmatch(HANDLES["telegram"], host[:-5]):
        return "telegram"
    return ""


def _partial(value, platform):
    """Only recognizable public URL paths; never infer a missing content ID."""
    relative = urlsplit(value.lstrip("/"))
    if relative.scheme or relative.netloc:
        return ""
    path = relative.path
    patterns = {
        "instagram": rf"(?:reel|p|tv)/{IDS}/?",
        "tiktok": r"@[A-Za-z0-9_.]+/(?:video|photo)/[0-9]+/?",
        "youtube": rf"(?:(?:shorts|embed|live|channel|c|user)/{IDS}/?|watch)",
        "x": r"(?:[A-Za-z0-9_]+|i/web)/status/[0-9]+(?:/video/[0-9]+)?/?",
        "twitch": rf"(?:videos/[0-9]+|[A-Za-z0-9_]+/clip/{IDS})/?",
        "kick": rf"[A-Za-z0-9_]+/videos/{IDS}/?",
        "facebook": rf"(?:(?:watch|profile\.php|story\.php|photo\.php|video\.php)/?|(?:reel|reels|videos)/{IDS}/?|[A-Za-z0-9_.]+/(?:posts|videos)/{IDS}/?)",
        "telegram": rf"(?:\+{IDS}|joinchat/{IDS}|(?:[A-Za-z0-9_]+|c/[0-9]+)/(?:[0-9]+/)*[0-9]+)/?",
    }
    if re.fullmatch(patterns.get(platform, r"(?!)"), path):
        prefix = PREFIXES[platform].removesuffix("@")
        return prefix + value.lstrip("/")
    return ""


def normalize_panel_link(link, platform=""):
    value = str(link or "").strip()
    platform = platform_name(platform)
    if not value or re.search(r"[\s\\\x00-\x1f]", value):
        return ""
    if platform in PREFIXES and "://" not in value:
        completed = _partial(value, platform)
        if completed:
            return completed
        handle = value.removeprefix("@").rstrip("/")
        looks_like_domain = re.search(r"\.(com|net|org|co|io|tv|me|am|dog)$", handle, re.I)
        if (re.fullmatch(HANDLES[platform], handle) and (value.startswith("@") or not looks_like_domain)
                and (value.startswith("@") or handle.lower() not in RESERVED | {"watch", "shorts", "videos", "channel", "reel", "reels", "joinchat"})):
            return PREFIXES[platform] + handle
    if "://" not in value:
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or parsed.username or parsed.password or parsed.port:
            return ""
        host = (parsed.hostname or "").lower()
        actual = host_platform(host)
        if not actual or platform in PREFIXES and actual != platform:
            return ""
        if "%" in unquote(parsed.path):
            return ""  # Ambiguous repeated encoding cannot create distinct target locks.
        # Instagram's www format is explicitly required. Other complete URLs
        # retain their official host, path, case, trailing slash, query and fragment.
        outbound_host = "www.instagram.com" if actual == "instagram" else parsed.netloc
        return urlunsplit(("https", outbound_host, parsed.path, parsed.query, parsed.fragment))
    except ValueError:
        return ""


def _one(query, key):
    values = {value for name, value in query if name == key}
    return next(iter(values)) if len(values) == 1 else ""


def _kind(platform, host, path, query):
    segments = path.split("/") if path else []
    if platform == "twitch" and host == "player.twitch.tv":
        if any(k == "video" for k, _ in query) and any(k == "channel" for k, _ in query):
            return ""
        return "content" if re.fullmatch(r"v?[0-9]+", _one(query, "video")) else "profile" if re.fullmatch(HANDLES["twitch"], _one(query, "channel")) else ""
    if platform == "twitch" and host == "clips.twitch.tv":
        clip = _one(query, "clip") if path == "embed" else path
        return "content" if re.fullmatch(IDS, clip) else ""
    if not segments or segments[0].lower() in RESERVED:
        return ""
    if platform == "instagram":
        if len(segments) == 1 and path.lower() not in {"p", "reel", "reels", "tv", "stories", "direct"} and re.fullmatch(HANDLES[platform], path) and not path.endswith(".") and ".." not in path:
            return "profile"
        return "content" if re.fullmatch(rf"(?:p|reel|tv)/{IDS}", path) else ""
    if platform == "tiktok":
        if re.fullmatch("@" + HANDLES[platform], path) and not path.endswith(".") and ".." not in path:
            return "profile"
        return "content" if re.fullmatch(r"@[A-Za-z0-9_][A-Za-z0-9._]{0,23}/(?:video|photo)/[0-9]+", path) else ""
    if platform == "youtube":
        if host == "youtu.be":
            return "content" if re.fullmatch(IDS, path) else ""
        if path == "watch":
            return "content" if re.fullmatch(IDS, _one(query, "v")) else ""
        if re.fullmatch(rf"(?:shorts|embed|live)/{IDS}", path):
            return "content"
        return "profile" if re.fullmatch(r"@[\w.-]+|(?:channel|c|user)/[\w.-]+", path) else ""
    if platform == "x":
        if re.fullmatch(r"(?:[A-Za-z0-9_]+|i/web)/status/[0-9]+(?:/video/[0-9]+)?", path):
            return "content"
        return "profile" if re.fullmatch(HANDLES[platform], path) and path.lower() not in {"i", "intent"} else ""
    if platform == "twitch":
        if re.fullmatch(rf"(?:videos/[0-9]+|[A-Za-z0-9_]+/clip/{IDS})", path):
            return "content"
        return "profile" if re.fullmatch(HANDLES[platform], path) and path.lower() not in {"videos", "directory", "downloads"} else ""
    if platform == "kick":
        markers = {"clips", "clip", "videos", "video"}
        if len(segments) > 1 and any(v in markers for v in segments):
            index = next(i for i, v in enumerate(segments) if v in markers)
            return "content" if index + 1 < len(segments) and re.fullmatch(IDS, segments[index + 1]) else ""
        if len(segments) == 1 and re.fullmatch(HANDLES[platform], path):
            if path.lower() in markers:
                return ""
            clips = {v for k, v in query if k in {"clip", "clip_id"}}
            if clips:
                return "content" if len(clips) == 1 and re.fullmatch(IDS, next(iter(clips))) else ""
            return "profile"
        return ""
    if platform == "facebook":
        if host == "fb.watch":
            return "content" if re.fullmatch(IDS, path) else ""
        if path == "profile.php":
            return "profile" if _one(query, "id").isdigit() else ""
        if path in {"watch", "video.php"}:
            return "content" if _one(query, "v").isdigit() else ""
        if path == "story.php":
            return "content" if _one(query, "story_fbid") and _one(query, "id").isdigit() else ""
        if path in {"photo.php", "photo"}:
            return "content" if _one(query, "fbid") else ""
        if re.fullmatch(rf"(?:(?:reel|reels|videos)/{IDS}|[A-Za-z0-9_.]+/(?:posts|videos)/{IDS})", path):
            return "content"
        return "profile" if re.fullmatch(HANDLES[platform], path) and path.lower() not in {"reel", "reels", "videos", "watch"} else ""
    if platform == "telegram":
        if re.fullmatch(rf"(?:\+{IDS}|joinchat/{IDS})", path):
            return "profile"
        if re.fullmatch(r"(?:[A-Za-z0-9_]+|c/[0-9]+|s/[A-Za-z0-9_]+)/(?:[0-9]+/)*[0-9]+", path):
            return "content"
        return "profile" if re.fullmatch(HANDLES[platform], path) and path not in {"c", "s", "joinchat"} else ""
    return ""


def link_issue(link, platform, target_type="auto"):
    value = normalize_panel_link(link, platform)
    if not value:
        return "link_missing"
    parsed = urlsplit(value)
    host = parsed.hostname.lower()
    actual = host_platform(host)
    if host in {"vt.tiktok.com", "vm.tiktok.com"}:
        return "link_short"
    path = unquote(parsed.path).strip("/")
    if re.search(r"[\s\\?#\x00-\x1f]", path):
        return "link_missing"
    if actual == "telegram" and host.endswith(".t.me") and _base(host) != "t.me":
        path = host[:-5] + ("/" + path if path else "")
    if actual == "facebook" and path.startswith("share/"):
        return "link_short"
    kind = _kind(actual, _base(host), path, parse_qsl(parsed.query))
    if not kind:
        return "link_missing"
    return "link_type" if target_type in {"profile", "content"} and target_type != kind else ""


def valid_link(link, platform, target_type="auto"):
    return not link_issue(link, platform, target_type)


def target_key(link, platform=""):
    """Keep persisted key semantics; URL preservation never feeds sharing metadata into a lock."""
    value = normalize_panel_link(link, platform)
    if not value:
        return ""
    parsed = urlsplit(value)
    host = _base(parsed.hostname.lower())
    host = {"instagr.am": "instagram.com", "twitter.com": "x.com", "telegram.me": "t.me", "telegram.dog": "t.me"}.get(host, host)
    host = {"mbasic.facebook.com": "facebook.com", "web.facebook.com": "facebook.com", "player.kick.com": "kick.com"}.get(host, host)
    path = unquote(parsed.path).rstrip("/")
    if host.endswith(".t.me"):
        path, host = "/" + host[:-5] + path, "t.me"
    if host in {"instagram.com", "tiktok.com", "x.com"} and len(path.strip("/").split("/")) == 1:
        path = path.lower()
    query = parse_qsl(parsed.query)
    if host == "player.twitch.tv":
        if not _kind("twitch", host, path.strip("/"), query):
            return ""
        if re.fullmatch(r"v?[0-9]+", _one(query, "video")):
            return "twitch.tv/videos/" + _one(query, "video").removeprefix("v")
        if re.fullmatch(HANDLES["twitch"], _one(query, "channel")):
            return "twitch.tv/" + _one(query, "channel")
    if host == "clips.twitch.tv":
        clip = _one(query, "clip") if path == "/embed" else path.lstrip("/")
        return "clips.twitch.tv/" + clip
    if host == "twitch.tv" and re.fullmatch(rf"/[A-Za-z0-9_]+/clip/{IDS}", path):
        return "clips.twitch.tv/" + path.rsplit("/", 1)[1]
    if parsed.hostname.lower() == "player.kick.com":
        clips = [(k, v) for k, v in query if k in {"clip", "clip_id"}]
        return host + path + ("?" + urlencode(sorted(clips)) if clips else "")
    if host in {"youtu.be", "youtube.com"}:
        video = path.lstrip("/") if host == "youtu.be" else _one(query, "v") if path == "/watch" else ""
        if path.startswith(("/shorts/", "/embed/", "/live/")):
            video = path.split("/")[2]
        if video:
            return "youtube.com/watch?v=" + video
    kept = [(k, v) for k, v in query if not k.lower().startswith(("utm_", "_")) and k.lower() not in {"si", "igsh", "feature"}]
    if host in {"instagram.com", "tiktok.com"}:
        kept = []
    return host + path + ("?" + urlencode(sorted(kept)) if kept else "")


def target_type(part, name=""):
    if part.get("target_type") in {"profile", "content"}:
        return part["target_type"]
    text = (str(name) + " " + part.get("name", "")).lower().replace("ı", "i").replace("ç", "c").replace("ğ", "g").replace("ş", "s").replace("ö", "o").replace("ü", "u").replace("\u0307", "")
    profile = bool(re.search(r"\b(takipci|abone|followers?|subscribers?)\b", text))
    content = bool(re.search(r"\b(begeni|izlenme|likes?|views?|yorum)\b", text))
    return "profile" if profile and not content else "content" if content and not profile else "auto"


def old_target_keys(target):
    keys = set()
    if target.startswith("instagram.com/"):
        keys.add(target.lower())
        keys.add(target.replace("instagram.com/", "instagr.am/", 1).lower())
    if target.startswith("t.me/"):
        keys.add(target.replace("t.me/", "telegram.me/", 1))
        keys.add(target.replace("t.me/", "telegram.dog/", 1))
    keys.discard(target)
    return sorted(keys)


def canonical_target(target):
    return target_key("https://" + target) or target if target else ""


def old_target_patterns(target):
    """Narrow legacy clip lookups; no unbounded idle scanning or key rewrite."""
    if target.startswith("clips.twitch.tv/"):
        clip = target.removeprefix("clips.twitch.tv/")
        if re.fullmatch(IDS, clip):
            escaped = clip.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            return ["twitch.tv/%/clip/" + escaped, "twitch.tv/%/clip/" + escaped + "?%",
                    "clips.twitch.tv/" + escaped + "?%"]
    return []
