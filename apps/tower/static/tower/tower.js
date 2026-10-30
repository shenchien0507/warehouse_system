// 數據塔：每隔 data-refresh 秒重新抓進度區塊；關掉自動更新或分頁在背景時不更新。
(function () {
  var box = document.getElementById("tower-board");
  if (!box) return;
  var seconds = parseInt(box.dataset.refresh, 10) || 60;
  var toggle = document.getElementById("tower-auto-refresh");

  function refresh() {
    if ((toggle && !toggle.checked) || document.hidden) return;
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

  setInterval(refresh, seconds * 1000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
