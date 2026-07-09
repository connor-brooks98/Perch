// Backyard Field Log — reads the static detections.json the classifier writes.
const DATA_URL = "data/detections.json";
const REFRESH_MS = 60_000;

const $ = (sel) => document.querySelector(sel);
let allDetections = [];

function timeAgo(iso) {
  if (!iso) return "";
  const then = new Date(iso.replace(" ", "T"));
  const secs = Math.max(0, (Date.now() - then.getTime()) / 1000);
  const mins = secs / 60, hrs = mins / 60, days = hrs / 24;
  if (secs < 90) return "just now";
  if (mins < 60) return `${Math.round(mins)} min ago`;
  if (hrs < 24) return `${Math.round(hrs)} hr ago`;
  if (days < 7) return `${Math.round(days)} day${Math.round(days) === 1 ? "" : "s"} ago`;
  return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function pct(conf) { return `${Math.round(conf * 100)}%`; }

function renderStats(stats) {
  $('[data-stat="species"]').textContent = stats.species ?? 0;
  $('[data-stat="today"]').textContent = stats.today ?? 0;
  $('[data-stat="total"]').textContent = stats.total ?? 0;
}

function renderHero(d) {
  const latest = $("#latest");
  if (!d) { latest.hidden = true; return; }
  latest.hidden = false;
  const img = $("#hero-img");
  img.src = d.thumb; img.alt = `Photo of ${d.common}`;
  $("#hero-common").textContent = d.common;
  $("#hero-sci").textContent = d.scientific || "";
  $("#hero-when").textContent = timeAgo(d.captured_at);
  $("#hero-conf-fill").style.width = pct(d.confidence);
  $("#hero-conf-label").textContent = `${pct(d.confidence)} sure`;
}

function cardEl(d) {
  const el = document.createElement("article");
  el.className = "card";
  el.innerHTML = `
    <div class="card-photo"><img loading="lazy" alt="Photo of ${d.common}"></div>
    <div class="card-body">
      <h3 class="species"></h3>
      <p class="scientific"></p>
      <div class="card-meta"><span class="when"></span><span class="badge"></span></div>
    </div>`;
  el.querySelector("img").src = d.thumb;
  el.querySelector(".species").textContent = d.common;
  el.querySelector(".scientific").textContent = d.scientific || "";
  el.querySelector(".when").textContent = timeAgo(d.captured_at);
  el.querySelector(".badge").textContent = pct(d.confidence);
  return el;
}

function renderCards(list) {
  const cards = $("#cards");
  const empty = $("#empty");
  cards.innerHTML = "";
  if (!list.length) { empty.hidden = false; return; }
  empty.hidden = true;
  const frag = document.createDocumentFragment();
  list.forEach((d) => frag.appendChild(cardEl(d)));
  cards.appendChild(frag);
}

function renderTally(species) {
  const section = $("#tally");
  const ul = $("#tally-list");
  if (!species || !species.length) { section.hidden = true; return; }
  section.hidden = false;
  ul.innerHTML = "";
  species.forEach((s) => {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.className = "tally-name";
    name.innerHTML = `${s.common}${s.scientific ? ` <em>${s.scientific}</em>` : ""}`;
    const count = document.createElement("span");
    count.className = "tally-count";
    count.textContent = `${s.count} visit${s.count === 1 ? "" : "s"} · ${timeAgo(s.last_seen)}`;
    li.append(name, count);
    ul.appendChild(li);
  });
}

function applyFilter() {
  const q = $("#filter").value.trim().toLowerCase();
  const list = !q ? allDetections : allDetections.filter((d) =>
    d.common.toLowerCase().includes(q) ||
    (d.scientific || "").toLowerCase().includes(q));
  renderCards(list.slice(0, 60));
}

async function load() {
  try {
    const res = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    allDetections = data.detections || [];
    renderStats(data.stats || {});
    renderHero(allDetections[0]);
    renderTally(data.species);
    applyFilter();
    $("#updated").textContent = `Updated ${timeAgo(data.generated_at)}`;
  } catch (err) {
    $("#updated").textContent = "Couldn't reach the feeder — retrying shortly.";
    console.error("load failed:", err);
  }
}

$("#filter").addEventListener("input", applyFilter);
$("#refresh").addEventListener("click", load);
load();
setInterval(load, REFRESH_MS);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
