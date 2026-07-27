const $ = (id) => document.getElementById(id);

const statusEl = $("status");
const editor = $("editor");
const previewCard = $("previewCard");
const linksEl = $("links");
const DEFAULT_TEMPLATE = window.DEFAULT_CAPTION_TEMPLATE || `{title}\n\n🔗 Available on\n\n{links}\n\n© {year} Lighthouse Records`;

let customCoverDataUrl = "";
let customCoverObjectUrl = "";

function setStatus(message, kind = "") {
  statusEl.textContent = message;
  statusEl.className = `status ${kind}`.trim();
}

function headers() {
  return {
    "Content-Type": "application/json",
    "X-App-Password": $("appPassword").value.trim(),
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function isHttpUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function addLinkRow(name = "", url = "") {
  const row = document.createElement("div");
  row.className = "link-row";
  row.innerHTML = `
    <div class="reorder-buttons">
      <button class="move-up secondary" type="button" title="Move up">↑</button>
      <button class="move-down secondary" type="button" title="Move down">↓</button>
    </div>
    <input class="platform-name" type="text" value="${escapeHtml(name)}" placeholder="Spotify">
    <input class="platform-url" type="url" value="${escapeHtml(url)}" placeholder="https://...">
    <button class="remove-link" type="button" title="Remove">×</button>
  `;

  row.querySelector(".move-up").addEventListener("click", () => {
    const previous = row.previousElementSibling;
    if (previous) linksEl.insertBefore(row, previous);
    refreshPreview();
  });

  row.querySelector(".move-down").addEventListener("click", () => {
    const next = row.nextElementSibling;
    if (next) linksEl.insertBefore(next, row);
    refreshPreview();
  });

  row.querySelector(".remove-link").addEventListener("click", () => {
    row.remove();
    refreshPreview();
  });

  row.querySelectorAll("input").forEach((input) =>
    input.addEventListener("input", refreshPreview)
  );

  linksEl.appendChild(row);
}

function collectData() {
  const links = [...document.querySelectorAll(".link-row")]
    .map((row) => ({
      name: row.querySelector(".platform-name").value.trim(),
      url: row.querySelector(".platform-url").value.trim(),
    }))
    .filter((item) => item.name && item.url);

  return {
    artist: $("artist").value.trim(),
    title: $("title").value.trim(),
    year: $("year").value.trim(),
    cover_url: $("coverUrl").value.trim(),
    cover_data_url: customCoverDataUrl,
    release_url: $("finalReleaseUrl").value.trim(),
    caption_template: $("captionTemplate").value,
    links,
  };
}

function titleHtml(data) {
  const displayTitle = data.artist
    ? `${data.artist} – ${data.title || "New Release"}`
    : (data.title || "New Release");

  return isHttpUrl(data.release_url)
    ? `<b><a href="${escapeHtml(data.release_url)}">${escapeHtml(displayTitle)}</a></b>`
    : `<b>${escapeHtml(displayTitle)}</b>`;
}

function linksHtml(data) {
  const seen = new Set();
  const rows = [];
  data.links.forEach(({ name, url }) => {
    const key = name.toLowerCase();
    if (!seen.has(key) && isHttpUrl(url)) {
      seen.add(key);
      rows.push(`<a href="${escapeHtml(url)}">${escapeHtml(name)}</a>`);
    }
  });
  return rows.join("\n");
}

function renderCaption(data) {
  const values = {
    "{title}": titleHtml(data),
    "{links}": linksHtml(data),
    "{artist}": escapeHtml(data.artist),
    "{release}": escapeHtml(data.title),
    "{year}": escapeHtml(data.year),
  };

  const pieces = String(data.caption_template || DEFAULT_TEMPLATE)
    .split(/(\{title\}|\{links\}|\{artist\}|\{release\}|\{year\})/g);

  return pieces
    .map((piece) => Object.prototype.hasOwnProperty.call(values, piece)
      ? values[piece]
      : escapeHtml(piece))
    .join("")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function updateCoverPreview() {
  const cover = $("coverPreview");
  const placeholder = $("coverPlaceholder");
  const remoteUrl = $("coverUrl").value.trim();
  const source = customCoverObjectUrl || remoteUrl;

  if (source) {
    cover.src = source;
    cover.classList.remove("hidden");
    placeholder.classList.add("hidden");
  } else {
    cover.removeAttribute("src");
    cover.classList.add("hidden");
    placeholder.classList.remove("hidden");
  }
}

function refreshPreview() {
  const data = collectData();
  $("telegramPreview").innerHTML = renderCaption(data);
  previewCard.classList.remove("hidden");
  updateCoverPreview();
}

function openManualMode() {
  editor.classList.remove("hidden");
  if (!linksEl.children.length) addLinkRow();
  if (!$("captionTemplate").value.trim()) $("captionTemplate").value = DEFAULT_TEMPLATE;
  setStatus("Manual mode is ready. Add your details, links, and cover.", "success");
  refreshPreview();
}

function resetEditorForGeneratedData(data, fallbackUrl) {
  $("artist").value = data.artist || "";
  $("title").value = data.title || "";
  $("year").value = data.year || "";
  $("coverUrl").value = data.cover_url || "";
  $("finalReleaseUrl").value = data.release_url || fallbackUrl || "";
  $("captionTemplate").value = data.caption_template || DEFAULT_TEMPLATE;

  customCoverDataUrl = "";
  if (customCoverObjectUrl) URL.revokeObjectURL(customCoverObjectUrl);
  customCoverObjectUrl = "";
  $("coverFile").value = "";
  $("removeUploadBtn").classList.add("hidden");
  $("coverInfo").textContent = "Images are resized and compressed before publishing.";

  linksEl.innerHTML = "";
  (data.links || []).forEach((item) => addLinkRow(item.name, item.url));
  if (!(data.links || []).length) addLinkRow();
}

async function generate() {
  const url = $("releaseUrl").value.trim();
  if (!url) {
    setStatus("Paste a smart link, or choose Start manually.", "error");
    return;
  }

  const button = $("generateBtn");
  button.disabled = true;
  setStatus("Reading the release page…");

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ url }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || "Could not generate.");

    resetEditorForGeneratedData(result.data, url);
    editor.classList.remove("hidden");
    refreshPreview();
    setStatus("Ready. Everything below can be edited before publishing.", "success");
  } catch (error) {
    openManualMode();
    $("finalReleaseUrl").value ||= url;
    setStatus(`${error.message} Manual mode is open below.`, "error");
  } finally {
    button.disabled = false;
  }
}

