// 一個來源欄只能選一次：已被其他欄位選走的選項停用
(function () {
  const selects = Array.from(document.querySelectorAll("select.source-column"));
  function refresh() {
    const taken = new Set(selects.map((s) => s.value).filter(Boolean));
    selects.forEach((s) => {
      Array.from(s.options).forEach((o) => {
        o.disabled = Boolean(o.value) && o.value !== s.value && taken.has(o.value);
      });
    });
  }
  // 改了還沒儲存就不能按生效，免得生效的是舊的對應
  const activate = document.querySelector("#activate-button");
  selects.forEach((s) => s.addEventListener("change", () => {
    refresh();
    if (activate) { activate.disabled = true; activate.title = "請先儲存再生效"; }
  }));
  refresh();
})();
