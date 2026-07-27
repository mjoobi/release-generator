import html
import ipaddress
import json
import os
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

HTTP_TIMEOUT = 18
MAX_PAGE_BYTES = 3_000_000
MAX_IMAGE_BYTES = 10_000_000

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
        if host in {"localhost"} or host.endswith(".local"):
            return False

        for info in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM):
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


def fetch_page(url: str):
    if not is_public_http_url(url):
        raise ValueError("Please enter a valid public http(s) link.")

    response = session.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True, stream=True)
    response.raise_for_status()

    if not is_public_http_url(response.url):
        raise ValueError("The link redirected to an unsupported address.")

    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        raise ValueError("This link did not return a web page.")

    chunks = []
    total = 0
    for chunk in response.iter_content(64 * 1024):
        total += len(chunk)
        if total > MAX_PAGE_BYTES:
            raise ValueError("The page is too large to process.")
        chunks.append(chunk)

    encoding = response.encoding or "utf-8"
    return b"".join(chunks).decode(encoding, errors="replace"), response.url


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
    if years:
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

    # Many smart-link pages place destinations inside JSON/script data.
    script_text = "\n".join(
        script.get_text(" ", strip=False) for script in soup.find_all("script")
    )
    for candidate in re.findall(r'https?:\\?/\\?/[^\s"\'<>]+', script_text):
        decoded = candidate.replace("\\/", "/").replace("\\u0026", "&")
        decoded = decoded.rstrip("\\,;)}]")
        add_link(links, decoded, "", source_url)

    # JSON-LD sometimes has cleaner metadata.
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

    # Stable, familiar ordering.
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
    }


def telegram_caption(data: dict) -> str:
    artist = str(data.get("artist", "")).strip()
    title = str(data.get("title", "")).strip() or "New Release"
    year = str(data.get("year", "")).strip()
    release_url = str(data.get("release_url", "")).strip()

    display_title = f"{artist} – {title}" if artist else title

    if release_url:
        headline = (
            f'<b><a href="{html.escape(release_url, quote=True)}">'
            f'{html.escape(display_title)}</a></b>'
        )
    else:
        headline = f"<b>{html.escape(display_title)}</b>"

    lines = [
        headline,
        "",
        "🔗 <b>Available on</b>",
        "",
    ]

    seen = set()

    for item in data.get("links", []):
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()

        if not name or not url or name.lower() in seen:
            continue

        seen.add(name.lower())

        lines.append(
            f'<a href="{html.escape(url, quote=True)}">'
            f'{html.escape(name)}</a>'
        )

    copyright_text = (
        f"© {html.escape(year)} Lighthouse Records"
        if year
        else "© Lighthouse Records"
    )

    lines.extend([
        "",
        f"<i>{copyright_text}</i>",
    ])

    return "\n".join(lines)


def require_access():
    configured = os.getenv("APP_PASSWORD", "").strip()
    supplied = request.headers.get("X-App-Password", "").strip()
    if configured and supplied != configured:
        return jsonify({"ok": False, "error": "Wrong app password."}), 401
    return None


@app.get("/")
def index():
    return render_template("index.html")


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
            "error": "The page could not be parsed. You can still fill the fields manually.",
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
    cover_url = str(data.get("cover_url", "")).strip()

    try:
        base = f"https://api.telegram.org/bot{token}"
        if cover_url and is_public_http_url(cover_url):
            image_response = session.get(
                cover_url, timeout=HTTP_TIMEOUT, allow_redirects=True, stream=True
            )
            image_response.raise_for_status()
            image_bytes = image_response.content
            if len(image_bytes) > MAX_IMAGE_BYTES:
                raise ValueError("The cover image is too large.")

            result = requests.post(
                f"{base}/sendPhoto",
                data={
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                },
                files={
                    "photo": (
                        "cover.jpg",
                        image_bytes,
                        image_response.headers.get("content-type", "image/jpeg"),
                    )
                },
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

        return jsonify({"ok": True, "message": "Published to Telegram."})
    except (requests.RequestException, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Unexpected Telegram error")
        return jsonify({"ok": False, "error": "Could not publish to Telegram."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
