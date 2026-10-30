// 登記紀錄的多列輸入：Enter 往下、拖曳右下角方塊向下填滿（編號、名稱接續）、從 Excel 貼上多列
(function () {
  var form = document.getElementById("record-grid");
  if (!form) return;
  var tbody = form.querySelector("tbody");
  var template = document.getElementById("empty-row");
  var total = form.querySelector("input[name$='-TOTAL_FORMS']");
  var maxRows = parseInt(form.querySelector("input[name$='-MAX_NUM_FORMS']").value, 10);
  var COLUMNS = ["number", "date_text", "name", "quantity"];

  var handle = document.createElement("div");
  handle.className = "fill-handle";
  handle.title = "往下拉填滿";
  var active = null; // 目前選到的格子（input）

  function rows() {
    return Array.prototype.slice.call(tbody.querySelectorAll("tr[data-row]"));
  }

  function cell(row, col) {
    return row.querySelector("[data-col='" + col + "']");
  }

  function addRows(count) {
    var added = 0;
    while (added < count && rows().length < maxRows) {
      var index = parseInt(total.value, 10);
      var html = template.innerHTML.replace(/__prefix__/g, index);
      tbody.insertAdjacentHTML("beforeend", html);
      var row = rows()[rows().length - 1];
      row.querySelector(".row-no").textContent = index + 1;
      total.value = index + 1;
      added++;
    }
    return added;
  }

  // 確保從第 from 列起往下有 count 列，不夠就加
  function ensureRows(from, count) {
    var missing = from + count - rows().length;
    if (missing > 0) addRows(missing);
  }

  // 編號接續：結尾的數字加 step，保留前面的文字和補零的位數（A009 → A010，15 → 16）；沒有數字就照抄
  function nextNumber(value, step) {
    var m = value.match(/^(.*?)(\d+)$/);
    if (!m) return value;
    var n = String(parseInt(m[2], 10) + step);
    while (n.length < m[2].length) n = "0" + n;
    return m[1] + n;
  }

  var SEQUENCE_COLUMNS = ["number", "name"]; // 往下拉會接續的欄，其他欄照抄

  function fillValue(col, value, step) {
    return SEQUENCE_COLUMNS.indexOf(col) >= 0 ? nextNumber(value, step) : value;
  }

  function setActive(input) {
    if (active) active.parentNode.classList.remove("active");
    active = input;
    if (!input) return;
    input.parentNode.classList.add("active");
    input.parentNode.appendChild(handle);
  }

  form.addEventListener("focusin", function (e) {
    if (e.target.matches("[data-col]")) setActive(e.target);
  });

  // Enter：跳到下一列同一欄（不送出表單），最後一列會自動加一列
  form.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" || !e.target.matches("[data-col]") || e.isComposing) return;
    e.preventDefault();
    var list = rows();
    var i = list.indexOf(e.target.closest("tr"));
    ensureRows(i + 1, 1);
    var next = rows()[i + 1];
    if (next) cell(next, e.target.dataset.col).focus();
  });

  // 拖曳填滿：按住方塊往下拉，放開時把來源格的值填到經過的列
  var drag = null;

  function rowAt(y) {
    var list = rows();
    for (var i = 0; i < list.length; i++) {
      var rect = list[i].getBoundingClientRect();
      if (y < rect.bottom) return i;
    }
    return list.length - 1;
  }

  function markTargets(toIndex) {
    rows().forEach(function (row, i) {
      var target = cell(row, drag.col).parentNode;
      target.classList.toggle("fill-target", i > drag.from && i <= toIndex);
    });
  }

  handle.addEventListener("pointerdown", function (e) {
    if (!active) return;
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    drag = { col: active.dataset.col, from: rows().indexOf(active.closest("tr")), to: -1, value: active.value };
  });

  handle.addEventListener("pointermove", function (e) {
    if (!drag) return;
    // 拉到表格最下面時自動加列，可以一直往下拉
    var last = rows()[rows().length - 1];
    if (e.clientY > last.getBoundingClientRect().bottom) addRows(1);
    drag.to = rowAt(e.clientY);
    markTargets(drag.to);
  });

  function endDrag() {
    if (!drag) return;
    var list = rows();
    for (var i = drag.from + 1; i <= drag.to; i++) {
      cell(list[i], drag.col).value = fillValue(drag.col, drag.value, i - drag.from);
    }
    if (drag.to > drag.from) dirty = true;
    drag.to = -1;
    markTargets(-1);
    drag = null;
  }

  handle.addEventListener("pointerup", endDrag);
  handle.addEventListener("pointercancel", endDrag);

  // 從 Excel 貼上多列多欄：從目前這格開始往右、往下填，列不夠自動加
  form.addEventListener("paste", function (e) {
    var input = e.target;
    if (!input.matches("[data-col]")) return;
    var text = (e.clipboardData || window.clipboardData).getData("text");
    if (text.indexOf("\t") < 0 && text.replace(/\r?\n$/, "").indexOf("\n") < 0) return; // 單一格照一般貼上
    e.preventDefault();
    var lines = text.replace(/\r/g, "").replace(/\n$/, "").split("\n");
    var start = rows().indexOf(input.closest("tr"));
    var startCol = COLUMNS.indexOf(input.dataset.col);
    ensureRows(start, lines.length);
    dirty = true;
    var list = rows();
    lines.forEach(function (line, r) {
      if (!list[start + r]) return;
      line.split("\t").forEach(function (value, c) {
        var col = COLUMNS[startCol + c];
        if (col) cell(list[start + r], col).value = value.trim();
      });
    });
  });

  form.addEventListener("click", function (e) {
    var add = e.target.closest("[data-add-rows]");
    if (add) addRows(parseInt(add.dataset.addRows, 10));
    var clear = e.target.closest("[data-clear-row]");
    if (clear) {
      clear.closest("tr").querySelectorAll("[data-col]").forEach(function (input) { input.value = ""; });
    }
  });

  // 沒存就離開時提醒
  var dirty = false;
  form.addEventListener("input", function () { dirty = true; });
  form.addEventListener("submit", function () { dirty = false; });
  window.addEventListener("beforeunload", function (e) {
    if (dirty) { e.preventDefault(); e.returnValue = ""; }
  });
})();
