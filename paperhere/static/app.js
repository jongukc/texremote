import { getDocument, GlobalWorkerOptions } from "/static/vendor/pdf.min.mjs";

GlobalWorkerOptions.workerSrc = "/static/vendor/pdf.worker.min.mjs";

const params = new URLSearchParams(window.location.search);
const token = params.get("token") || "";
const viewer = document.querySelector("#viewer");
const statusElement = document.querySelector("#status");
const pageNumber = document.querySelector("#page-number");
const pageCount = document.querySelector("#page-count");
const zoomLabel = document.querySelector("#zoom-label");
const help = document.querySelector("#help");
const searchPanel = document.querySelector("#search-panel");
const searchInput = document.querySelector("#search-input");
const searchStatus = document.querySelector("#search-status");

let documentHandle = null;
let loadingTask = null;
let revision = 0;
let scale = 1.25;
let scaleMode = "width";
let renderGeneration = 0;
let pendingForward = null;
let searchResults = [];
let searchIndex = -1;
let lastSearch = "";
let pendingG = false;
let pendingGTimer = null;

function apiUrl(path) {
  const url = new URL(path, window.location.origin);
  url.searchParams.set("token", token);
  return url.toString();
}

function setStatus(message, isError = false) {
  statusElement.textContent = message;
  statusElement.classList.toggle("error", isError);
}

function currentPage() {
  const toolbarBottom = document.querySelector("#toolbar").getBoundingClientRect().bottom;
  let closest = 1;
  let distance = Number.POSITIVE_INFINITY;
  for (const page of document.querySelectorAll(".page")) {
    const delta = Math.abs(page.getBoundingClientRect().top - toolbarBottom - 8);
    if (delta < distance) {
      closest = Number(page.dataset.page);
      distance = delta;
    }
  }
  return closest;
}

function captureAnchor() {
  const page = document.querySelector(`.page[data-page="${currentPage()}"]`);
  if (!page) return { page: 1, ratio: 0 };
  const top = page.getBoundingClientRect().top + window.scrollY;
  return {
    page: Number(page.dataset.page),
    ratio: Math.max(0, (window.scrollY + 50 - top) / Math.max(page.offsetHeight, 1)),
  };
}

function restoreAnchor(anchor) {
  const page = document.querySelector(`.page[data-page="${anchor.page}"]`);
  if (!page) return;
  const top = page.getBoundingClientRect().top + window.scrollY;
  window.scrollTo({ top: top + anchor.ratio * page.offsetHeight - 50 });
}

async function calculateScale(pdf) {
  if (scaleMode === "manual") return scale;
  const first = await pdf.getPage(1);
  const base = first.getViewport({ scale: 1 });
  const widthScale = Math.max(0.25, (window.innerWidth - 48) / base.width);
  if (scaleMode === "page") {
    const heightScale = Math.max(0.25, (window.innerHeight - 78) / base.height);
    return Math.min(widthScale, heightScale);
  }
  return widthScale;
}

async function renderPage(pdf, number, generation) {
  const page = await pdf.getPage(number);
  if (generation !== renderGeneration) return;
  const viewport = page.getViewport({ scale });
  const outputScale = window.devicePixelRatio || 1;
  const wrapper = document.createElement("section");
  wrapper.className = "page";
  wrapper.dataset.page = String(number);
  wrapper.dataset.scale = String(scale);
  wrapper.style.width = `${viewport.width}px`;
  wrapper.style.height = `${viewport.height}px`;
  const canvas = document.createElement("canvas");
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  canvas.addEventListener("click", inverseSearch);
  wrapper.append(canvas);
  viewer.append(wrapper);
  const context = canvas.getContext("2d", { alpha: false });
  await page.render({
    canvasContext: context,
    viewport,
    transform: outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0],
  }).promise;
}

