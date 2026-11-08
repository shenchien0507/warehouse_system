// 新增登記頁：最新一筆編號；選的種類今天的當日統計總數、已登記、這批正在打的數量、存完剩下多少。
// 打數量時馬上算；已登記、總數每 15 秒跟伺服器拿一次（別人同時在登記、或當日統計匯入新訂單時會變）。
(function () {
  var box = document.getElementById("kind-live");
  var select = document.getElementById("grid-kind");
  var form = document.getElementById("record-grid");
  var dataTag = document.getElementById("kind-stats-data");
  if (!box || !select || !form || !dataTag) return;
  var stats = JSON.parse(dataTag.textContent);
  var updatedAt = new Date();

  function stat(name) { return box.querySelector("[data-stat='" + name + "']"); }

  function batchQuantity() {
    var sum = 0;
    form.querySelectorAll("input[name$='-quantity']").forEach(function (input) {
      var value = input.value.trim();
      if (/^\d+$/.test(value)) sum += parseInt(value, 10);
    });
    return sum;
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  // 最新一筆編號：不分種類，別人剛登記的也會跟著更新
  function renderLatest() {
    var el = document.getElementById("latest-number");
    if (!el) return;
    var latest = stats.latest;
    var previous = stats.previous;
    el.querySelector("[data-latest='number']").textContent = latest ? latest.number : "（今天還沒登記）";
    el.querySelector("[data-latest='detail']").textContent = latest
      ? "（" + (latest.kind || "未分類") + "，" + latest.by + "，" + latest.at + "）"
      : previous ? "（前一個作業日 " + previous.day + " 最後一筆是 " + previous.number + "，編號每天重新一輪）" : "";
  }

  function render() {
    renderLatest();
    var kind = stats.kinds[select.value];
    if (!kind) { box.hidden = true; return; }
    box.hidden = false;
    var batch = batchQuantity();
    var left = kind.total - kind.registered - batch;
    stat("total").textContent = kind.total;
    stat("registered").textContent = kind.registered;
    stat("batch").textContent = batch;
    stat("left-label").textContent = left < 0 ? "存完會超出" : "存完剩下";
    stat("left").textContent = left < 0 ? -left : left;
    box.classList.toggle("is-over", left < 0);
    var note = "更新於 " + pad(updatedAt.getHours()) + ":" + pad(updatedAt.getMinutes()) + ":" + pad(updatedAt.getSeconds());
    if (left < 0) note = "超過當日統計總數，這樣存不進去；有新訂單請先到當日統計匯入。 " + note;
    stat("note").textContent = note;
  }

  function refresh() {
    if (document.hidden) return;
    fetch(box.dataset.url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (!data) return;
        stats = data;
        updatedAt = new Date();
        render();
      })
      .catch(function () {});
  }

  select.addEventListener("change", render);
  form.addEventListener("input", render);
  // 貼上、拖曳填滿是程式改值，不會觸發 input，順便在這些動作後重算
  form.addEventListener("paste", function () { setTimeout(render, 0); });
  document.addEventListener("pointerup", function () { setTimeout(render, 0); });
  form.addEventListener("click", function () { setTimeout(render, 0); });
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
  setInterval(refresh, 15000);
  render();
})();
