import base64
import html
import io
import ipaddress
import json
import os
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request
from PIL import Image, ImageOps, UnidentifiedImageError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

HTTP_TIMEOUT = 18
MAX_PAGE_BYTES = 3_000_000
MAX_SOURCE_IMAGE_BYTES = 8_000_000
TARGET_IMAGE_BYTES = 1_200_000
TARGET_IMAGE_DIMENSION = 1280

DEFAULT_CAPTION_TEMPLATE = """{title}

🔗 Available on

{links}

© {year} Lighthouse Records"""

PLATFORM_NAMES = {
    "spotify": "Spotify",
    "beatport": "Beatport",
    "apple": "Apple Music",
    "music.apple": "Apple Music",
    "itunes": "Apple Music",
    "soundcloud": "SoundCloud",
    "deezer": "Deezer",
    "amazon": "Amazon Music",
    "youtube": "YouTube",
    "tidal": "TIDAL",
    "bandcamp": "Bandcamp",
    "traxsource": "Traxsource",
    "juno": "Juno Download",
    "qobuz": "Qobuz",
    "boomkat": "Boomkat",
}

session = requests.Session()
retry = Retry(
    total=2,
    connect=2,
    read=2,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET", "POST"),
)
session.mount("https://", HTTPAdapter(max_retries=retry))
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})