async function loadPdf(nextRevision = revision, preservePosition = true) {
  const generation = ++renderGeneration;
  const anchor = preservePosition ? captureAnchor() : { page: 1, ratio: 0 };
  revision = nextRevision;
  setStatus("Loading PDF…");
  try {
    if (loadingTask) await loadingTask.destroy();
    loadingTask = getDocument({
      url: apiUrl(`/document.pdf?revision=${revision}`),
      cMapUrl: "/static/cmaps/",
      cMapPacked: true,
    });
    const pdf = await loadingTask.promise;
    if (generation !== renderGeneration) return;
    documentHandle = pdf;
    scale = await calculateScale(pdf);
    zoomLabel.textContent = `${Math.round(scale * 100)}%`;
    pageCount.textContent = String(pdf.numPages);
    viewer.replaceChildren();
    for (let number = 1; number <= pdf.numPages; number += 1) {
      await renderPage(pdf, number, generation);
    }
    if (generation !== renderGeneration) return;
    restoreAnchor(anchor);
    updateCurrentPage();
    setStatus("Ready");
    if (pendingForward) showForward(pendingForward);
  } catch (error) {
    if (generation !== renderGeneration) return;
    const message = String(error?.message || error);
    if (message.includes("404") || message.includes("Missing PDF")) {
      showWaiting();
    } else {
      setStatus(message, true);
    }
  }
}

function showWaiting() {
  documentHandle = null;
  pageCount.textContent = "0";
  viewer.innerHTML = `
    <section id="empty-state">
      <div class="spinner"></div>
      <h1>Waiting for the first build</h1>
      <p>Paperhere will load the PDF after compilation succeeds.</p>
    </section>`;
  setStatus("Waiting for PDF");
}

function scrollToPage(number, behavior = "smooth") {
  if (!documentHandle) return;
  const bounded = Math.max(1, Math.min(documentHandle.numPages, Number(number) || 1));
  const page = document.querySelector(`.page[data-page="${bounded}"]`);
  page?.scrollIntoView({ behavior, block: "start" });
  pageNumber.value = String(bounded);
}

function showForward(position) {
  pendingForward = position;
  const page = document.querySelector(`.page[data-page="${position.page}"]`);
  if (!page) return;
  document.querySelector(".synctex-highlight")?.remove();
  const pageScale = Number(page.dataset.scale);
  const marker = document.createElement("div");
  marker.className = "synctex-highlight";
  marker.style.left = `${position.h * pageScale}px`;
  marker.style.top = `${Math.max(0, position.v - Math.abs(position.height)) * pageScale}px`;
  marker.style.width = `${Math.max(8, position.width * pageScale)}px`;
  marker.style.height = `${Math.max(8, Math.abs(position.height) * pageScale)}px`;
  page.append(marker);
  marker.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
  pageNumber.value = String(position.page);
  setStatus("Forward SyncTeX");
}

