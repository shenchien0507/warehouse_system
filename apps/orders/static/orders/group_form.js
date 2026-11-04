// 切開時間有填才能勾「算進前」，沒填才能勾「一天一列」；不能勾的照原值送出，不會被改掉。
(function () {
  const cutoff = document.getElementById("id_cutoff");
  const withCutoff = [document.getElementById("id_carry_over")];
  const withoutCutoff = [document.getElementById("id_split_by_day")];

  function toggle() {
    const has = /\d/.test(cutoff.value);
    withCutoff.forEach((input) => setEnabled(input, has));
    withoutCutoff.forEach((input) => setEnabled(input, !has));
  }

  function setEnabled(input, enabled) {
    input.disabled = !enabled;
    input.closest(".wh-field").style.opacity = enabled ? "" : "0.5";
  }

  ["input", "keyup", "focusout"].forEach((type) => cutoff.addEventListener(type, toggle));
  cutoff.form.addEventListener("submit", () => {
    [...withCutoff, ...withoutCutoff].forEach((input) => { input.disabled = false; });
  });
  toggle();
})();

// 連動選單：依勾選的平台（和店鋪）只顯示來源檔裡有出現的店鋪、出貨類型
(function () {
  const combos = JSON.parse(document.getElementById("source-combos").textContent);  // [平台, 店鋪, 出貨類型]

  function checked(card, field) {
    return [...card.querySelectorAll(`[data-field="${field}"] input:checked`)].map((i) => i.value);
  }

  const known = {shops: new Set(combos.map((c) => c[1])), ship_types: new Set(combos.map((c) => c[2]))};

  function show(card, field, allowed, uncheckHidden) {
    const box = card.querySelector(`[data-field="${field}"]`);
    let visible = 0;
    box.querySelectorAll(".form-check").forEach((row) => {
      const input = row.querySelector("input");
      const ok = allowed.has(row.dataset.value) || !known[field].has(row.dataset.value);  // 來源檔沒有的舊值照原樣保留
      if (!ok && uncheckHidden) input.checked = false;
      row.hidden = !ok && !input.checked;
      if (!row.hidden) visible += 1;
    });
    box.querySelector(".none-left").hidden = visible > 0;
  }

  function update(card, uncheckHidden) {
    const platforms = checked(card, "platforms");
    const byPlatform = combos.filter((c) => !platforms.length || platforms.includes(c[0]));
    show(card, "shops", new Set(byPlatform.map((c) => c[1])), uncheckHidden);
    const shops = checked(card, "shops");
    const byShop = byPlatform.filter((c) => !shops.length || shops.includes(c[1]));
    show(card, "ship_types", new Set(byShop.map((c) => c[2])), uncheckHidden);
  }

  function init(card) {
    update(card, false);  // 剛打開時不取消已存的勾選
    card.addEventListener("change", (event) => {
      if (event.target.closest('[data-field="platforms"], [data-field="shops"]')) update(card, true);
    });
  }

  document.querySelectorAll("#condition-list [data-condition]").forEach(init);

  // 新增一組空白條件：複製 formset 的 empty_form，換上新的序號
  document.getElementById("add-condition").addEventListener("click", () => {
    const total = document.getElementById("id_conditions-TOTAL_FORMS");
    const index = Number(total.value);
    const html = document.getElementById("empty-condition").innerHTML
      .replace(/__prefix__/g, index).replace(/__number__/g, index + 1);
    const list = document.getElementById("condition-list");
    list.insertAdjacentHTML("beforeend", html);
    total.value = index + 1;
    init(list.lastElementChild);
  });
})();
