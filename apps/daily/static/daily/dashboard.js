// 當日統計：每隔 data-refresh 秒重新抓 dashboard 區塊；選了檔案準備匯入、或關掉自動更新時不更新。
(function () {
  var box = document.getElementById("daily-dashboard");
  if (!box) return;
  var seconds = parseInt(box.dataset.refresh, 10) || 60;
  var toggle = document.getElementById("daily-auto-refresh");
  var fileInput = document.querySelector("#daily-import input[type=file]");

  function busy() {
    return (toggle && !toggle.checked) || (fileInput && fileInput.files.length > 0) || document.hidden;
  }

  function refresh() {
    if (busy()) return;
    // 記住哪些展開區塊是開著的（依順序），更新後照原樣打開
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
        var stamp = document.getElementById("daily-refreshed-at");
        if (stamp) stamp.textContent += "（更新失敗，稍後再試）";
      });
  }

  setInterval(refresh, seconds * 1000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