async function inverseSearch(event) {
  if (!event.ctrlKey) return;
  event.preventDefault();
  const page = event.currentTarget.closest(".page");
  const rect = event.currentTarget.getBoundingClientRect();
  const pageScale = Number(page.dataset.scale);
  setStatus("Inverse SyncTeX…");
  try {
    const response = await fetch(apiUrl("/api/inverse"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page: Number(page.dataset.page),
        x: (event.clientX - rect.left) / pageScale,
        y: (event.clientY - rect.top) / pageScale,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Inverse search failed");
    setStatus(`${result.path.split("/").pop()}:${result.line}`);
  } catch (error) {
    setStatus(String(error?.message || error), true);
  }
}

function updateCurrentPage() {
  if (documentHandle) pageNumber.value = String(currentPage());
}

async function setScale(nextScale, mode = "manual") {
  scale = Math.max(0.25, Math.min(5, nextScale));
  scaleMode = mode;
  if (documentHandle) await loadPdf(revision, true);
}

async function runSearch(query) {
  if (!documentHandle || !query) return;
  lastSearch = query;
  searchResults = [];
  searchIndex = -1;
  searchStatus.textContent = "searching…";
  const needle = query.toLocaleLowerCase();
  for (let number = 1; number <= documentHandle.numPages; number += 1) {
    const page = await documentHandle.getPage(number);
    const content = await page.getTextContent();
    const text = content.items.map((item) => item.str || "").join(" ").toLocaleLowerCase();
    if (text.includes(needle)) searchResults.push(number);
  }
  searchStatus.textContent = `${searchResults.length} pages`;
  if (searchResults.length) {
    searchIndex = 0;
    scrollToPage(searchResults[0]);
  }
}

function repeatSearch(direction) {
  if (!searchResults.length) {
    if (lastSearch) void runSearch(lastSearch);
    return;
  }
  searchIndex = (searchIndex + direction + searchResults.length) % searchResults.length;
  scrollToPage(searchResults[searchIndex]);
  searchStatus.textContent = `${searchIndex + 1}/${searchResults.length}`;
}

function openSearch() {
  searchPanel.classList.remove("hidden");
  searchInput.focus();
  searchInput.select();
}

function closeOverlays() {
  help.classList.add("hidden");
  searchPanel.classList.add("hidden");
  searchInput.blur();
}

function handleKey(event) {
  const target = event.target;
  if (target instanceof HTMLInputElement) {
    if (event.key === "Escape") {
      closeOverlays();
      event.preventDefault();
    }
    return;
  }
  const halfPage = window.innerHeight * 0.48;
  const fullPage = window.innerHeight * 0.88;
  let handled = true;
  if (event.key === "j") window.scrollBy({ top: 90 });
  else if (event.key === "k") window.scrollBy({ top: -90 });
  else if (event.key === "h") window.scrollBy({ left: -90 });
  else if (event.key === "l") window.scrollBy({ left: 90 });
  else if (event.key === "J") scrollToPage(currentPage() + 1);
  else if (event.key === "K") scrollToPage(currentPage() - 1);
  else if (event.ctrlKey && event.key === "d") window.scrollBy({ top: halfPage });
  else if (event.ctrlKey && event.key === "u") window.scrollBy({ top: -halfPage });
  else if (event.ctrlKey && event.key === "f") window.scrollBy({ top: fullPage });
  else if (event.ctrlKey && event.key === "b") window.scrollBy({ top: -fullPage });
  else if (event.key === "G") scrollToPage(documentHandle?.numPages || 1);
  else if (event.key === "g") {
    if (pendingG) {
      clearTimeout(pendingGTimer);
      pendingG = false;
      scrollToPage(1);
    } else {
      pendingG = true;
      pendingGTimer = setTimeout(() => { pendingG = false; }, 500);
    }
  }
  else if (["+", "="].includes(event.key)) void setScale(scale * 1.1);
  else if (event.key === "-") void setScale(scale / 1.1);
  else if (event.key === "s") void setScale(scale, "width");
  else if (event.key === "a") void setScale(scale, "page");
  else if (event.key === "r") void loadPdf(revision, true);
  else if (event.key === "/") openSearch();
  else if (event.key === "n") repeatSearch(1);
  else if (event.key === "N") repeatSearch(-1);
  else if (event.key === "?") help.classList.toggle("hidden");
  else if (event.key === "Escape") closeOverlays();
  else handled = false;
  if (handled) event.preventDefault();
}

function connectEvents() {
  const events = new EventSource(apiUrl("/events"));
  events.onopen = () => setStatus("Connected");
  events.onerror = () => setStatus("Reconnecting…", true);
  events.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "status") {
      revision = event.revision;
      if (event.pdfReady) void loadPdf(revision, false);
      else showWaiting();
    } else if (event.type === "reload") {
      void loadPdf(event.revision, true);
    } else if (event.type === "forward") {
      showForward(event);
    }
  };
}

document.querySelector("#previous").addEventListener("click", () => scrollToPage(currentPage() - 1));
document.querySelector("#next").addEventListener("click", () => scrollToPage(currentPage() + 1));
document.querySelector("#zoom-in").addEventListener("click", () => void setScale(scale * 1.1));
document.querySelector("#zoom-out").addEventListener("click", () => void setScale(scale / 1.1));
document.querySelector("#fit-width").addEventListener("click", () => void setScale(scale, "width"));
document.querySelector("#fit-page").addEventListener("click", () => void setScale(scale, "page"));
document.querySelector("#help-button").addEventListener("click", () => help.classList.toggle("hidden"));
pageNumber.addEventListener("change", () => scrollToPage(pageNumber.value));
searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    void runSearch(searchInput.value);
    event.preventDefault();
  }
});
window.addEventListener("keydown", handleKey);
window.addEventListener("scroll", updateCurrentPage, { passive: true });
window.addEventListener("resize", () => {
  if (scaleMode !== "manual" && documentHandle) void loadPdf(revision, true);
});

connectEvents();
