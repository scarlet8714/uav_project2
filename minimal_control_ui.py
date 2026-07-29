"""Shared browser camera-control panel for the minimal stream demos."""


def build_page(
    title,
    media_html,
    connection_script="",
    source_options=(
        ("v4l2", "V4L2"),
        ("tiscamera", "tiscamera / tcambin"),
    ),
):
    source_html = "".join(
        f'<option value="{value}">{label}</option>'
        for value, label in source_options
    )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ margin: 0; background: #202124; color: #eee; font-family: sans-serif; }}
    main {{ width: min(96%, 1280px); margin: 20px auto; }}
    h1 {{ text-align: center; }}
    video, img {{ width: 100%; background: #000; border: 1px solid #666; }}
    .control-drawer {{
      position: fixed;
      top: 0;
      right: 0;
      z-index: 10;
      width: min(380px, calc(100vw - 48px));
      height: 100vh;
      transition: transform .25s ease;
    }}
    .control-drawer.closed {{ transform: translateX(100%); }}
    .drawer-toggle {{
      position: absolute;
      top: 18px;
      left: -44px;
      width: 44px;
      height: 48px;
      padding: 0;
      border: 0;
      border-radius: 8px 0 0 8px;
      background: #303134;
      color: #fff;
      font-size: 24px;
      cursor: pointer;
    }}
    .panel {{
      box-sizing: border-box;
      height: 100%;
      padding: 16px;
      overflow-y: auto;
      background: #303134;
      opacity: .6;
      box-shadow: -4px 0 14px #0008;
    }}
    .row {{
      display: grid;
      grid-template-columns: minmax(82px, 112px) minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      margin: 9px 0;
    }}
    .row label {{
      min-width: 0;
      overflow-wrap: anywhere;
      line-height: 1.25;
    }}
    input, select, button {{
      box-sizing: border-box;
      min-width: 0;
      max-width: 100%;
      padding: 7px;
      font: inherit;
    }}
    .row input, .row select {{ width: 100%; }}
    .row-actions {{
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 5px;
    }}
    .row-actions button {{ padding-inline: 7px; }}
    button {{ cursor: pointer; }}
    #message {{ min-height: 1.5em; color: #9ad0ff; }}
    .unsupported {{ opacity: .55; }}
    @media (max-width: 520px) {{
      .row {{ grid-template-columns: minmax(0, 1fr) auto; }}
      .row label {{ grid-column: 1 / -1; }}
    }}
  </style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <div id="connection-status"></div>
  {media_html}
  <aside id="control-drawer" class="control-drawer closed">
    <button id="drawer-toggle" class="drawer-toggle"
      onclick="toggleControls()" aria-label="顯示相機控制"
      aria-expanded="false">‹</button>
    <section class="panel">
    <h2>相機控制</h2>
    <div class="row"><label for="source">來源</label>
      <select id="source">{source_html}</select>
      <button onclick="applyControl('source')">套用</button></div>
    <div class="row"><label for="resolution">解析度</label>
      <select id="resolution">
        <option>4128x3096</option><option>1920x1080</option>
        <option>1600x1200</option>
        <option>1280x960</option><option>1280x720</option>
        <option>800x480</option><option>640x480</option>
      </select><span class="row-actions">
        <button onclick="fillDefault('resolution', '1920x1080')">預設</button>
        <button onclick="applyControl('resolution')">套用</button>
      </span></div>
    <div class="row"><label for="fps">FPS</label>
      <select id="fps"><option>30</option><option>25</option><option>20</option>
      <option>15</option><option>10</option><option>5</option>
      <option>1</option></select>
      <span class="row-actions">
        <button id="fps-default" onclick="fillDefault('fps', '30')">預設</button>
        <button id="fps-apply" onclick="applyControl('fps')">套用</button>
      </span></div>
    <div class="row" id="row-exposure"><label for="exposure">曝光時間 (µs)</label>
      <input id="exposure" type="number" min="200" max="1000000" step="1">
      <span class="row-actions">
        <button onclick="fillDefault('exposure', '33333')">預設</button>
        <button onclick="applyControl('exposure')">套用</button>
      </span></div>
    <div class="row" id="row-brightness"><label for="brightness">亮度</label>
      <input id="brightness" type="number" step="1">
      <span class="row-actions">
        <button onclick="fillDefault('brightness', '0')">預設</button>
        <button onclick="applyControl('brightness')">套用</button>
      </span></div>
    <div class="row" id="row-contrast"><label for="contrast">對比</label>
      <input id="contrast" type="number" step="1">
      <span class="row-actions">
        <button onclick="fillDefault('contrast', '64')">預設</button>
        <button onclick="applyControl('contrast')">套用</button>
      </span></div>
    <div class="row" id="row-saturation"><label for="saturation">飽和度</label>
      <input id="saturation" type="number" step="1">
      <span class="row-actions">
        <button onclick="fillDefault('saturation', '32')">預設</button>
        <button onclick="applyControl('saturation')">套用</button>
      </span></div>
    <div class="row" id="row-gain"><label for="gain">增益</label>
      <input id="gain" type="number" step="1">
      <span class="row-actions">
        <button onclick="fillDefault('gain', '100')">預設</button>
        <button onclick="applyControl('gain')">套用</button>
      </span></div>
    <div class="row" id="row-sharpness"><label for="sharpness">銳利度</label>
      <input id="sharpness" type="number" step="1">
      <span class="row-actions">
        <button onclick="fillDefault('sharpness', '8')">預設</button>
        <button onclick="applyControl('sharpness')">套用</button>
      </span></div>
    <div class="row" id="row-focus-one-push">
      <label>One Push Focus</label><span>單次自動對焦</span>
      <button id="focus-one-push"
        onclick="applyAction('focus_one_push')">觸發</button></div>
      <div id="message"></div>
    </section>
  </aside>
</main>
<script>
{connection_script}
const controlNames = [
  "exposure", "brightness", "contrast", "saturation", "gain", "sharpness"
];

function toggleControls() {{
  const drawer = document.getElementById("control-drawer");
  const button = document.getElementById("drawer-toggle");
  const closed = drawer.classList.toggle("closed");
  button.textContent = closed ? "‹" : "›";
  button.setAttribute("aria-expanded", String(!closed));
  button.setAttribute(
    "aria-label",
    closed ? "顯示相機控制" : "隱藏相機控制"
  );
}}

function syncFpsForResolution() {{
  const resolution = document.getElementById("resolution");
  const fps = document.getElementById("fps");
  const highResolution = resolution.value === "4128x3096";
  if (highResolution) fps.value = "1";
  fps.disabled = highResolution;
  document.getElementById("fps-default").disabled = highResolution;
  document.getElementById("fps-apply").disabled = highResolution;
}}

function fillDefault(name, value) {{
  document.getElementById(name).value = value;
  if (name === "resolution") syncFpsForResolution();
  document.getElementById("message").textContent =
    `已填入 ${{name}} 預設值；尚未套用`;
}}

function showStatus(data) {{
  document.getElementById("source").value = data.source;
  document.getElementById("resolution").value = data.resolution;
  document.getElementById("fps").value = String(data.fps);
  syncFpsForResolution();
  for (const name of controlNames) {{
    const info = data.controls[name];
    const row = document.getElementById("row-" + name);
    row.classList.toggle("unsupported", !info.supported);
    row.title = info.supported ? "" : info.error;
    if (info.supported) document.getElementById(name).value = info.value;
  }}
  const focusInfo = data.actions.focus_one_push;
  const focusRow = document.getElementById("row-focus-one-push");
  const focusButton = document.getElementById("focus-one-push");
  focusRow.classList.toggle("unsupported", !focusInfo.supported);
  focusButton.disabled = !focusInfo.supported;
}}

async function refreshControls() {{
  const response = await fetch("/api/camera");
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "無法取得相機狀態");
  showStatus(data);
}}

async function applyControl(name) {{
  const message = document.getElementById("message");
  message.textContent = "套用中…";
  try {{
    const element = document.getElementById(name);
    const response = await fetch("/api/camera/control", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ name, value: element.value }})
    }});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "套用失敗");
    if (data.controls) showStatus(data);
    message.textContent = data.actual === undefined
      ? "已套用 " + name
      : `已套用 ${{name}}：要求 ${{data.requested}}，讀回 ${{data.actual}}`;
    await refreshControls();
  }} catch (error) {{
    message.textContent = "錯誤：" + error.message;
  }}
}}

async function applyAction(name) {{
  const message = document.getElementById("message");
  message.textContent = "觸發中…";
  try {{
    const response = await fetch("/api/camera/control", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ name, value: true }})
    }});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "觸發失敗");
    message.textContent = data.triggered
      ? "One Push Focus 已觸發"
      : "One Push Focus 未觸發";
  }} catch (error) {{
    message.textContent = "錯誤：" + error.message;
  }}
}}

refreshControls().catch(error => {{
  document.getElementById("message").textContent = "錯誤：" + error.message;
}});
document.getElementById("resolution").addEventListener(
  "change", syncFpsForResolution
);
</script>
</body>
</html>"""
