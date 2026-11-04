// 固定輸入列：Enter 跳到下一格，最後一格（數量）按 Enter 才送出；有錯時游標停在第一個錯的格子
(function () {
  var form = document.querySelector("[data-quick-form]");
  var kind = form.querySelector("[data-kind-select]");
  if (kind) {
    kind.addEventListener("change", function () {
      var params = new URLSearchParams(window.location.search);
      if (kind.value) { params.set("kind", kind.value); } else { params.delete("kind"); }
      params.delete("page");
      window.location = window.location.pathname + (params.toString() ? "?" + params : "");
    });
  }
  var inputs = Array.prototype.slice.call(form.querySelectorAll("[data-quick]"));
  inputs.forEach(function (input, i) {
    input.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" || event.isComposing || i === inputs.length - 1) { return; }
      event.preventDefault();
      inputs[i + 1].focus();
      inputs[i + 1].select();
    });
  });
  var invalid = form.querySelector(".is-invalid");
  if (invalid) { invalid.focus(); invalid.select(); } else { inputs[0].focus(); }
})();

// 列表勾選：全選、顯示勾了幾筆；批量修改帶著勾選的編號到修改頁
(function () {
  var form = document.getElementById("bulk-form");
  var boxes = Array.prototype.slice.call(document.querySelectorAll("input[name=ids][form=bulk-form]"));
  var all = document.querySelector("[data-select-all]");
  var count = document.querySelector("[data-bulk-count]");
  var buttons = document.querySelectorAll("[data-bulk-edit], [data-bulk-delete]");
  if (!boxes.length) { all.disabled = true; }

  function checked() { return boxes.filter(function (box) { return box.checked; }); }

  function refresh() {
    var n = checked().length;
    count.textContent = n ? "已勾選 " + n + " 筆" : "勾選要批量操作的紀錄";
    buttons.forEach(function (button) { button.disabled = !n; });
    all.checked = n > 0 && n === boxes.length;
    all.indeterminate = n > 0 && n < boxes.length;
  }

  all.addEventListener("change", function () {
    boxes.forEach(function (box) { box.checked = all.checked; });
    refresh();
  });
  boxes.forEach(function (box) { box.addEventListener("change", refresh); });
  document.querySelector("[data-bulk-edit]").addEventListener("click", function () {
    var query = checked().map(function (box) { return "ids=" + encodeURIComponent(box.value); }).join("&");
    window.location = form.dataset.editUrl + "?" + query;
  });
  refresh();
})();
