// 全站共用腳本；各 app 專屬腳本放在 app/static/app/ 下

// 24 小時制時間欄位（data-time24）：格子裡固定有冒號，只要打數字，依序填進 __:__ 的位置
(function () {
  var EMPTY = "__:__";
  var SLOTS = [0, 1, 3, 4]; // 數字的位置，2 是冒號

  function isTime(el) {
    return el && el.matches && el.matches("input[data-time24]");
  }

  // 把任何輸入整理成 __:__ 的樣子（貼上、手機輸入法等沒有逐鍵事件時用）
  function normalize(value) {
    var m = value.match(/^(\d{1,2}):(\d{2})$/);
    var digits = m ? (m[1].length === 1 ? "0" + m[1] : m[1]) + m[2] : value.replace(/\D/g, "").slice(0, 4);
    var chars = EMPTY.split("");
    for (var i = 0; i < digits.length; i++) chars[SLOTS[i]] = digits[i];
    return chars.join("");
  }

  function nextSlot(pos) {
    for (var i = 0; i < SLOTS.length; i++) if (SLOTS[i] >= pos) return SLOTS[i];
    return null;
  }

  function prevSlot(pos) {
    for (var i = SLOTS.length - 1; i >= 0; i--) if (SLOTS[i] < pos) return SLOTS[i];
    return null;
  }

  function setChar(input, pos, ch) {
    var chars = input.value.split("");
    chars[pos] = ch;
    input.value = chars.join("");
  }

  function caret(input, pos) {
    input.setSelectionRange(pos, pos);
  }

  document.addEventListener("focusin", function (event) {
    var input = event.target;
    if (!isTime(input)) return;
    input.value = normalize(input.value); // 游標位置交給 click 和 keydown 處理
  });

  document.addEventListener("keydown", function (event) {
    var input = event.target;
    if (!isTime(input) || event.ctrlKey || event.metaKey || event.altKey) return;
    if (input.value.length !== EMPTY.length) input.value = normalize(input.value);
    var start = input.selectionStart, end = input.selectionEnd, pos;
    if (/^\d$/.test(event.key)) {
      event.preventDefault();
      if (end > start) {
        // 選取了一段：先清掉選取範圍的數字
        for (var i = start; i < end; i++) if (i !== 2) setChar(input, i, "_");
      }
      pos = nextSlot(start);
      var blank = input.value.indexOf("_");
      if (end === start && blank !== -1 && (pos === null || pos > blank)) pos = blank; // 游標在空格後面時從第一個空格開始填
      if (pos === null) return;
      setChar(input, pos, event.key);
      var after = nextSlot(pos + 1);
      caret(input, after === null ? EMPTY.length : after);
    } else if (event.key === "Backspace" || event.key === "Delete") {
      event.preventDefault();
      if (end > start) {
        for (var j = start; j < end; j++) if (j !== 2) setChar(input, j, "_");
        caret(input, start);
        return;
      }
      pos = event.key === "Backspace" ? prevSlot(start) : nextSlot(start);
      if (pos === null) return;
      setChar(input, pos, "_");
      caret(input, pos);
    } else if (event.key.length === 1) {
      event.preventDefault(); // 其他字（包括冒號）都不接受
    }
  });

  document.addEventListener("click", function (event) {
    // 點在空白格子後面時，游標移到第一個空格
    var input = event.target;
    if (!isTime(input) || input.selectionStart !== input.selectionEnd) return;
    var blank = input.value.indexOf("_");
    if (blank !== -1 && input.selectionStart > blank) caret(input, blank);
  });

  document.addEventListener("input", function (event) {
    var input = event.target;
    if (!isTime(input)) return;
    var value = normalize(input.value);
    if (value !== input.value) {
      input.value = value;
      var first = value.indexOf("_");
      caret(input, first === -1 ? EMPTY.length : first);
    }
  });

  document.addEventListener("focusout", function (event) {
    var input = event.target;
    if (isTime(input) && input.value === EMPTY) input.value = ""; // 沒填就留空白
  });

  document.addEventListener("submit", function (event) {
    // 在格子裡直接按 Enter 送出時不會先離開格子，這裡再清一次
    event.target.querySelectorAll("input[data-time24]").forEach(function (input) {
      if (input.value === EMPTY) input.value = "";
    });
  }, true);
})();

// 深色／淺色模式切換：導覽列的按鈕，選好的模式記在瀏覽器（localStorage），每台電腦各自記
(function () {
  var root = document.documentElement;
  function label() {
    var dark = root.getAttribute("data-bs-theme") === "dark";
    document.querySelectorAll("[data-theme-label]").forEach(function (el) { el.textContent = dark ? "淺色模式" : "深色模式"; });
  }
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-theme-toggle]");
    if (!button) return;
    var next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-bs-theme", next);
    try { localStorage.setItem("wh-theme", next); } catch (e) {}
    label();
  });
  label();
})();

// 顏色條提示（data-tip）：滑鼠移到長條上馬上顯示這段是什麼數據（瀏覽器內建 title 要等一秒，又會被卡片連結蓋住）
(function () {
  var tip = null;

  function box() {
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "wh-tip";
      document.body.appendChild(tip);
    }
    return tip;
  }

  function place(event) {
    var el = box(), x = event.clientX + 12, y = event.clientY + 16;
    var w = el.offsetWidth, h = el.offsetHeight;
    if (x + w > window.innerWidth - 8) x = window.innerWidth - w - 8;
    if (y + h > window.innerHeight - 8) y = event.clientY - h - 10;
    el.style.left = x + "px";
    el.style.top = y + "px";
  }

  document.addEventListener("mousemove", function (event) {
    var target = event.target.closest && event.target.closest("[data-tip]");
    if (!target) {
      if (tip) tip.classList.remove("is-on");
      return;
    }
    var el = box();
    if (el.textContent !== target.dataset.tip) el.textContent = target.dataset.tip;
    el.classList.add("is-on");
    place(event);
  });

  document.addEventListener("mouseleave", function () {
    if (tip) tip.classList.remove("is-on");
  });
})();
