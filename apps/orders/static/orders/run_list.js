// 匯入頁：選好檔案就先檢查並顯示結果；換檔、按「移除」會清掉這個檔案上次的錯誤
(function () {
  const form = document.querySelector("form[data-check-url]");
  if (!form) return;

  // 匯入失敗後頁面是 POST 的結果，重新整理會再送一次；換成一般網址，重新整理就是乾淨的頁面
  if (window.history.replaceState) window.history.replaceState(null, "", window.location.href);

  const token = form.querySelector("input[name=csrfmiddlewaretoken]").value;
  const pending = {}; // 欄位 id → 目前在等的檢查，晚回來的舊結果不要蓋掉新的

  function clearServerErrors(id) {
    document.querySelectorAll(`.server-error[data-for="${id}"]`).forEach((el) => el.remove());
    const input = document.getElementById(id);
    input.closest(".wh-field").classList.remove("has-error");
    // 上面的總提示也一起拿掉：只要有換過檔，就是新的一次，等按匯入再看結果
    document.querySelectorAll(".alert.server-error").forEach((el) => el.remove());
  }

  function show(id, kind, message, errors, errorCount) {
    const box = document.querySelector(`.file-check[data-for="${id}"]`);
    box.className = `file-check small mt-1 ${kind}`;
    box.textContent = message;
    if (errors && errors.length) {
      const list = document.createElement("ul");
      list.className = "mb-0 ps-3";
      errors.slice(0, 10).forEach(([row, label, raw, error]) => {
        const item = document.createElement("li");
        item.textContent = `第 ${row} 列 ${label}「${raw || "（空白）"}」：${error}`;
        list.appendChild(item);
      });
      box.appendChild(list);
      if (errorCount > 10) box.appendChild(document.createTextNode(`只列出前 10 筆，共 ${errorCount} 列。`));
    }
  }

  function check(input) {
    const id = input.id;
    const file = input.files[0];
    if (!file) { show(id, "", ""); pending[id] = null; return; }
    show(id, "text-muted", "檢查中…");
    const data = new FormData();
    data.append("file", file);
    const request = fetch(form.dataset.checkUrl, { method: "POST", body: data, headers: { "X-CSRFToken": token } })
      .then((response) => {
        if (!response.ok) throw new Error(response.status);
        return response.json();
      });
    pending[id] = request;
    request.then((result) => {
      if (pending[id] !== request) return;
      show(id, result.ok ? "text-success" : "text-danger", result.message, result.errors, result.error_count);
    }).catch(() => {
      if (pending[id] === request) show(id, "text-warning", "現在沒辦法先檢查，按「匯入並統計」時會再檢查。");
    });
  }

  form.querySelectorAll("input[type=file]").forEach((input) => {
    const button = form.querySelector(`.file-clear[data-target="${input.id}"]`);
    const refresh = () => { if (button) button.hidden = !input.files.length; };
    input.addEventListener("change", () => {
      clearServerErrors(input.id);
      refresh();
      check(input);
    });
    if (button) {
      button.addEventListener("click", () => {
        input.value = "";
        clearServerErrors(input.id);
        refresh();
        check(input);
      });
    }
    refresh();
  });
})();