function readCoverFile(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    setStatus("Choose a JPG, PNG, or WebP image.", "error");
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    setStatus("The cover is over 8 MB. Choose a smaller image.", "error");
    $("coverFile").value = "";
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    customCoverDataUrl = String(reader.result || "");
    if (customCoverObjectUrl) URL.revokeObjectURL(customCoverObjectUrl);
    customCoverObjectUrl = URL.createObjectURL(file);
    $("removeUploadBtn").classList.remove("hidden");
    const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
    $("coverInfo").textContent = `${file.name} · ${sizeMb} MB · will be compressed to a Telegram-friendly JPEG.`;
    refreshPreview();
    setStatus("Custom cover selected. It will override the Cover URL.", "success");
  };
  reader.onerror = () => setStatus("Could not read that image.", "error");
  reader.readAsDataURL(file);
}

function removeUploadedCover() {
  customCoverDataUrl = "";
  if (customCoverObjectUrl) URL.revokeObjectURL(customCoverObjectUrl);
  customCoverObjectUrl = "";
  $("coverFile").value = "";
  $("removeUploadBtn").classList.add("hidden");
  $("coverInfo").textContent = "Images are resized and compressed before publishing.";
  refreshPreview();
}

async function publish() {
  const button = $("publishBtn");
  button.disabled = true;
  setStatus("Publishing to Telegram…");

  try {
    const response = await fetch("/api/publish", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify(collectData()),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || "Publish failed.");
    setStatus("Published successfully to Telegram.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

$("generateBtn").addEventListener("click", generate);
$("manualBtn").addEventListener("click", openManualMode);
$("releaseUrl").addEventListener("keydown", (event) => {
  if (event.key === "Enter") generate();
});
$("addLinkBtn").addEventListener("click", () => {
  addLinkRow();
  refreshPreview();
});
$("resetTemplateBtn").addEventListener("click", () => {
  $("captionTemplate").value = DEFAULT_TEMPLATE;
  refreshPreview();
});
$("coverFile").addEventListener("change", (event) => readCoverFile(event.target.files[0]));
$("removeUploadBtn").addEventListener("click", removeUploadedCover);
$("previewBtn").addEventListener("click", refreshPreview);
$("publishBtn").addEventListener("click", publish);
["artist", "title", "year", "coverUrl", "finalReleaseUrl", "captionTemplate"].forEach((id) =>
  $(id).addEventListener("input", refreshPreview)
);
