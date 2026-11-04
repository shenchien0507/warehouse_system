// 編號按 Enter 跳到員工編號（刷條碼槍會自動送 Enter），員工編號按 Enter 才送出；有錯時游標停在第一個錯的格子
(function () {
  var form = document.querySelector("[data-scan-form]");
  var number = form.querySelector("[data-scan=number]");
  var employee = form.querySelector("[data-scan=employee]");
  number.addEventListener("keydown", function (event) {
    if (event.key !== "Enter") { return; }
    event.preventDefault();
    if (number.value.trim()) { employee.focus(); employee.select(); }
  });
  employee.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !number.value.trim()) { event.preventDefault(); number.focus(); }
  });
  var invalid = form.querySelector(".is-invalid");
  if (invalid) { invalid.focus(); invalid.select(); }
})();
