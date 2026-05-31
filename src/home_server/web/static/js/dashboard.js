(function () {
  function init() {
    var sock = io();

    sock.on("device_status", function (d) {
      var cls = { connected: "bg-success", reconnecting: "bg-warning", disconnected: "bg-secondary" }[d.status] || "bg-secondary";
      document.querySelectorAll('[data-device-id="' + d.device_id + '"]').forEach(function (b) {
        b.textContent = d.status;
        b.className = "badge " + cls;
      });
    });

    var canvases = document.querySelectorAll("canvas[data-channel-id]");
    var charts = {};
    canvases.forEach(function (canvas) {
      var channelId = parseInt(canvas.getAttribute("data-channel-id"), 10);
      var unit = canvas.getAttribute("data-unit") || "value";
      var chart = new Chart(canvas, {
        type: "line",
        data: { labels: [], datasets: [{ label: unit, data: [], tension: 0.3 }] },
        options: { animation: false, scales: { x: { display: false } } },
      });
      charts[channelId] = chart;

      fetch("/channels/" + channelId + "/history")
        .then(function (r) { return r.json(); })
        .then(function (j) {
          j.readings.forEach(function (pt) {
            chart.data.labels.push(pt.recorded_at);
            chart.data.datasets[0].data.push(pt.value);
          });
          chart.update();
        })
        .catch(function (err) {
          console.warn("history fetch failed for channel " + channelId, err);
        });

      sock.emit("subscribe_channel", { channel_id: channelId });
    });

    sock.on("reading", function (d) {
      var chart = charts[d.channel_id];
      if (!chart) return;
      chart.data.labels.push(d.timestamp);
      chart.data.datasets[0].data.push(d.value);
      if (chart.data.labels.length > 60) {
        chart.data.labels.shift();
        chart.data.datasets[0].data.shift();
      }
      chart.update();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
