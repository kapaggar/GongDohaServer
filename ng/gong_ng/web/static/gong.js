// Live clock in the header strip, driven by the server-reported time so the
// page shows the appliance's clock, not the phone's.
(function () {
  var el = document.getElementById("clock");
  if (!el) return;
  var offset = parseFloat(el.dataset.epoch) * 1000 - Date.now();
  var big = document.getElementById("bigtime");
  function tick() {
    var d = new Date(Date.now() + offset);
    var s = [d.getHours(), d.getMinutes(), d.getSeconds()]
      .map(function (n) { return String(n).padStart(2, "0"); }).join(":");
    el.textContent = s;
    if (big) big.textContent = s;
  }
  tick();
  setInterval(tick, 1000);
})();
