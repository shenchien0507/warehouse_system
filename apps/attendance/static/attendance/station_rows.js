(() => {
  const tbody = document.getElementById("station-rows");
  if (!tbody) return;
  const rows = [...tbody.querySelectorAll("tr.person-row")];
  const select = (row) => row.querySelector("select");
  const visible = (row) => !row.hidden;
  const checked = () => rows.filter((row) => visible(row) && row.querySelector(".row-check").checked);
  const countText = document.getElementById("checked-count");
  const applyButton = document.getElementById("bulk-apply");
  const checkAll = document.getElementById("check-all");
  const onlyUnassigned = document.getElementById("only-unassigned");

  function refreshCount() {
    const n = checked().length;
    countText.textContent = n;
    applyButton.disabled = n === 0;
  }

  function filter() {
    rows.forEach((row) => {
      row.hidden = onlyUnassigned.checked && select(row).value !== "";
      if (row.hidden) row.querySelector(".row-check").checked = false;
    });
    tbody.querySelectorAll("tr.group-row").forEach((header) => {
      header.hidden = !rows.some((row) => visible(row) && row.dataset.group === header.dataset.group);
    });
    refreshCount();
  }

  // 按工位分組：依目前選的工位排，「未安排」放最前面；切回按工號恢復原本順序
  function regroup() {
    tbody.querySelectorAll("tr.group-row").forEach((header) => header.remove());
    const byStation = document.getElementById("group-station").checked;
    const name = (row) => (select(row).value ? select(row).selectedOptions[0].text : "");
    const sorted = [...rows].sort((a, b) =>
      byStation ? name(a).localeCompare(name(b), "zh-Hant") || a.dataset.order - b.dataset.order : a.dataset.order - b.dataset.order
    );
    let current = null;
    sorted.forEach((row) => {
      row.dataset.group = byStation ? name(row) : "";
      if (byStation && row.dataset.group !== current) {
        current = row.dataset.group;
        const count = sorted.filter((r) => name(r) === current).length;
        const header = document.createElement("tr");
        header.className = "group-row table-light";
        header.dataset.group = current;
        header.innerHTML = `<td colspan="5" class="fw-bold"></td>`;
        header.firstChild.textContent = `${current || "未安排"}（${count} 人）`;
        tbody.appendChild(header);
      }
      tbody.appendChild(row);
    });
    filter();
  }

  checkAll.addEventListener("change", () => {
    rows.filter(visible).forEach((row) => { row.querySelector(".row-check").checked = checkAll.checked; });
    refreshCount();
  });
  tbody.addEventListener("change", (e) => { if (e.target.classList.contains("row-check")) refreshCount(); });
  applyButton.addEventListener("click", () => {
    const value = document.getElementById("bulk-station").value;
    checked().forEach((row) => { select(row).value = value; row.querySelector(".row-check").checked = false; });
    checkAll.checked = false;
    regroup();
  });
  document.querySelectorAll("input[name=group-mode]").forEach((radio) => radio.addEventListener("change", regroup));
  onlyUnassigned.addEventListener("change", filter);
  refreshCount();
})();
