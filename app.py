import streamlit as st
import google.generativeai as genai
from supabase import create_client
from PIL import Image
import json
import time

# --- 1. 初始化设置 ---
st.set_page_config(page_title="AI 饮食日记", page_icon="🥑")

if "gemini" not in st.secrets or "supabase" not in st.secrets:
    st.error("Secrets 配置缺失！")
    st.stop()

# 【关键修改】使用最稳定的旧版 SDK 初始化方式
try:
    genai.configure(api_key=st.secrets["gemini"]["api_key"])
except Exception as e:
    st.error(f"API Key 配置出错: {e}")
    st.stop()

# 初始化 Supabase
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"数据库连接失败: {e}")
    st.stop()

# --- 2. 核心函数 ---

def analyze_image(image_bytes):
    """
    使用 google-generative-ai (稳定版) 进行分析
    """
    # 提示词：强制要求 JSON
    prompt = """
    你是一个营养师。请识别图片中的食物。
    请直接返回标准的 JSON 格式数据，不要包含 Markdown 标记（如 ```json）。
    必须包含以下字段：
    {
        "food_name": "食物名称",
        "calories": 0 (整数热量),
        "nutrients": "蛋白质/碳水/脂肪含量描述",
        "analysis": "简短评价"
    }
    如果不是食物，calories 填 0，food_name 填 "未知"。
    """

    try:
        # 【关键修改】模型名称使用最通用的 'gemini-1.5-flash'
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # 调用接口
        response = model.generate_content([
            {'mime_type': 'image/jpeg', 'data': image_bytes},
            prompt
        ])
        
        # 清洗数据 (防止 AI 有时候还是加上了 ```json)
        text_content = response.text.strip()
        if text_content.startswith("```json"):
            text_content = text_content[7:]
        if text_content.endswith("```"):
            text_content = text_content[:-3]
            
        return json.loads(text_content)
        
    except Exception as e:
        st.error(f"AI 响应解析失败: {e}")
        return None

def upload_image(file_bytes, file_name):
    bucket_name = "food-images"
    path = f"{int(time.time())}_{file_name}"
    try:
        supabase.storage.from_(bucket_name).upload(path, file_bytes, {"content-type": "image/jpeg"})
        return f"{st.secrets['supabase']['url']}/storage/v1/object/public/{bucket_name}/{path}"
    except:
        return None # 忽略上传错误，保证能显示结果

def save_to_db(data, url):
    try:
        record = {
            "food_name": data.get("food_name", "未知"),
            "calories": data.get("calories", 0),
            "nutrients": data.get("nutrients", ""),
            "analysis": data.get("analysis", ""),
            "image_url": url
        }
        supabase.table("meals").insert(record).execute()
    except Exception as e:
        st.warning(f"保存数据库失败: {e}")

# --- 3. 界面逻辑 ---
st.title("🥑 AI 饮食追踪 (稳定版)")

with st.expander("➕ 记一笔", expanded=True):
    up_file = st.file_uploader("拍照", type=["jpg", "png", "jpeg"])
    
    if up_file and st.button("🚀 开始分析"):
        with st.spinner("正在识别..."):
            bytes_data = up_file.getvalue()
            
            # 1. AI 分析
            result = analyze_image(bytes_data)
            
            if result:
                # 2. 上传 & 保存
                url = upload_image(bytes_data, up_file.name)
                save_to_db(result, url)
                
                # 3. 反馈
                st.success(f"已记录: {result['food_name']} ({result['calories']} kcal)")
                time.sleep(1)
                st.rerun()

st.divider()
try:
    rows = supabase.table("meals").select("*").order("created_at", desc=True).limit(5).execute().data
    for row in rows:
        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            with c1:
                if row['image_url']: st.image(row['image_url'])
            with c2:
                st.markdown(f"**{row['food_name']}**")
                st.caption(f"{row['calories']} kcal | {row['analysis']}")
except:
    pass
