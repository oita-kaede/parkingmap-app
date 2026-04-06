import streamlit as st
import streamlit.components.v1 as components
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
from streamlit_image_coordinates import streamlit_image_coordinates
import io
import base64
import json

st.set_page_config(page_title="駐車場マップ作成ツール", layout="wide", page_icon="🅿️")


# =============================================================
# ユーティリティ関数
# =============================================================

def pil_to_base64(pil_image, fmt="PNG", quality=85):
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        pil_image.save(buf, format="JPEG", quality=quality, optimize=True)
    else:
        pil_image.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/{fmt.lower()};base64,{b64}"


def draw_yellow_label(image, target_x, target_y, label_text, font_size=36):
    draw = ImageDraw.Draw(image)
    padding_x, padding_y = 12, 8
    try:
        font = ImageFont.truetype("ipaexg.ttf", font_size)
    except:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label_text, font=font)
    w = (bbox[2] - bbox[0]) + padding_x * 2
    h = (bbox[3] - bbox[1]) + padding_y * 2

    label_y = target_y - h - 30
    if label_y < 10:
        label_y = target_y + 30

    rect_left = target_x - (w / 2)
    rect_top = label_y
    rect_right = rect_left + w
    rect_bottom = rect_top + h

    label_center_x = rect_left + w / 2
    label_bottom_y = rect_bottom
    draw.line([(label_center_x, label_bottom_y), (target_x, target_y)], fill="#FFD600", width=3)
    draw.rectangle((rect_left, rect_top, rect_right, rect_bottom), fill="#FFEB3B", outline="#F9A825", width=2)
    text_x = rect_left + padding_x
    text_y = rect_top + padding_y - bbox[1]
    draw.text((text_x, text_y), label_text, font=font, fill="black")

    pin_r = 6
    draw.ellipse((target_x - pin_r, target_y - pin_r, target_x + pin_r, target_y + pin_r), fill="red", outline="darkred", width=2)
    return image


def wrap_text_to_box(text, font, max_width, draw):
    wrapped_lines = []
    for line in text.strip().split('\n'):
        if not line:
            wrapped_lines.append('')
            continue
        current = ''
        for char in line:
            test = current + char
            bb = draw.textbbox((0, 0), test, font=font)
            if (bb[2] - bb[0]) > max_width:
                if current:
                    wrapped_lines.append(current)
                current = char
            else:
                current = test
        if current:
            wrapped_lines.append(current)
    return wrapped_lines


def calc_text_height(lines, font, draw, line_spacing=6):
    total = 0
    for line in lines:
        if not line:
            total += line_spacing
            continue
        bb = draw.textbbox((0, 0), line, font=font)
        total += (bb[3] - bb[1]) + line_spacing
    return total


def draw_info_box(image, info_text, box_x, box_y, box_w, box_h, font_size=14):
    draw = ImageDraw.Draw(image)
    padding = 8
    inner_w = box_w - padding * 2
    inner_h = box_h - padding * 2
    line_spacing = 5

    for fs in range(font_size, 7, -1):
        try:
            font = ImageFont.truetype("ipaexg.ttf", fs)
        except:
            font = ImageFont.load_default()
            break
        wrapped = wrap_text_to_box(info_text, font, inner_w, draw)
        total_h = calc_text_height(wrapped, font, draw, line_spacing)
        if total_h <= inner_h:
            break
    else:
        try:
            font = ImageFont.truetype("ipaexg.ttf", 8)
        except:
            font = ImageFont.load_default()
        wrapped = wrap_text_to_box(info_text, font, inner_w, draw)

    overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        (box_x, box_y, box_x + box_w, box_y + box_h),
        radius=8, fill=(255, 255, 255, 230), outline=(200, 200, 200, 255), width=1
    )
    image = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')

    draw = ImageDraw.Draw(image)
    current_y = box_y + padding
    for line in wrapped:
        if not line:
            current_y += line_spacing
            continue
        bb = draw.textbbox((0, 0), line, font=font)
        line_h = bb[3] - bb[1]
        if current_y + line_h > box_y + box_h - padding:
            break
        draw.text((box_x + padding, current_y - bb[1]), line, font=font, fill="black")
        current_y += line_h + line_spacing

    return image


