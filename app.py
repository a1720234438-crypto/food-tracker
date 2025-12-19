import streamlit as st
import requests
import json
import base64
import time
from supabase import create_client

# --- 1. 页面设置 ---
st.set_page_config(page_title="AI 饮食日记", page_icon="🍱")

# 检查配置
if "gemini" not in st.secrets or "supabase" not in st.secrets:
    st.error("请配置 Secrets！")
    st.stop()

# 初始化数据库
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"数据库连接失败: {e}")
    st.stop()

# --- 2. 核心分析逻辑 ---

def call_gemini_api(image_bytes, model_name):
    """
    最底层的 HTTP 调用，增加模型兼容性逻辑
    """
    api_key = st.secrets["gemini"]["api_key"]
    # 强制使用 v1beta 接口，这是目前最兼容图片识别的路径
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    payload = {
        "contents": [{
            "parts": [
                {"text": "你是一个营养师。请识别图片中的食物，直接返回如下JSON格式：{\"food_name\":\"名称\", \"calories\":数字, \"nutrients\":\"简述\", \"analysis\":\"点评\"}"},
                {"inline_data": {"mime_type": "image/jpeg", "data": base64_image}}
            ]
        }]
    }

    response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
    return response

def analyze_image_self_healing(image_bytes):
    """
    自愈式分析：如果一个模型失败，自动尝试另一个
    """
    # 尝试顺序：1.5-flash (最稳) -> 1.5-flash-8b (极速) -> 2.0-flash (最强但限流)
    models_to_try = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-2.0-flash"]
    
    for model in models_to_try:
        with st.status(f"正在尝试使用 {model} 进行识别...", expanded=False):
            resp = call_gemini_api(image_bytes, model)
            
            if resp.status_code == 200:
                try:
                    res_data = resp.json()
                    raw_text = res_data['candidates'][0]['content']['parts'][0]['text']
                    clean_json = raw_text.replace("```json", "").replace("```", "").strip()
                    return json.loads(clean_json)
                except:
                    continue
            elif resp.status_code == 429:
                st.warning(f"{model} 额度已满，尝试下一个...")
                time.sleep(1) # 稍作停顿
                continue
            else:
                st.error(f"{model} 报错: {resp.status_code}")
                continue
    
    st.error("所有 AI 模型目前都不可用，请稍后再试。")
    return None

# --- 3. 基础功能 ---
def upload_img(file_bytes, name):
    path = f"{int(time.time())}_{name}"
    try:
        supabase.storage.from_("food-images").upload(path, file_bytes, {"content-type": "image/jpeg"})
        return f"{st.secrets['supabase']['url']}/storage/v1/object/public/food-images/{path}"
    except: return None

def save_to_db(data, url):
    record = {
        "food_name": data.get("food_name", "未知"),
        "calories": data.get("calories", 0),
        "nutrients": data.get("nutrients", ""),
        "analysis": data.get("analysis", ""),
        "image_url": url
    }
    supabase.table("meals").insert(record).execute()

# --- 4. UI 界面 ---
st.title("🍱 AI 饮食记录")

uploaded_file = st.file_uploader("拍一张照片", type=["jpg", "png", "jpeg"])

if uploaded_file:
    st.image(uploaded_file, width=300)
    if st.button("🚀 识别并记录"):
        img_bytes = uploaded_file.getvalue()
        result = analyze_image_self_healing(img_bytes)
        
        if result:
            img_url = upload_img(img_bytes, uploaded_file.name)
            save_to_db(result, img_url)
            st.success(f"成功识别: {result['food_name']}!")
            time.sleep(1)
            st.rerun()

st.divider()
# 展示历史记录
try:
    rows = supabase.table("meals").select("*").order("created_at", desc=True).limit(5).execute().data
    for row in rows:
        with st.container(border=True):
            c1, c2 = st.columns([1, 2])
            if row['image_url']: c1.image(row['image_url'])
            c2.markdown(f"**{row['food_name']}** | 🔥 {row['calories']} kcal")
            c2.caption(row['analysis'])
except: pass
