document.getElementById("check-all")?.addEventListener("change", (e) => {
  document.querySelectorAll(".row-check").forEach((box) => { box.checked = e.target.checked; });
});
