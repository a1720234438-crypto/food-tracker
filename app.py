import streamlit as st
from google import genai
from google.genai import types
from supabase import create_client
from PIL import Image
import json
import time
from datetime import datetime
import io

# --- 1. 配置与初始化 ---
st.set_page_config(page_title="AI 饮食日记 (Pro)", page_icon="🍱", layout="centered")

if "gemini" not in st.secrets or "supabase" not in st.secrets:
    st.error("请配置 .streamlit/secrets.toml")
    st.stop()

# [变化点1] 初始化客户端：新版使用 genai.Client
client = genai.Client(api_key=st.secrets["gemini"]["api_key"])

# 初始化 Supabase
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"数据库连接失败: {e}")
    st.stop()


# --- 2. 核心功能函数 ---

def analyze_image_with_new_sdk(image_file):
    """使用新版 SDK (google-genai) 分析食物"""

    # 定义我们想要的数据结构 (新版 SDK 的强项！)
    class FoodInfo(to_dict=True):  # 这是一个 Pydantic 风格的定义
        food_name: str
        calories: int
        protein: str
        carbs: str
        fat: str
        analysis: str

    try:
        # 将上传的文件转为 Bytes
        image_bytes = image_file.getvalue()

        # [变化点2] 调用方式变了：client.models.generate_content
        response = client.models.generate_content(
            model="gemini-2.0-flash",  # 建议尝试最新的 2.0 Flash，速度极快
            contents=[
                "识别图中的食物。如果不是食物，calories填0，名称填'未知'。",
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",  # 强制返回 JSON
                response_schema=list[FoodInfo]  # 或者直接指定结构
            )
        )

        # 新版 SDK 可能会直接返回对象，或者我们需要解析 JSON 文本
        # 这里为了稳妥，我们解析 text
        return json.loads(response.text)[0]  # 假设返回的是列表中的第一个

    except Exception as e:
        st.error(f"AI 分析出错: {e}")
        return None


def upload_image(file_bytes, file_name):
    """上传图片到 Supabase (保持不变)"""
    bucket_name = "food-images"
    timestamp = int(time.time())
    file_path = f"{timestamp}_{file_name}"

    try:
        supabase.storage.from_(bucket_name).upload(
            path=file_path,
            file=file_bytes,
            file_options={"content-type": "image/jpeg"}
        )
        project_url = st.secrets["supabase"]["url"]
        return f"{project_url}/storage/v1/object/public/{bucket_name}/{file_path}"
    except Exception as e:
        st.error(f"图片上传失败: {e}")
        return None


def save_to_db(data, image_url):
    """写入数据库"""
    nutrients_str = f"P:{data.get('protein')} | C:{data.get('carbs')} | F:{data.get('fat')}"
    record = {
        "food_name": data.get("food_name", "未知"),
        "calories": data.get("calories", 0),
        "nutrients": nutrients_str,
        "analysis": data.get("analysis", ""),
        "image_url": image_url
    }
    supabase.table("meals").insert(record).execute()


# --- 3. 页面 UI ---
st.title("🍱 AI 饮食追踪 (New SDK)")

with st.expander("➕ 记一笔", expanded=True):
    uploaded_file = st.file_uploader("拍摄食物", type=["jpg", "png", "jpeg", "webp"])

    if uploaded_file:
        st.image(uploaded_file, caption="预览", width=300)

        if st.button("🚀 开始分析"):
            with st.spinner("Gemini 2.0 正在分析..."):
                # 1. AI 分析
                ai_result = analyze_image_with_new_sdk(uploaded_file)

                if ai_result:
                    # 2. 上传图片
                    uploaded_file.seek(0)
                    url = upload_image(uploaded_file.read(), uploaded_file.name)

                    if url:
                        # 3. 保存
                        save_to_db(ai_result, url)
                        st.success(f"已记录：{ai_result['food_name']}")
                        time.sleep(1)
                        st.rerun()

# --- 列表展示 (保持不变) ---
st.divider()
try:
    response = supabase.table("meals").select("*").order("created_at", desc=True).limit(10).execute()
    for meal in response.data:
        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            with c1:
                if meal['image_url']: st.image(meal['image_url'])
            with c2:
                st.markdown(f"**{meal['food_name']}** - `{meal['calories']} kcal`")
                st.caption(meal['analysis'])
except:
    pass