// 編輯頁開著時每分鐘延長編輯鎖；鎖被別人拿走（被強制解除後有人開始編輯）時提醒。
// 不是按頁面上的按鈕離開（例如點選單、關分頁）時放開編輯鎖。
(() => {
  const script = document.currentScript;
  const url = script.dataset.lockUrl;
  const csrf = document.querySelector("input[name=csrfmiddlewaretoken]").value;
  const body = (action) => new URLSearchParams({ action, date: script.dataset.date, csrfmiddlewaretoken: csrf });
  let submitting = false;
  document.querySelectorAll("form").forEach((form) => form.addEventListener("submit", () => { submitting = true; }));
  document.querySelectorAll("a[href]").forEach((link) => {
    if (link.href.includes(script.dataset.newUrl)) link.addEventListener("click", () => { submitting = true; });
  });
  window.addEventListener("pagehide", () => { if (!submitting) navigator.sendBeacon(url, body("release")); });
  const timer = setInterval(async () => {
    try {
      const response = await fetch(url, { method: "POST", body: body("touch") });
      const data = await response.json();
      if (!data.ok) {
        clearInterval(timer);
        alert("別人已經開始編輯工位安排，你這頁的修改將無法儲存。");
      }
    } catch (e) { /* 網路暫時斷線，下一分鐘再試 */ }
  }, 60000);
})();
