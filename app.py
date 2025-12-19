import streamlit as st
from google import genai
from google.genai import types
from supabase import create_client
from PIL import Image
import json
import time

# --- 1. 配置与初始化 ---
st.set_page_config(page_title="AI 饮食日记", page_icon="🥑")

# 检查 Secrets
if "gemini" not in st.secrets or "supabase" not in st.secrets:
    st.error("请配置 Secrets！")
    st.stop()

# 初始化 Gemini 客户端
client = genai.Client(api_key=st.secrets["gemini"]["api_key"])

# 初始化 Supabase
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"数据库连接失败: {e}")
    st.stop()

# --- 2. 核心功能函数 ---

def analyze_image(image_bytes):
    """
    修复版：使用标准的 JSON Schema 定义，
    不再使用 class 写法，彻底避免 TypeError。
    """
    
    # 提示词
    prompt = "识别图中的食物。请务必返回 JSON 格式数据。如果不是食物，calories 填 0。"

    try:
        # 调用 AI (配置更稳妥的 Schema)
        response = client.models.generate_content(
            model="gemini-1.5-flash-001", 
            contents=[
                prompt,
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "OBJECT",
                    "properties": {
                        "food_name": {"type": "STRING"},
                        "calories": {"type": "INTEGER"},
                        "nutrients": {"type": "STRING"},
                        "analysis": {"type": "STRING"},
                    },
                    "required": ["food_name", "calories", "nutrients", "analysis"]
                }
            )
        )
        
        # 解析返回结果
        # 新版 SDK 有时候会直接把结果转为 dict，有时候是 text
        if response.parsed:
            return response.parsed
        else:
            return json.loads(response.text)
            
    except Exception as e:
        st.error(f"AI 识别出错: {e}")
        return None

def upload_image(file_bytes, file_name):
    bucket_name = "food-images"
    # 使用时间戳避免文件名重复
    path = f"{int(time.time())}_{file_name}"
    try:
        supabase.storage.from_(bucket_name).upload(path, file_bytes, {"content-type": "image/jpeg"})
        return f"{st.secrets['supabase']['url']}/storage/v1/object/public/{bucket_name}/{path}"
    except Exception as e:
        # 很多时候是文件名乱码问题，这里做个简单容错
        st.warning(f"图片上传遇到小问题，但记录继续: {e}")
        return None

def save_to_db(data, url):
    record = {
        "food_name": data.get("food_name", "未知"),
        "calories": data.get("calories", 0),
        "nutrients": data.get("nutrients", ""),
        "analysis": data.get("analysis", ""),
        "image_url": url
    }
    supabase.table("meals").insert(record).execute()

# --- 3. 界面 UI ---
st.title("🥑 AI 饮食追踪")

# 上传区域
with st.expander("➕ 记一笔", expanded=True):
    up_file = st.file_uploader("拍照或上传", type=["jpg", "png", "jpeg"])
    
    if up_file is not None:
        st.image(up_file, caption="预览", width=300)
        
        if st.button("🚀 开始分析"):
            with st.spinner("AI 正在识别..."):
                # 读取图片数据
                bytes_data = up_file.getvalue()
                
                # 1. 分析
                result = analyze_image(bytes_data)
                
                if result:
                    # 2. 上传 (如果上传失败 url 可能是 None，也不影响记录文字)
                    url = upload_image(bytes_data, up_file.name)
                    
                    # 3. 保存
                    save_to_db(result, url)
                    
                    st.success(f"已记录: {result['food_name']} ({result['calories']} kcal)")
                    time.sleep(1)
                    st.rerun()

# 列表区域
st.divider()
st.subheader("📝 近期记录")
try:
    rows = supabase.table("meals").select("*").order("created_at", desc=True).limit(5).execute().data
    for row in rows:
        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            with c1:
                if row['image_url']: st.image(row['image_url'], use_container_width=True)
            with c2:
                st.markdown(f"**{row['food_name']}**")
                st.code(f"{row['calories']} kcal | {row['nutrients']}")
                st.caption(row['analysis'])
except Exception:
    st.info("暂无数据")



