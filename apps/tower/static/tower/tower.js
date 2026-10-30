// 數據塔：每隔 data-refresh 秒重新抓進度區塊；關掉自動更新或分頁在背景時不更新。
(function () {
  var box = document.getElementById("tower-board");
  if (!box) return;
  var seconds = parseInt(box.dataset.refresh, 10) || 60;
  var toggle = document.getElementById("tower-auto-refresh");

  function refresh() {
    if ((toggle && !toggle.checked) || document.hidden || (current && current.classList.contains("is-open"))) return;
    // 記住展開區塊是否開著，更新後照原樣打開
    var open = Array.prototype.map.call(box.querySelectorAll("details"), function (el) { return el.open; });
    fetch(box.dataset.url, { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
      .then(function (response) { return response.ok ? response.text() : Promise.reject(response.status); })
      .then(function (html) {
        box.innerHTML = html;
        box.querySelectorAll("details").forEach(function (el, i) {
          if (i < open.length) el.open = open[i];
        });
      })
      .catch(function () {
        var stamp = document.getElementById("tower-refreshed-at");
        if (stamp) stamp.textContent += "（更新失敗，稍後再試）";
      });
  }

  // 數字卡：停在上面 0.5 秒開詳細小窗，放在卡片右邊（放不下換左邊），上下左右都限制在畫面裡
  var DELAY = 500, GAP = 8, MARGIN = 8, timer = null, current = null;

  function place(tile) {
    var pop = tile.querySelector(".tower-pop");
    if (!pop) return;
    var rect = tile.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    var left = rect.right + GAP;
    if (left + w > window.innerWidth - MARGIN) left = rect.left - GAP - w;
    if (left < MARGIN) left = Math.min(Math.max(rect.left + rect.width / 2 - w / 2, MARGIN), Math.max(MARGIN, window.innerWidth - w - MARGIN));
    var top = rect.top + rect.height / 2 - h / 2;
    top = Math.min(Math.max(top, MARGIN), Math.max(MARGIN, window.innerHeight - h - MARGIN));
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  }

  function close() {
    clearTimeout(timer);
    if (current) current.classList.remove("is-open");
    current = null;
  }

  box.addEventListener("mouseover", function (event) {
    var tile = event.target.closest(".tower-tile");
    if (!tile || tile === current) return;
    close();
    timer = setTimeout(function () { place(tile); tile.classList.add("is-open"); current = tile; }, DELAY);
    current = tile;
  });
  box.addEventListener("mouseout", function (event) {
    var tile = event.target.closest(".tower-tile");
    if (tile && !tile.contains(event.relatedTarget)) close();
  });
  window.addEventListener("scroll", close, { passive: true });

  setInterval(refresh, seconds * 1000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
