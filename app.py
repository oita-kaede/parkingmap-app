import streamlit as st
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
from streamlit_image_coordinates import streamlit_image_coordinates
from components.drag_editor import drag_editor
import io
import base64
import json

st.set_page_config(page_title="駐車場マップ作成ツール", layout="wide", page_icon="🅿️")


# =============================================================
# ユーティリティ関数
# =============================================================

def pil_to_base64(pil_image, fmt="PNG"):
    buf = io.BytesIO()
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
    """テキストをbox幅に合わせて自動改行する"""
    wrapped_lines = []
    for line in text.strip().split('\n'):
        if not line:
            wrapped_lines.append('')
            continue
        # 1行ずつ幅をチェックして折り返す
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
    """折り返し済みテキストの合計高さを計算"""
    total = 0
    for line in lines:
        if not line:
            total += line_spacing
            continue
        bb = draw.textbbox((0, 0), line, font=font)
        total += (bb[3] - bb[1]) + line_spacing
    return total


def draw_info_box(image, info_text, box_x, box_y, box_w, box_h, font_size=14):
    """枠に合わせてフォントサイズ自動調整 + 自動改行する情報欄"""
    draw = ImageDraw.Draw(image)
    padding = 8
    inner_w = box_w - padding * 2
    inner_h = box_h - padding * 2
    line_spacing = 5

    # フォントサイズを自動調整（枠に収まるまで小さくする）
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

    # 半透明の白背景
    overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        (box_x, box_y, box_x + box_w, box_y + box_h),
        radius=8, fill=(255, 255, 255, 230), outline=(200, 200, 200, 255), width=1
    )
    image = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')

    # テキスト描画
    draw = ImageDraw.Draw(image)
    current_y = box_y + padding
    for line in wrapped:
        if not line:
            current_y += line_spacing
            continue
        bb = draw.textbbox((0, 0), line, font=font)
        line_h = bb[3] - bb[1]
        # 枠の下限チェック
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


def render_final_image(base_image, positions, info_text, layout_pil=None):
    """ドラッグ後の位置をもとに最終画像を生成

    Parameters
    ----------
    positions : dict
        drag_editor から返される位置情報。
        例: {"site-label": {"x":..,"y":..,"w":..,"h":..}, "parking-label": {...}, ...}
    """
    result = base_image.copy()
    img_w, img_h = result.size

    # 配置図
    if layout_pil and "layout-img" in positions:
        lp = positions["layout-img"]
        result = overlay_layout_image(result, layout_pil, lp["x"], lp["y"], lp["w"], lp["h"])
    elif layout_pil:
        result = overlay_layout_image(result, layout_pil, 10, 10, 150, 110)

    # 建築現場ラベル — ピン位置はラベルの下中央 + pin offset(16px)
    if "site-label" in positions:
        sp = positions["site-label"]
        pin_x = sp["x"] + sp["w"] // 2
        pin_y = sp["y"] + sp["h"] + 16
        result = draw_yellow_label(result, pin_x, pin_y, "建築現場", font_size=18)

    # 駐車場ラベル
    if "parking-label" in positions:
        pp = positions["parking-label"]
        pin_x = pp["x"] + pp["w"] // 2
        pin_y = pp["y"] + pp["h"] + 16
        result = draw_yellow_label(result, pin_x, pin_y, "駐車場", font_size=18)

    # 情報欄
    if info_text and "info-box" in positions:
        ip = positions["info-box"]
        result = draw_info_box(result, info_text, ip["x"], ip["y"], ip["w"], ip["h"], font_size=14)
    elif info_text:
        box_w, box_h = 230, 130
        box_x = 15
        box_y = max(0, img_h - box_h - 15)
        result = draw_info_box(result, info_text, box_x, box_y, box_w, box_h, font_size=14)

    return result



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
if "final_image" not in st.session_state:
    st.session_state.final_image = None

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
        st.info("③ プレビューを確認 → **「確定」** ボタン")
    else:
        st.success("✅ 配置を確定しました")

    if st.button("🔄 ラベル配置をやり直す"):
        st.session_state.place_step = 1
        st.session_state.site_pos = None
        st.session_state.parking_pos = None
        st.session_state.final_image = None
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

    # --- 保存セクション（Step4で表示） ---
    if st.session_state.final_image is not None:
        st.write("---")
        st.subheader("📥 保存")
        buf_dl = io.BytesIO()
        st.session_state.final_image.save(buf_dl, format="PNG")
        st.download_button(
            "📥 駐車場マップをダウンロード",
            buf_dl.getvalue(),
            "駐車場マップ.png",
            "image/png",
            use_container_width=True,
            key="dl_left"
        )

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
        # STEP 3: ドラッグでプレビュー + 確定ボタン
        # =============================================
        elif step == 3:
            st.subheader("🗺️ 配置の調整 — ドラッグで移動、四隅でリサイズ")
            st.caption("要素をドラッグして位置を調整し、「✅ この配置で確定する」を押してください")

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

            # --- drag_editor コンポーネント（双方向通信） ---
            result = drag_editor(
                image_base64=bg_b64,
                overlays=overlays,
                key="drag_editor"
            )

            # ユーザーが「確定」ボタンを押すと result に位置情報が返る
            if result is not None:
                layout_pil_final = None
                if layout_file:
                    layout_file.seek(0)
                    layout_pil_final = Image.open(layout_file).convert("RGB")

                final = render_final_image(
                    resized_image,
                    result,        # ドラッグ後の位置情報
                    info_text,
                    layout_pil_final
                )
                st.session_state.final_image = final
                st.session_state.place_step = 4
                st.rerun()

        # =============================================
        # STEP 4: 確定済み — 最終画像 + ダウンロード
        # =============================================
        elif step == 4:
            st.subheader("🗺️ 完成マップ")

            if st.session_state.final_image:
                st.image(st.session_state.final_image, use_container_width=True)
                st.success("✅ 配置が確定されました。左パネルからダウンロードできます。")

                buf_dl = io.BytesIO()
                st.session_state.final_image.save(buf_dl, format="PNG")
                st.download_button(
                    "📥 駐車場マップをダウンロード",
                    buf_dl.getvalue(),
                    "駐車場マップ.png",
                    "image/png",
                    use_container_width=True,
                    key="dl_right"
                )

            if st.button("🔧 配置を再調整する"):
                st.session_state.place_step = 3
                st.session_state.final_image = None
                st.rerun()

    else:
        st.subheader("🗺️ 地図プレビュー")
        st.info("👆 左の操作パネルからGoogleマップのスクショをアップロードしてください。")
        for key in ["result_image", "last_click_id", "site_pos", "parking_pos", "final_image"]:
            if key in st.session_state:
                del st.session_state[key]
        st.session_state.place_step = 1