def is_public_http_url(value: str) -> bool:
    """Allow only public http(s) URLs to reduce SSRF risk."""
    try:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False

        host = parsed.hostname.lower()
        if host == "localhost" or host.endswith(".local"):
            return False

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
            ip = ipaddress.ip_address(info[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                return False
        return True
    except Exception:
        return False


def fetch_limited(url: str, max_bytes: int, expected: str = ""):
    if not is_public_http_url(url):
        raise ValueError("Please enter a valid public http(s) link.")

    response = session.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True, stream=True)
    response.raise_for_status()

    if not is_public_http_url(response.url):
        raise ValueError("The link redirected to an unsupported address.")

    content_type = response.headers.get("content-type", "").lower()
    if expected and expected not in content_type:
        raise ValueError(f"The link did not return {expected} content.")

    chunks = []
    total = 0
    for chunk in response.iter_content(64 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("The downloaded file is too large.")
        chunks.append(chunk)

    return b"".join(chunks), response.url, content_type


def fetch_page(url: str):
    raw, final_url, content_type = fetch_limited(url, MAX_PAGE_BYTES)
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        raise ValueError("This link did not return a web page.")
    return raw.decode("utf-8", errors="replace"), final_url


def first_meta(soup: BeautifulSoup, *selectors: str) -> str:
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag:
            value = tag.get("content") or tag.get("href") or tag.get_text(" ", strip=True)
            if value:
                return value.strip()
    return ""


def clean_title(raw_title: str) -> str:
    raw_title = re.sub(r"\s+", " ", raw_title or "").strip()
    raw_title = re.sub(
        r"\s*[|–—-]\s*(Listen|Stream|Download|Proton|Smart Link).*$",
        "",
        raw_title,
        flags=re.I,
    )
    return raw_title.strip()


def split_artist_title(title: str):
    separators = [" – ", " — ", " - ", " by "]
    for separator in separators:
        if separator in title:
            left, right = title.split(separator, 1)
            if left.strip() and right.strip():
                if separator == " by ":
                    return right.strip(), left.strip()
                return left.strip(), right.strip()
    return "", title.strip()


def platform_name(url: str, text: str = ""):
    haystack = f"{url} {text}".lower()
    for key, display in PLATFORM_NAMES.items():
        if key in haystack:
            return display
    return ""


def add_link(links: dict, url: str, text: str = "", base_url: str = ""):
    if not url:
        return
    absolute = urljoin(base_url, html.unescape(url.strip()))
    if not absolute.startswith(("http://", "https://")):
        return
    name = platform_name(absolute, text)
    if name and name not in links:
        links[name] = absolute


def parse_release(page_html: str, source_url: str):
    soup = BeautifulSoup(page_html, "html.parser")

    raw_title = first_meta(
        soup,
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
    )
    if not raw_title and soup.title:
        raw_title = soup.title.get_text(" ", strip=True)
    title_line = clean_title(raw_title)
    artist, title = split_artist_title(title_line)

    description = first_meta(
        soup,
        'meta[property="og:description"]',
        'meta[name="description"]',
    )

    image = first_meta(
        soup,
        'meta[property="og:image"]',
        'meta[name="twitter:image"]',
        'link[rel="image_src"]',
    )
    image = urljoin(source_url, image) if image else ""

    year = ""
    combined_text = f"{title_line} {description} {soup.get_text(' ', strip=True)[:12000]}"
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", combined_text)
    plausible = [y for y in years if 1950 <= int(y) <= 2100]
    if plausible:
        year = plausible[0]

    links = {}
    for anchor in soup.find_all("a", href=True):
        add_link(
            links,
            anchor.get("href", ""),
            anchor.get_text(" ", strip=True),
            source_url,
        )

    script_text = "\n".join(
        script.get_text(" ", strip=False) for script in soup.find_all("script")
    )
    for candidate in re.findall(r'https?:\\?/\\?/[^\s"\'<>]+', script_text):
        decoded = candidate.replace("\\/", "/").replace("\\u0026", "&")
        decoded = decoded.rstrip("\\,;)}]")
        add_link(links, decoded, "", source_url)

    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.string or "")
            objects = data if isinstance(data, list) else [data]
            for obj in objects:
                if not isinstance(obj, dict):
                    continue
                if not image:
                    candidate_image = obj.get("image")
                    if isinstance(candidate_image, list):
                        candidate_image = candidate_image[0] if candidate_image else ""
                    if isinstance(candidate_image, dict):
                        candidate_image = candidate_image.get("url", "")
                    if candidate_image:
                        image = urljoin(source_url, str(candidate_image))
                if not title:
                    title = str(obj.get("name", "")).strip()
                if not artist:
                    by_artist = obj.get("byArtist") or obj.get("author")
                    if isinstance(by_artist, dict):
                        artist = str(by_artist.get("name", "")).strip()
        except Exception:
            pass

    preferred = [
        "Spotify", "Beatport", "Apple Music", "SoundCloud", "Deezer",
        "Amazon Music", "YouTube", "TIDAL", "Traxsource", "Bandcamp",
        "Juno Download", "Qobuz", "Boomkat",
    ]
    ordered_links = [
        {"name": name, "url": links[name]}
        for name in preferred
        if name in links
    ]
    ordered_links.extend(
        {"name": name, "url": url}
        for name, url in links.items()
        if name not in preferred
    )

    return {
        "artist": artist,
        "title": title or title_line or "New Release",
        "year": year,
        "cover_url": image,
        "release_url": source_url,
        "links": ordered_links,
        "caption_template": DEFAULT_CAPTION_TEMPLATE,
    }


def title_html(data: dict) -> str:
    artist = str(data.get("artist", "")).strip()
    title = str(data.get("title", "")).strip() or "New Release"
    release_url = str(data.get("release_url", "")).strip()
    display_title = f"{artist} – {title}" if artist else title

    escaped_title = html.escape(display_title)
    if release_url and is_public_http_url(release_url):
        return (
            f'<b><a href="{html.escape(release_url, quote=True)}">'
            f"{escaped_title}</a></b>"
        )
    return f"<b>{escaped_title}</b>"


def links_html(data: dict) -> str:
    lines = []
    seen = set()
    for item in data.get("links", []):
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        key = name.casefold()
        if not name or not url or key in seen or not is_public_http_url(url):
            continue
        seen.add(key)
        lines.append(
            f'<a href="{html.escape(url, quote=True)}">{html.escape(name)}</a>'
        )
    return "\n".join(lines)


def telegram_caption(data: dict) -> str:
    template = str(data.get("caption_template", "")).strip() or DEFAULT_CAPTION_TEMPLATE
    values = {
        "{title}": title_html(data),
        "{links}": links_html(data),
        "{artist}": html.escape(str(data.get("artist", "")).strip()),
        "{release}": html.escape(str(data.get("title", "")).strip()),
        "{year}": html.escape(str(data.get("year", "")).strip()),
    }

    token_pattern = re.compile(r"(\{title\}|\{links\}|\{artist\}|\{release\}|\{year\})")
    parts = token_pattern.split(template)
    rendered = "".join(values.get(part, html.escape(part)) for part in parts)
    rendered = re.sub(r"\n{3,}", "\n\n", rendered).strip()
    return rendered


def decode_data_url(value: str) -> bytes:
    match = re.fullmatch(r"data:image/[a-zA-Z0-9.+-]+;base64,(.+)", value, flags=re.S)
    if not match:
        raise ValueError("The uploaded cover image is invalid.")
    try:
        raw = base64.b64decode(match.group(1), validate=True)
    except Exception as exc:
        raise ValueError("The uploaded cover image could not be decoded.") from exc
    if len(raw) > MAX_SOURCE_IMAGE_BYTES:
        raise ValueError("The uploaded cover is too large. Choose an image under 8 MB.")
    return raw


def compress_cover(source_bytes: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(source_bytes)) as opened:
            image = ImageOps.exif_transpose(opened)
            image.thumbnail(
                (TARGET_IMAGE_DIMENSION, TARGET_IMAGE_DIMENSION),
                Image.Resampling.LANCZOS,
            )

            if image.mode in {"RGBA", "LA"} or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            best = None
            working = image
            for dimension in (1280, 1120, 960, 800):
                if max(working.size) > dimension:
                    resized = working.copy()
                    resized.thumbnail((dimension, dimension), Image.Resampling.LANCZOS)
                else:
                    resized = working

                for quality in (88, 84, 80, 76, 72, 68):
                    buffer = io.BytesIO()
                    resized.save(
                        buffer,
                        format="JPEG",
                        quality=quality,
                        optimize=True,
                        progressive=True,
                    )
                    candidate = buffer.getvalue()
                    best = candidate
                    if len(candidate) <= TARGET_IMAGE_BYTES:
                        return candidate
            if best:
                return best
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("The selected file is not a valid image.") from exc
    raise ValueError("The cover image could not be processed.")


def obtain_cover(data: dict):
    uploaded = str(data.get("cover_data_url", "")).strip()
    if uploaded:
        return compress_cover(decode_data_url(uploaded))

    cover_url = str(data.get("cover_url", "")).strip()
    if not cover_url:
        return None
    raw, _, content_type = fetch_limited(cover_url, MAX_SOURCE_IMAGE_BYTES)
    if not content_type.startswith("image/"):
        raise ValueError("The cover URL did not return an image.")
    return compress_cover(raw)


def require_access():
    configured = os.getenv("APP_PASSWORD", "").strip()
    supplied = request.headers.get("X-App-Password", "").strip()
    if configured and supplied != configured:
        return jsonify({"ok": False, "error": "Wrong app password."}), 401
    return None


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({
        "ok": False,
        "error": "The upload is too large. Choose a cover image under 8 MB.",
    }), 413


@app.get("/")
def index():
    return render_template("index.html", default_template=DEFAULT_CAPTION_TEMPLATE)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/generate")
def generate():
    denied = require_access()
    if denied:
        return denied

    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()

    try:
        page_html, final_url = fetch_page(url)
        data = parse_release(page_html, final_url)
        data["caption_html"] = telegram_caption(data)
        return jsonify({"ok": True, "data": data})
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "error": f"Could not open the release page: {exc}",
        }), 400
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Unexpected generation error")
        return jsonify({
            "ok": False,
            "error": "The page could not be parsed. Use Manual mode and enter the details yourself.",
        }), 500


@app.post("/api/publish")
def publish():
    denied = require_access()
    if denied:
        return denied

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return jsonify({
            "ok": False,
            "error": "Telegram is not configured on Render yet.",
        }), 400

    data = request.get_json(silent=True) or {}
    caption = telegram_caption(data)

    try:
        cover_bytes = obtain_cover(data)
        base = f"https://api.telegram.org/bot{token}"

        if cover_bytes:
            result = requests.post(
                f"{base}/sendPhoto",
                data={
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                },
                files={"photo": ("cover.jpg", cover_bytes, "image/jpeg")},
                timeout=HTTP_TIMEOUT,
            )
        else:
            result = requests.post(
                f"{base}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": caption,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "false",
                },
                timeout=HTTP_TIMEOUT,
            )

        response_data = result.json()
        if not result.ok or not response_data.get("ok"):
            description = response_data.get("description", "Telegram rejected the message.")
            return jsonify({"ok": False, "error": description}), 400

        return jsonify({
            "ok": True,
            "message": "Published to Telegram.",
            "cover_processed": bool(cover_bytes),
        })
    except (requests.RequestException, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Unexpected Telegram error")
        return jsonify({"ok": False, "error": "Could not publish to Telegram."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
