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

    // 0/1 flag channels: an LED plus the time the flag last became 1.
    var FLAG_ON = 0.5;

    function formatTs(ts) {
      if (!ts) return null;
      // DB timestamps are "YYYY-MM-DD HH:MM:SS" in UTC with no tz marker; the
      // live socket sends ISO 8601 with an offset. Normalize both to a Date.
      var iso = ts.indexOf("T") === -1 ? ts.replace(" ", "T") + "Z" : ts;
      var d = new Date(iso);
      return isNaN(d.getTime()) ? ts : d.toLocaleString();
    }

    var flags = {};
    document.querySelectorAll("[data-flag-channel-id]").forEach(function (el) {
      var channelId = parseInt(el.getAttribute("data-flag-channel-id"), 10);
      var led = el.querySelector("[data-flag-led]");
      var stateEl = el.querySelector("[data-flag-state]");
      var lastEl = el.querySelector("[data-flag-last]");

      function render(value, lastOn) {
        var on = value != null && value >= FLAG_ON;
        led.classList.toggle("flag-on", on);
        stateEl.textContent = value == null ? "尚無資料" : on ? "觸發中" : "正常";
        var lt = formatTs(lastOn);
        lastEl.textContent = lt ? "上次觸發：" + lt : "尚無觸發記錄";
      }

      var entry = { render: render, lastOn: null };
      flags[channelId] = entry;

      fetch("/channels/" + channelId + "/flag")
        .then(function (r) { return r.json(); })
        .then(function (j) {
          entry.lastOn = j.last_on_at || null;
          render(j.value, entry.lastOn);
        })
        .catch(function (err) {
          console.warn("flag fetch failed for channel " + channelId, err);
        });

      sock.emit("subscribe_channel", { channel_id: channelId });
    });

    sock.on("reading", function (d) {
      var chart = charts[d.channel_id];
      if (chart) {
        chart.data.labels.push(d.timestamp);
        chart.data.datasets[0].data.push(d.value);
        if (chart.data.labels.length > 60) {
          chart.data.labels.shift();
          chart.data.datasets[0].data.shift();
        }
        chart.update();
      }
      var flag = flags[d.channel_id];
      if (flag) {
        if (d.value >= FLAG_ON) flag.lastOn = d.timestamp;
        flag.render(d.value, flag.lastOn);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
