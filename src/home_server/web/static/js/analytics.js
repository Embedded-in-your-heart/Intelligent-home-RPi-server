(function () {
  function init() {
    var sock = io();

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

    function escapeHtml(s) {
      var d = document.createElement("div");
      d.textContent = s == null ? "" : String(s);
      return d.innerHTML;
    }

    // Pop a transient Bootstrap toast in the top-right. Used to alert the user
    // the moment a 0/1 flag channel rises to 1 (triggered).
    function showToast(title, ts) {
      var container = document.getElementById("toast-container");
      if (!container || typeof bootstrap === "undefined") return;
      var el = document.createElement("div");
      el.className = "toast align-items-center text-bg-danger border-0";
      el.setAttribute("role", "alert");
      el.setAttribute("aria-live", "assertive");
      el.setAttribute("aria-atomic", "true");
      var when = formatTs(ts);
      el.innerHTML =
        '<div class="d-flex">' +
        '<div class="toast-body">⚠️ ' + escapeHtml(title) + " 觸發！" +
        (when ? '<div class="small text-white-50">' + escapeHtml(when) + "</div>" : "") +
        "</div>" +
        '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>' +
        "</div>";
      container.appendChild(el);
      var toast = new bootstrap.Toast(el, { delay: 5000 });
      el.addEventListener("hidden.bs.toast", function () { el.remove(); });
      toast.show();
    }

    // Global observation window: how far back charts show. Buttons in
    // #window-selector switch it; the live feed trims to the same span.
    var WINDOW_MS = { "1m": 60e3, "10m": 600e3, "1h": 3600e3, "1d": 86400e3, "1w": 604800e3 };
    var FLAG_ON = 0.5;

    var windowSelector = document.getElementById("window-selector");
    var currentWindow = null;
    if (windowSelector) {
      var activeBtn = windowSelector.querySelector("[data-window].active");
      currentWindow = activeBtn ? activeBtn.getAttribute("data-window") : "1m";
    }

    // Merged numeric charts: one chart per sensor type, multiple datasets per device.
    var mergedCharts = document.querySelectorAll("canvas[data-merged-chart]");
    var charts = {};  // keyed by chart canvas element
    var bySub = {};   // keyed by channelId: { chart, datasetIndex, deviceName }

    // Pin the linear x-axis to the actual data extent (across all datasets).
    // Without this, Chart.js rounds the axis out to "nice" tick boundaries,
    // leaving the line squeezed in the middle with blank margins on both
    // sides. Fitting min/max to the data fills the width: the full window when
    // readings are plentiful, a tight fit when they are sparse.
    function fitXRange(chart) {
      var minX = Infinity;
      var maxX = -Infinity;
      chart.data.datasets.forEach(function (ds) {
        ds.data.forEach(function (pt) {
          if (pt.x < minX) minX = pt.x;
          if (pt.x > maxX) maxX = pt.x;
        });
      });
      if (minX <= maxX) {
        chart.options.scales.x.min = minX;
        chart.options.scales.x.max = maxX;
      } else {
        // No points yet: let Chart.js auto-range.
        chart.options.scales.x.min = undefined;
        chart.options.scales.x.max = undefined;
      }
    }

    function loadChart(channelId) {
      var sub = bySub[channelId];
      if (!sub) return;
      var chart = sub.chart;
      var url = "/channels/" + channelId + "/history";
      if (currentWindow) url += "?window=" + currentWindow;
      fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (j) {
          var data = [];
          j.readings.forEach(function (pt) {
            data.push({ x: tsToMs(pt.recorded_at), y: pt.value });
          });
          // Sort by x ascending to ensure correct left-to-right ordering
          data.sort(function (a, b) { return a.x - b.x; });
          chart.data.datasets[sub.datasetIndex].data = data;
          fitXRange(chart);
          chart.update();
        })
        .catch(function (err) {
          console.warn("history fetch failed for channel " + channelId, err);
        });
    }

    mergedCharts.forEach(function (canvas) {
      var channelsJson = canvas.getAttribute("data-channels");
      var unit = canvas.getAttribute("data-unit") || "value";
      var channels = [];
      try {
        channels = JSON.parse(channelsJson || "[]");
      } catch (e) {
        console.warn("failed to parse data-channels JSON", e);
      }

      // Create one dataset per device
      var datasets = [];
      var chartMap = {};  // channelId -> datasetIndex
      channels.forEach(function (ch, idx) {
        datasets.push({
          label: ch.deviceName,
          data: [],
          tension: 0.3
        });
        chartMap[ch.channelId] = idx;
      });

      var chart = new Chart(canvas, {
        type: "line",
        data: { datasets: datasets },
        options: {
          animation: false,
          scales: {
            x: {
              type: "linear",
              ticks: {
                callback: function (v) {
                  return new Date(v).toLocaleTimeString();
                },
                maxTicksLimit: 6
              }
            },
            y: {
              title: unit ? { display: true, text: unit } : undefined
            }
          }
        }
      });

      charts[canvas] = chart;

      // Load and subscribe to each channel in this merged chart
      channels.forEach(function (ch) {
        bySub[ch.channelId] = {
          chart: chart,
          datasetIndex: chartMap[ch.channelId],
          deviceName: ch.deviceName
        };
        loadChart(ch.channelId);
        sock.emit("subscribe_channel", { channel_id: ch.channelId });
      });
    });

    // Window selector: switch observation window and reload all charts
    if (windowSelector) {
      windowSelector.querySelectorAll("[data-window]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          windowSelector.querySelectorAll("[data-window]").forEach(function (b) {
            b.classList.remove("active");
          });
          btn.classList.add("active");
          currentWindow = btn.getAttribute("data-window");
          Object.keys(bySub).forEach(function (id) {
            loadChart(parseInt(id, 10));
          });
        });
      });
    }

    // 0/1 flag channels: an LED plus the time the flag last became 1.
    var flags = {};
    document.querySelectorAll("[data-mflag-channel-id]").forEach(function (el) {
      var channelId = parseInt(el.getAttribute("data-mflag-channel-id"), 10);
      var led = el.querySelector("[data-mflag-led]");
      var stateEl = el.querySelector("[data-mflag-state]");
      var lastEl = el.querySelector("[data-mflag-last]");
      var name = el.getAttribute("data-mflag-name") || "警示";
      var deviceName = el.getAttribute("data-device-name") || "未知";

      function render(value, lastOn) {
        var on = value != null && value >= FLAG_ON;
        led.classList.toggle("flag-on", on);
        stateEl.textContent = value == null ? "尚無資料" : on ? "觸發中" : "正常";
        var lt = formatTs(lastOn);
        lastEl.textContent = lt ? "上次觸發：" + lt : "尚無觸發記錄";
      }

      var entry = {
        render: render,
        lastOn: null,
        on: false,
        name: name,
        deviceName: deviceName
      };
      flags[channelId] = entry;

      fetch("/channels/" + channelId + "/flag")
        .then(function (r) { return r.json(); })
        .then(function (j) {
          entry.lastOn = j.last_on_at || null;
          entry.on = j.value != null && j.value >= FLAG_ON;
          render(j.value, entry.lastOn);
        })
        .catch(function (err) {
          console.warn("flag fetch failed for channel " + channelId, err);
        });

      sock.emit("subscribe_channel", { channel_id: channelId });
    });

    // Live reading updates from socket
    sock.on("reading", function (d) {
      // Update merged numeric charts
      var sub = bySub[d.channel_id];
      if (sub) {
        var chart = sub.chart;
        var data = chart.data.datasets[sub.datasetIndex].data;
        var point = { x: tsToMs(d.timestamp), y: d.value };
        // Live timestamps have 1-second resolution but readings arrive
        // unthrottled (several per second). On the linear time axis, multiple
        // points sharing the same x draw as vertical zig-zags. Collapse same-
        // second readings to one point (keep latest) to match the per-second
        // resolution of the downsampled history.
        var last = data[data.length - 1];
        if (last && last.x === point.x) {
          last.y = point.y;
        } else {
          data.push(point);
        }

        if (currentWindow) {
          // Drop points that fell outside the selected observation window.
          var cutoff = Date.now() - WINDOW_MS[currentWindow];
          while (data.length && data[0].x < cutoff) {
            data.shift();
          }
        } else if (data.length > 60) {
          data.shift();
        }
        fitXRange(chart);
        chart.update();
      }

      // Update flags
      var flag = flags[d.channel_id];
      if (flag) {
        var nowOn = d.value >= FLAG_ON;
        // Only toast on the rising edge (0 -> 1), not on every "still on" reading.
        if (nowOn && !flag.on) {
          showToast(flag.name + "（" + flag.deviceName + "）", d.timestamp);
        }
        flag.on = nowOn;
        if (nowOn) flag.lastOn = d.timestamp;
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
