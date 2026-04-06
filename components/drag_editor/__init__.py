import streamlit.components.v1 as components
import os
import json

_COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
_component_func = components.declare_component("drag_editor", path=_COMPONENT_DIR)


def drag_editor(image_base64, overlays, key=None):
    """
    ドラッグ＆リサイズ可能なオーバーレイエディター

    Parameters
    ----------
    image_base64 : str
        背景画像のbase64文字列 (data:image/png;base64,... 形式)
    overlays : list[dict]
        各オーバーレイ要素。例:
        [
            {"id": "site-label", "type": "label", "text": "建築現場", "x": 100, "y": 80, "w": 110, "h": 36},
            {"id": "parking-label", "type": "label", "text": "駐車場", "x": 300, "y": 250, "w": 90, "h": 36},
            {"id": "info-box", "type": "info", "text": "期間...", "x": 10, "y": 350, "w": 220, "h": 130},
            {"id": "layout-img", "type": "layout", "image_base64": "...", "x": 10, "y": 10, "w": 150, "h": 110},
        ]
    key : str
        Streamlit widget key

    Returns
    -------
    dict or None
        確定時に各要素の位置・サイズを返す
    """
    result = _component_func(
        image_base64=image_base64,
        overlays=json.dumps(overlays, ensure_ascii=False),
        key=key,
        default=None
    )
    return result
