const $ = (id) => document.getElementById(id);

const statusEl = $("status");
const editor = $("editor");
const previewCard = $("previewCard");
const linksEl = $("links");

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

function addLinkRow(name = "", url = "") {
  const row = document.createElement("div");
  row.className = "link-row";
  row.innerHTML = `
    <input class="platform-name" type="text" value="${escapeHtml(name)}" placeholder="Spotify">
    <input class="platform-url" type="url" value="${escapeHtml(url)}" placeholder="https://...">
    <button class="remove-link" type="button" title="Remove">×</button>
  `;
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
    release_url: $("finalReleaseUrl").value.trim(),
    links,
  };
}

function renderCaption(data) {
  const displayTitle = data.artist
    ? `${data.artist} – ${data.title || "New Release"}`
    : (data.title || "New Release");

  const headline = data.release_url
    ? `<b><a href="${escapeHtml(data.release_url)}">${escapeHtml(displayTitle)}</a></b>`
    : `<b>${escapeHtml(displayTitle)}</b>`;

  const rows = [headline];
  if (data.year) rows.push(escapeHtml(data.year));
  rows.push("", "Listen / Buy 👇");

  const seen = new Set();
  data.links.forEach(({ name, url }) => {
    const key = name.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      rows.push(`<a href="${escapeHtml(url)}">${escapeHtml(name)}</a>`);
    }
  });
  return rows.join("\n");
}

function refreshPreview() {
  const data = collectData();
  $("telegramPreview").innerHTML = renderCaption(data);
  previewCard.classList.remove("hidden");

  const cover = $("coverPreview");
  if (data.cover_url) {
    cover.src = data.cover_url;
    cover.classList.remove("hidden");
  } else {
    cover.removeAttribute("src");
    cover.classList.add("hidden");
  }
}

async function generate() {
  const url = $("releaseUrl").value.trim();
  if (!url) {
    setStatus("Paste a Proton release link first.", "error");
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

    const data = result.data;
    $("artist").value = data.artist || "";
    $("title").value = data.title || "";
    $("year").value = data.year || "";
    $("coverUrl").value = data.cover_url || "";
    $("finalReleaseUrl").value = data.release_url || url;

    linksEl.innerHTML = "";
    (data.links || []).forEach((item) => addLinkRow(item.name, item.url));
    if (!(data.links || []).length) addLinkRow();

    editor.classList.remove("hidden");
    refreshPreview();
    setStatus("Ready. Review the information, then publish.", "success");
  } catch (error) {
    editor.classList.remove("hidden");
    $("finalReleaseUrl").value ||= url;
    if (!linksEl.children.length) addLinkRow();
    refreshPreview();
    setStatus(error.message, "error");
  } finally {
    button.disabled = false;
  }
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
$("releaseUrl").addEventListener("keydown", (event) => {
  if (event.key === "Enter") generate();
});
$("addLinkBtn").addEventListener("click", () => addLinkRow());
$("previewBtn").addEventListener("click", refreshPreview);
$("publishBtn").addEventListener("click", publish);
["artist", "title", "year", "coverUrl", "finalReleaseUrl"].forEach((id) =>
  $(id).addEventListener("input", refreshPreview)
);
