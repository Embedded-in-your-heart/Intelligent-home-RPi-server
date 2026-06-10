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

    // Parse both DB ("YYYY-MM-DD HH:MM:SS" UTC, no tz marker) and live ISO 8601
    // (with offset) timestamps to epoch milliseconds.
    function tsToMs(ts) {
      if (!ts) return 0;
      var iso = ts.indexOf("T") === -1 ? ts.replace(" ", "T") + "Z" : ts;
      var d = new Date(iso);
      return isNaN(d.getTime()) ? 0 : d.getTime();
    }

    function formatTs(ts) {
      var ms = tsToMs(ts);
      return ms ? new Date(ms).toLocaleString() : (ts || null);
    }

    // Global observation window: how far back charts show. Buttons in
    // #window-selector switch it; the live feed trims to the same span.
    var WINDOW_MS = { "1m": 60e3, "10m": 600e3, "1h": 3600e3, "1d": 86400e3, "1w": 604800e3 };
    var windowSelector = document.getElementById("window-selector");
    var currentWindow = null;
    if (windowSelector) {
      var activeBtn = windowSelector.querySelector("[data-window].active");
      currentWindow = activeBtn ? activeBtn.getAttribute("data-window") : "1m";
    }

    var canvases = document.querySelectorAll("canvas[data-channel-id]");
    var charts = {};

    function loadChart(channelId) {
      var chart = charts[channelId];
      if (!chart) return;
      var url = "/channels/" + channelId + "/history";
      if (currentWindow) url += "?window=" + currentWindow;
      fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (j) {
          chart.data.labels = [];
          chart.data.datasets[0].data = [];
          j.readings.forEach(function (pt) {
            chart.data.labels.push(pt.recorded_at);
            chart.data.datasets[0].data.push(pt.value);
          });
          chart.update();
        })
        .catch(function (err) {
          console.warn("history fetch failed for channel " + channelId, err);
        });
    }

    canvases.forEach(function (canvas) {
      var channelId = parseInt(canvas.getAttribute("data-channel-id"), 10);
      var unit = canvas.getAttribute("data-unit") || "value";
      charts[channelId] = new Chart(canvas, {
        type: "line",
        data: { labels: [], datasets: [{ label: unit, data: [], tension: 0.3 }] },
        options: { animation: false, scales: { x: { display: false } } },
      });
      loadChart(channelId);
      sock.emit("subscribe_channel", { channel_id: channelId });
    });

    if (windowSelector) {
      windowSelector.querySelectorAll("[data-window]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          windowSelector.querySelectorAll("[data-window]").forEach(function (b) {
            b.classList.remove("active");
          });
          btn.classList.add("active");
          currentWindow = btn.getAttribute("data-window");
          Object.keys(charts).forEach(function (id) { loadChart(parseInt(id, 10)); });
        });
      });
    }

    // 0/1 flag channels: an LED plus the time the flag last became 1.
    var FLAG_ON = 0.5;

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
        if (currentWindow) {
          // Drop points that fell outside the selected observation window.
          var cutoff = Date.now() - WINDOW_MS[currentWindow];
          while (chart.data.labels.length && tsToMs(chart.data.labels[0]) < cutoff) {
            chart.data.labels.shift();
            chart.data.datasets[0].data.shift();
          }
        } else if (chart.data.labels.length > 60) {
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
