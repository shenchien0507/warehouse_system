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
    input.value = normalize(input.value);
    var first = input.value.indexOf("_");
    setTimeout(function () { caret(input, first === -1 ? 0 : first); }, 0);
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