def overlay_layout_image(base_image, layout_pil, lx, ly, lw, lh):
    resized = layout_pil.resize((max(1, lw), max(1, lh)), Image.Resampling.LANCZOS)
    border = 3
    bordered = Image.new('RGB', (resized.width + border * 2, resized.height + border * 2), 'white')
    bordered.paste(resized, (border, border))
    px = max(0, min(lx, base_image.width - bordered.width))
    py = max(0, min(ly, base_image.height - bordered.height))
    base_image.paste(bordered, (px, py))
    return base_image


def build_drag_editor_html(bg_b64, overlays_json, canvas_w, canvas_h):
    """ドラッグエディターHTML — 確定ボタンでCanvas描画→ブラウザダウンロード"""
    return f'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, 'Segoe UI', 'Hiragino Sans', sans-serif; background: transparent; }}
  .editor-wrap {{ position: relative; display: inline-block; }}
  .editor-wrap img {{ display: block; width: {canvas_w}px; height: {canvas_h}px; }}
  .overlay {{
    position: absolute; cursor: move;
    border: 2px solid transparent; border-radius: 4px;
    z-index: 20; transition: border-color 0.1s; user-select: none;
  }}
  .overlay:hover, .overlay.active {{
    border-color: #FF6D00;
    box-shadow: 0 0 0 1px rgba(255,109,0,0.3);
  }}
  .overlay .rh {{
    position: absolute; width: 10px; height: 10px;
    background: #FF6D00; border: 1.5px solid white;
    border-radius: 2px; display: none; z-index: 30;
  }}
  .overlay:hover .rh, .overlay.active .rh {{ display: block; }}
  .rh.tl {{ top: -5px; left: -5px; cursor: nw-resize; }}
  .rh.tr {{ top: -5px; right: -5px; cursor: ne-resize; }}
  .rh.bl {{ bottom: -5px; left: -5px; cursor: sw-resize; }}
  .rh.br {{ bottom: -5px; right: -5px; cursor: se-resize; }}
  .label-inner {{
    background: #FFEB3B; border: 2px solid #F9A825; border-radius: 4px;
    font-weight: bold; text-align: center; white-space: nowrap;
    width: 100%; height: 100%; display: flex;
    align-items: center; justify-content: center;
    overflow: hidden; font-size: 15px;
  }}
  .pin-marker {{
    position: absolute; bottom: -16px; left: 50%;
    transform: translateX(-50%); pointer-events: none;
    display: flex; flex-direction: column; align-items: center;
  }}
  .pin-marker .pin-line {{ width: 2px; height: 10px; background: #FFD600; }}
  .pin-marker .pin-dot {{ width: 10px; height: 10px; background: red; border: 2px solid darkred; border-radius: 50%; }}
  .info-inner {{
    background: rgba(255,255,255,0.92); border: 1px solid #ccc;
    border-radius: 8px; padding: 8px 10px; font-size: 11px;
    line-height: 1.5; width: 100%; height: 100%;
    overflow: hidden; white-space: pre-line; word-break: break-all;
  }}
  .layout-inner {{
    width: 100%; height: 100%; background: white;
    border: 3px solid white; box-shadow: 0 2px 6px rgba(0,0,0,0.2);
    border-radius: 4px; overflow: hidden;
  }}
  .layout-inner img {{ width: 100%; height: 100%; object-fit: cover; }}
  .help-badge {{
    position: absolute; top: 6px; left: 50%;
    transform: translateX(-50%); background: rgba(0,0,0,0.6);
    color: white; font-size: 11px; padding: 4px 12px;
    border-radius: 12px; z-index: 50; pointer-events: none;
  }}
  .confirm-bar {{ margin-top: 8px; text-align: center; }}
  .confirm-btn {{
    background: #FF6D00; color: white; border: none;
    padding: 10px 40px; border-radius: 8px;
    font-size: 15px; font-weight: bold; cursor: pointer;
  }}
  .confirm-btn:hover {{ background: #E65100; }}
  .confirm-btn:disabled {{ background: #ccc; cursor: wait; }}
  .done-msg {{
    margin-top: 10px; padding: 10px 20px;
    background: #E8F5E9; border: 1px solid #81C784;
    border-radius: 8px; color: #2E7D32; font-weight: bold;
    text-align: center; display: none;
  }}
</style>
</head>
<body>
<div class="editor-wrap" id="editor-wrap">
  <img id="bg-image" src="{bg_b64}" />
  <div class="help-badge">ドラッグで移動 ／ 四隅■でリサイズ</div>
</div>
<div class="confirm-bar">
  <button class="confirm-btn" id="confirm-btn">✅ この配置で確定してダウンロード</button>
</div>
<div class="done-msg" id="done-msg">✅ ダウンロード完了！</div>
<canvas id="render-canvas" style="display:none;"></canvas>
<script>
(function() {{
  var wrap = document.getElementById('editor-wrap');
  var bgImg = document.getElementById('bg-image');
  var confirmBtn = document.getElementById('confirm-btn');
  var doneMsg = document.getElementById('done-msg');
  var canvas = document.getElementById('render-canvas');
  var overlayData = {overlays_json};
  var CANVAS_W = {canvas_w};
  var CANVAS_H = {canvas_h};
  var activeEl = null;
  var mode = null;
  var resizeDir = '';
  var startX, startY, startLeft, startTop, startW, startH;

  function createOverlayEl(ov) {{
    var el = document.createElement('div');
    el.className = 'overlay';
    el.id = ov.id;
    el.style.left = ov.x + 'px';
    el.style.top = ov.y + 'px';
    el.style.width = ov.w + 'px';
    el.style.height = ov.h + 'px';
    ['tl','tr','bl','br'].forEach(function(dir) {{
      var rh = document.createElement('div');
      rh.className = 'rh ' + dir;
      rh.dataset.dir = dir;
      el.appendChild(rh);
    }});
    if (ov.type === 'label') {{
      var inner = document.createElement('div');
      inner.className = 'label-inner';
      inner.textContent = ov.text || '';
      el.appendChild(inner);
      var marker = document.createElement('div');
      marker.className = 'pin-marker';
      marker.innerHTML = '<div class="pin-line"></div><div class="pin-dot"></div>';
      el.appendChild(marker);
    }} else if (ov.type === 'info') {{
      var inner2 = document.createElement('div');
      inner2.className = 'info-inner';
      inner2.textContent = ov.text || '';
      el.appendChild(inner2);
    }} else if (ov.type === 'layout') {{
      var inner3 = document.createElement('div');
      inner3.className = 'layout-inner';
      if (ov.image_base64) {{
        var img = document.createElement('img');
        img.src = ov.image_base64;
        inner3.appendChild(img);
      }}
      el.appendChild(inner3);
    }}
    el.addEventListener('mousedown', function(e) {{
      if (e.target.classList.contains('rh')) return;
      e.preventDefault();
      setActive(el);
      mode = 'drag';
      startX = e.clientX; startY = e.clientY;
      startLeft = el.offsetLeft; startTop = el.offsetTop;
    }});
    el.querySelectorAll('.rh').forEach(function(rh) {{
      rh.addEventListener('mousedown', function(e) {{
        e.preventDefault(); e.stopPropagation();
        setActive(el);
        mode = 'resize';
        resizeDir = rh.dataset.dir;
        startX = e.clientX; startY = e.clientY;
        startLeft = el.offsetLeft; startTop = el.offsetTop;
        startW = el.offsetWidth; startH = el.offsetHeight;
      }});
    }});
    return el;
  }}

  function setActive(el) {{
    document.querySelectorAll('.overlay').forEach(function(o) {{ o.classList.remove('active'); }});
    if (el) el.classList.add('active');
    activeEl = el;
  }}

  document.addEventListener('mousemove', function(e) {{
    if (!activeEl) return;
    e.preventDefault();
    var dx = e.clientX - startX;
    var dy = e.clientY - startY;
    var maxW = bgImg.offsetWidth;
    var maxH = bgImg.offsetHeight;
    if (mode === 'drag') {{
      var nl = Math.max(0, Math.min(startLeft + dx, maxW - activeEl.offsetWidth));
      var nt = Math.max(0, Math.min(startTop + dy, maxH - activeEl.offsetHeight));
      activeEl.style.left = nl + 'px';
      activeEl.style.top = nt + 'px';
    }} else if (mode === 'resize') {{
      var nw = startW, nh = startH, nl2 = startLeft, nt2 = startTop;
      var minW = 40, minH = 20;
      if (resizeDir.includes('r')) nw = Math.max(minW, startW + dx);
      if (resizeDir.includes('l')) {{ nw = Math.max(minW, startW - dx); nl2 = startLeft + (startW - nw); }}
      if (resizeDir.includes('b')) nh = Math.max(minH, startH + dy);
      if (resizeDir.includes('t')) {{ nh = Math.max(minH, startH - dy); nt2 = startTop + (startH - nh); }}
      activeEl.style.width = nw + 'px';
      activeEl.style.height = nh + 'px';
      activeEl.style.left = nl2 + 'px';
      activeEl.style.top = nt2 + 'px';
      var labelInner = activeEl.querySelector('.label-inner');
      if (labelInner) {{
        var fontSize = Math.max(10, Math.min(48, nh * 0.55));
        labelInner.style.fontSize = fontSize + 'px';
      }}
      var infoInner = activeEl.querySelector('.info-inner');
      if (infoInner) {{
        var infoFs = Math.max(8, Math.min(18, Math.min(nh * 0.09, nw * 0.05)));
        infoInner.style.fontSize = infoFs + 'px';
        infoInner.style.lineHeight = (infoFs * 1.5) + 'px';
      }}
    }}
  }});

  document.addEventListener('mouseup', function() {{ mode = null; }});

  overlayData.forEach(function(ov) {{
    wrap.appendChild(createOverlayEl(ov));
  }});

  /* ===== Canvas描画で最終画像を生成 → ダウンロード ===== */
  confirmBtn.addEventListener('click', function() {{
    confirmBtn.disabled = true;
    confirmBtn.textContent = '画像を生成中...';

    canvas.width = CANVAS_W;
    canvas.height = CANVAS_H;
    var ctx = canvas.getContext('2d');

    // 1) 背景画像を描画
    ctx.drawImage(bgImg, 0, 0, CANVAS_W, CANVAS_H);

    // 2) 各オーバーレイの現在位置を取得して描画
    var loadPromises = [];

    overlayData.forEach(function(ov) {{
      var el = document.getElementById(ov.id);
      if (!el) return;
      var x = el.offsetLeft;
      var y = el.offsetTop;
      var w = el.offsetWidth;
      var h = el.offsetHeight;

      if (ov.type === 'layout' && ov.image_base64) {{
        // 配置図：白枠 + 画像
        var p = new Promise(function(resolve) {{
          var layoutImg = new window.Image();
          layoutImg.onload = function() {{
            ctx.fillStyle = 'white';
            ctx.fillRect(x - 3, y - 3, w + 6, h + 6);
            ctx.drawImage(layoutImg, x, y, w, h);
            resolve();
          }};
          layoutImg.onerror = function() {{ resolve(); }};
          layoutImg.src = ov.image_base64;
        }});
        loadPromises.push(p);
      }}

      if (ov.type === 'label') {{
        // 黄色ラベル＋ピン
        var pinX = x + w / 2;
        var pinY = y + h + 16;

        // ピンの線
        ctx.strokeStyle = '#FFD600';
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(pinX, y + h);
        ctx.lineTo(pinX, pinY);
        ctx.stroke();

        // 黄色ラベル背景
        ctx.fillStyle = '#FFEB3B';
        ctx.fillRect(x, y, w, h);
        ctx.strokeStyle = '#F9A825';
        ctx.lineWidth = 2;
        ctx.strokeRect(x, y, w, h);

        // ラベルテキスト
        var fontSize = Math.max(10, Math.min(48, h * 0.55));
        ctx.fillStyle = 'black';
        ctx.font = 'bold ' + fontSize + 'px "Hiragino Sans", "Yu Gothic", "Meiryo", sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(ov.text || '', x + w / 2, y + h / 2);

        // ピンの丸
        ctx.beginPath();
        ctx.arc(pinX, pinY, 6, 0, Math.PI * 2);
        ctx.fillStyle = 'red';
        ctx.fill();
        ctx.strokeStyle = 'darkred';
        ctx.lineWidth = 2;
        ctx.stroke();
      }}

      if (ov.type === 'info') {{
        // 情報欄：白背景 + テキスト
        ctx.globalAlpha = 0.9;
        ctx.fillStyle = 'white';
        // 角丸矩形
        var r = 8;
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + r);
        ctx.lineTo(x + w, y + h - r);
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
        ctx.lineTo(x + r, y + h);
        ctx.quadraticCurveTo(x, y + h, x, y + h - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1.0;
        ctx.strokeStyle = '#ccc';
        ctx.lineWidth = 1;
        ctx.stroke();

        // テキスト描画（自動折り返し・ボックスサイズ連動）
        var padding = 8;
        var textX = x + padding;
        var textY = y + padding;
        var maxTextW = w - padding * 2;
        var infoFs = Math.max(8, Math.min(18, Math.min(h * 0.09, w * 0.05)));
        var lineH = Math.round(infoFs * 1.5);
        var infoText = ov.text || '';
        ctx.fillStyle = 'black';
        ctx.font = infoFs + 'px "Hiragino Sans", "Yu Gothic", "Meiryo", sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        var lines = infoText.split('\\n');
        var curY = textY;
        lines.forEach(function(line) {{
          // 文字ごとに折り返し
          var cur = '';
          for (var i = 0; i < line.length; i++) {{
            var test = cur + line[i];
            if (ctx.measureText(test).width > maxTextW && cur.length > 0) {{
              if (curY + lineH > y + h - padding) return;
              ctx.fillText(cur, textX, curY);
              curY += lineH;
              cur = line[i];
            }} else {{
              cur = test;
            }}
          }}
          if (cur && curY + lineH <= y + h - padding) {{
            ctx.fillText(cur, textX, curY);
            curY += lineH;
          }}
        }});
      }}
    }});

    // 画像読み込み完了後にダウンロード
    Promise.all(loadPromises).then(function() {{
      canvas.toBlob(function(blob) {{
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = '駐車場マップ.png';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        confirmBtn.textContent = '✅ この配置で確定してダウンロード';
        confirmBtn.disabled = false;
        doneMsg.style.display = 'block';
        setTimeout(function() {{ doneMsg.style.display = 'none'; }}, 5000);
      }}, 'image/png');
    }});
  }});
}})();
</script>
</body>
</html>'''


# =============================================================
# メインアプリ
# =============================================================

st.title("🅿️ 駐車場マップ作成ツール")

# --- session_state の初期化 ---
if "place_step" not in st.session_state:
    st.session_state.place_step = 1
if "site_pos" not in st.session_state:
    st.session_state.site_pos = None
if "parking_pos" not in st.session_state:
    st.session_state.parking_pos = None

uploaded_file = None
layout_file = None

# --- 左右2カラムに分割 ---
col_left, col_right = st.columns([1, 2])

with col_left:
    st.subheader("⚙️ 設定")
    uploaded_file = st.file_uploader("Googleマップのスクショ", type=["png", "jpg", "jpeg"])
    layout_file = st.file_uploader("配置図（任意）", type=["png", "jpg", "jpeg"])

    # --- ステップ表示 ---
    st.write("---")
    st.subheader("📍 ラベル配置")
    step = st.session_state.place_step
    if step == 1:
        st.info("① 地図上で **「建築現場」の位置** をクリック")
    elif step == 2:
        st.success("✅ 建築現場を配置しました")
        st.info("② 地図上で **「駐車場」の位置** をクリック")
    elif step == 3:
        st.success("✅ 建築現場を配置しました")
        st.success("✅ 駐車場を配置しました")
        st.info("③ ドラッグで調整 → **「確定してダウンロード」**")

    if st.button("🔄 ラベル配置をやり直す"):
        st.session_state.place_step = 1
        st.session_state.site_pos = None
        st.session_state.parking_pos = None
        for k in ["result_image", "last_click_id"]:
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()

    # --- 駐車場情報メモ ---
    st.write("---")
    st.subheader("📝 駐車場情報")
    info_period = st.text_input("期間", placeholder="例：2/1～6/30まで")
    info_cars = st.text_input("台数", placeholder="例：二台")
    info_number = st.text_input("番号", placeholder="例：1.2")
    info_note = st.text_area("注意事項", placeholder="例：大型不可（軽トラも）", height=80)
    info_walk = st.text_input("徒歩分数", placeholder="例：5分")

    info_lines = []
    if info_period:
        info_lines.append(f"期間 {info_period}　台数 {info_cars}" if info_cars else f"期間 {info_period}")
    elif info_cars:
        info_lines.append(f"台数 {info_cars}")
    if info_number:
        info_lines.append(f"番号 {info_number}")
    if info_note:
        info_lines.append(info_note)
    if info_walk:
        info_lines.append(f"徒歩{info_walk}（現場から駐車場まで）")
    info_text = '\n'.join(info_lines)

# --- 右パネル ---
with col_right:
    if uploaded_file:
        image = Image.open(uploaded_file).convert("RGB")

        base_width = 700
        w_percent = base_width / float(image.size[0])
        h_size = int(float(image.size[1]) * w_percent)
        resized_image = image.resize((base_width, h_size), Image.Resampling.LANCZOS)

        step = st.session_state.place_step

        # =============================================
        # STEP 1 & 2: クリックでラベル位置を決定
        # =============================================
        if step <= 2:
            st.subheader("🗺️ 地図プレビュー — クリックで位置を決定")
            if step == 1:
                st.info("① 地図上で **「建築現場」の位置** をクリックしてください")
                display_img = resized_image
            else:
                st.info("② 地図上で **「駐車場」の位置** をクリックしてください")
                if "result_image" in st.session_state:
                    display_img = st.session_state.result_image
                else:
                    display_img = resized_image

            coords = streamlit_image_coordinates(display_img, key="click")

            if coords:
                click_id = f"{coords['x']}_{coords['y']}"
                if st.session_state.get("last_click_id") != click_id:
                    st.session_state.last_click_id = click_id
                    tx, ty = coords['x'], coords['y']

                    if step == 1:
                        st.session_state.site_pos = (tx, ty)
                        preview = draw_yellow_label(resized_image.copy(), tx, ty, "建築現場")
                        st.session_state.result_image = preview
                        st.session_state.place_step = 2
                        st.rerun()
                    elif step == 2:
                        st.session_state.parking_pos = (tx, ty)
                        st.session_state.place_step = 3
                        st.rerun()

        # =============================================
        # STEP 3: ドラッグエディター + Canvas描画ダウンロード
        # =============================================
        elif step == 3:
            st.subheader("🗺️ 配置の調整 — ドラッグで移動、四隅でリサイズ")

            bg_b64 = pil_to_base64(resized_image)

            site_x, site_y = st.session_state.site_pos
            park_x, park_y = st.session_state.parking_pos

            overlays = [
                {
                    "id": "site-label",
                    "type": "label",
                    "text": "建築現場",
                    "x": max(0, site_x - 55),
                    "y": max(0, site_y - 65),
                    "w": 110,
                    "h": 36
                },
                {
                    "id": "parking-label",
                    "type": "label",
                    "text": "駐車場",
                    "x": max(0, park_x - 45),
                    "y": max(0, park_y - 65),
                    "w": 90,
                    "h": 36
                },
            ]

            if info_text:
                overlays.append({
                    "id": "info-box",
                    "type": "info",
                    "text": info_text,
                    "x": 15,
                    "y": max(0, h_size - 145),
                    "w": 230,
                    "h": 130
                })

            if layout_file:
                layout_pil = Image.open(layout_file).convert("RGB")
                layout_b64 = pil_to_base64(layout_pil)
                overlays.append({
                    "id": "layout-img",
                    "type": "layout",
                    "image_base64": layout_b64,
                    "x": 10,
                    "y": 10,
                    "w": 150,
                    "h": 110
                })

            overlays_json = json.dumps(overlays, ensure_ascii=False)
            editor_html = build_drag_editor_html(bg_b64, overlays_json, base_width, h_size)
            components.html(editor_html, height=h_size + 80, scrolling=False)

    else:
        st.subheader("🗺️ 地図プレビュー")
        st.info("👆 左の操作パネルからGoogleマップのスクショをアップロードしてください。")
        for key in ["result_image", "last_click_id", "site_pos", "parking_pos"]:
            if key in st.session_state:
                del st.session_state[key]
        st.session_state.place_step = 1
