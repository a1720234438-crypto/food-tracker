import streamlit as st
import requests
import json
import base64
import time
from supabase import create_client

# --- 1. 初始化 ---
st.set_page_config(page_title="AI 饮食日记 (诊断版)", page_icon="🍱")

if "gemini" not in st.secrets or "supabase" not in st.secrets:
    st.error("请配置 Secrets！")
    st.stop()

# 初始化数据库
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"数据库连接失败: {e}")
    st.stop()

# --- 2. 核心函数 (自适应模型版) ---

def get_available_models(api_key):
    """自动获取当前 Key 下所有可用的模型列表"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        res = requests.get(url)
        if res.status_code == 200:
            models = res.json().get('models', [])
            # 过滤出支持生成内容且支持图片输入的模型
            return [m['name'] for m in models if 'generateContent' in m['supportedGenerationMethods']]
        return []
    except:
        return []

def analyze_image_http(image_bytes):
    api_key = st.secrets["gemini"]["api_key"]
    
    # 1. 诊断：看看到底哪些模型可用
    available_models = get_available_models(api_key)
    
    # 2. 优先级排序：谁在列表里就用谁
    # 尝试顺序：2.0-flash -> 1.5-flash -> 1.5-pro -> 第一个可用的
    target_model = None
    priority = ["models/gemini-2.0-flash", "models/gemini-1.5-flash", "models/gemini-1.5-flash-8b", "models/gemini-1.5-pro"]
    
    for p in priority:
        if p in available_models:
            target_model = p
            break
    
    if not target_model:
        if available_models:
            target_model = available_models[0]
        else:
            st.error("你的 API Key 没有任何可用模型！请检查 Google AI Studio 权限。")
            return None

    # 3. 发送请求
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                {"text": "你是一个营养师。识别图中食物。只返回纯JSON: {\"food_name\":\"...\",\"calories\":0,\"nutrients\":\"...\",\"analysis\":\"...\"}"},
                {"inline_data": {"mime_type": "image/jpeg", "data": base64_image}}
            ]
        }]
    }

    try:
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
        if response.status_code != 200:
            st.error(f"模型 {target_model} 报错 ({response.status_code})")
            with st.expander("查看详情"):
                st.write(response.text)
            return None
            
        res_data = response.json()
        raw_text = res_data['candidates'][0]['content']['parts'][0]['text']
        clean_json = raw_text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        st.error(f"解析失败: {e}")
        return None

# --- 下面是上传和 UI 逻辑，保持不变 ---
def upload_image(file_bytes, file_name):
    bucket_name = "food-images"
    path = f"{int(time.time())}_{file_name}"
    try:
        supabase.storage.from_(bucket_name).upload(path, file_bytes, {"content-type": "image/jpeg"})
        return f"{st.secrets['supabase']['url']}/storage/v1/object/public/{bucket_name}/{path}"
    except: return None

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
    except: pass

st.title("🍱 AI 饮食记录 (自修复版)")
up_file = st.file_uploader("拍照", type=["jpg", "png", "jpeg"])

if up_file and st.button("🚀 开始分析"):
    with st.spinner("正在探测模型并分析..."):
        img_data = up_file.getvalue()
        result = analyze_image_http(img_data)
        if result:
            img_url = upload_image(img_data, up_file.name)
            save_to_db(result, img_url)
            st.success(f"成功: {result['food_name']}")
            time.sleep(1)
            st.rerun()

# 列表显示逻辑...
try:
    rows = supabase.table("meals").select("*").order("created_at", desc=True).limit(5).execute().data
    for row in rows:
        with st.container(border=True):
            st.write(f"**{row['food_name']}** | {row['calories']} kcal")
            if row['image_url']: st.image(row['image_url'], width=200)
except: pass
