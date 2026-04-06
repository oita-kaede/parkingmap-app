import streamlit as st
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
from streamlit_image_coordinates import streamlit_image_coordinates
import io
import base64

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
    """黄色背景ラベル + 黄色線 + 赤ピンを描画"""
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


def draw_info_box(image, info_text, box_x, box_y, box_w, box_h, font_size=28):
    """指定位置・サイズで情報欄を描画"""
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("ipaexg.ttf", font_size)
    except:
        font = ImageFont.load_default()

    overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        (box_x, box_y, box_x + box_w, box_y + box_h),
        radius=8, fill=(255, 255, 255, 230), outline=(200, 200, 200, 255), width=1
    )
    image = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')

    draw = ImageDraw.Draw(image)
    padding = 10
    lines = info_text.strip().split('\n')
    current_y = box_y + padding
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        line_h = bb[3] - bb[1]
        draw.text((box_x + padding, current_y - bb[1]), line, font=font, fill="black")
        current_y += line_h + 8
        if current_y > box_y + box_h - padding:
            break

    return image


def overlay_layout_image(base_image, layout_pil, lx, ly, lw, lh):
    """指定位置・サイズで配置図を重ねる"""
    resized = layout_pil.resize((max(1, lw), max(1, lh)), Image.Resampling.LANCZOS)
    border = 3
    bordered = Image.new('RGB', (resized.width + border * 2, resized.height + border * 2), 'white')
    bordered.paste(resized, (border, border))
    px = max(0, min(lx, base_image.width - bordered.width))
    py = max(0, min(ly, base_image.height - bordered.height))
    base_image.paste(bordered, (px, py))
    return base_image


def render_preview(base_image, site_pos, park_pos, info_text, layout_pil=None,
                   site_offset=(0,0), park_offset=(0,0),
                   info_x=15, info_y=None, info_w=230, info_h=130,
                   layout_x=10, layout_y=10, layout_w=150, layout_h=110):
    """スライダー値を反映したプレビュー画像を生成"""
    result = base_image.copy()

    # 配置図
    if layout_pil:
        result = overlay_layout_image(result, layout_pil, layout_x, layout_y, layout_w, layout_h)

    # 建築現場ラベル
    sx = site_pos[0] + site_offset[0]
    sy = site_pos[1] + site_offset[1]
    result = draw_yellow_label(result, sx, sy, "建築現場", font_size=32)

    # 駐車場ラベル
    px = park_pos[0] + park_offset[0]
    py = park_pos[1] + park_offset[1]
    result = draw_yellow_label(result, px, py, "駐車場", font_size=32)

    # 情報欄
    if info_text:
        if info_y is None:
            info_y = base_image.height - info_h - 15
        font_size = max(14, min(32, int(info_h / max(1, info_text.count('\n') + 1) * 0.6)))
        result = draw_info_box(result, info_text, info_x, info_y, info_w, info_h, font_size=font_size)

    return result


# =============================================================
# メインアプリ
# =============================================================

st.title("🅿️ 駐車場マップ作成ツール")

# --- session_state の初期化 ---
if "place_step" not in st.session_state:
    st.session_state.place_step = 1  # 1=建築現場待ち, 2=駐車場待ち, 3=配置調整, 4=確定済み
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
        st.info("③ スライダーで位置を調整 → **「確定」** ボタン")
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
        # STEP 3: スライダーで位置調整 + リアルタイムプレビュー
        # =============================================
        elif step == 3:
            st.subheader("🗺️ 配置の調整")

            site_x, site_y = st.session_state.site_pos
            park_x, park_y = st.session_state.parking_pos

            # --- 位置調整スライダー ---
            with st.expander("📌 建築現場ラベルの位置調整", expanded=False):
                site_dx = st.slider("建築現場 左右", -200, 200, 0, key="site_dx")
                site_dy = st.slider("建築現場 上下", -200, 200, 0, key="site_dy")

            with st.expander("📌 駐車場ラベルの位置調整", expanded=False):
                park_dx = st.slider("駐車場 左右", -200, 200, 0, key="park_dx")
                park_dy = st.slider("駐車場 上下", -200, 200, 0, key="park_dy")

            # 情報欄の位置
            info_x = 15
            info_y_default = max(0, h_size - 145)
            info_w = 230
            info_h = 130

            if info_text:
                with st.expander("📋 情報欄の位置調整", expanded=False):
                    info_x = st.slider("情報欄 左右", 0, base_width - 100, info_x, key="info_x")
                    info_y_default = st.slider("情報欄 上下", 0, h_size - 50, info_y_default, key="info_y")
                    info_w = st.slider("情報欄 幅", 100, 400, info_w, key="info_w")
                    info_h = st.slider("情報欄 高さ", 60, 300, info_h, key="info_h")

            # 配置図の位置
            layout_pil = None
            layout_x, layout_y, layout_w, layout_h = 10, 10, 150, 110
            if layout_file:
                layout_pil = Image.open(layout_file).convert("RGB")
                with st.expander("🖼️ 配置図の位置調整", expanded=False):
                    layout_x = st.slider("配置図 左右", 0, base_width - 50, layout_x, key="layout_x")
                    layout_y = st.slider("配置図 上下", 0, h_size - 50, layout_y, key="layout_y")
                    layout_w = st.slider("配置図 幅", 50, 400, layout_w, key="layout_w")
                    layout_h = st.slider("配置図 高さ", 50, 300, layout_h, key="layout_h")

            # --- プレビュー画像生成 ---
            preview = render_preview(
                resized_image,
                (site_x, site_y),
                (park_x, park_y),
                info_text,
                layout_pil=layout_pil,
                site_offset=(site_dx, site_dy),
                park_offset=(park_dx, park_dy),
                info_x=info_x, info_y=info_y_default, info_w=info_w, info_h=info_h,
                layout_x=layout_x, layout_y=layout_y, layout_w=layout_w, layout_h=layout_h
            )

            st.image(preview, use_container_width=True)
            st.caption("💡 位置を微調整したい場合は上のスライダーを操作してください")

            # --- 確定ボタン ---
            if st.button("✅ この配置で確定する", type="primary", use_container_width=True):
                st.session_state.final_image = preview
                st.session_state.place_step = 4
                st.rerun()

        # =============================================
        # STEP 4: 確定済み — 最終画像表示 + ダウンロード
        # =============================================
        elif step == 4:
            st.subheader("🗺️ 完成マップ")

            if st.session_state.final_image:
                st.image(st.session_state.final_image, use_container_width=True)
                st.success("✅ 配置が確定されました")

                buf_dl = io.BytesIO()
                st.session_state.final_image.save(buf_dl, format="PNG")
                st.download_button(
                    "📥 駐車場マップをダウンロード",
                    buf_dl.getvalue(),
                    "駐車場マップ.png",
                    "image/png",
                    use_container_width=True
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
