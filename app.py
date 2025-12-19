import streamlit as st
import requests
import json
import base64
import time
from supabase import create_client

# --- 1. 初始化 ---
st.set_page_config(page_title="AI 饮食日记", page_icon="🥑")

if "gemini" not in st.secrets or "supabase" not in st.secrets:
    st.error("请配置 Secrets！")
    st.stop()

try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"数据库连接失败: {e}")
    st.stop()

# --- 2. 核心函数 ---

def analyze_image_http(image_bytes):
    api_key = st.secrets["gemini"]["api_key"]
    
    # 【修正点】使用 -latest 后缀，强制指向最新版，解决 404 问题
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={api_key}"
    
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                {"text": "你是一个营养师。识别图片中的食物。请务必返回纯 JSON 格式：{\"food_name\": \"...\", \"calories\": 0, \"nutrients\": \"...\", \"analysis\": \"...\"}。如果不是食物，calories填0。不要使用Markdown格式。"},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64_image
                    }
                }
            ]
        }]
    }

    try:
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
        
        # 调试信息：如果再报错，屏幕上会直接显示 Google 到底说了什么
        if response.status_code != 200:
            st.error(f"API 报错 (代码 {response.status_code}): {response.text}")
            return None
            
        result_json = response.json()
        try:
            # 尝试解析深层结构
            if 'candidates' in result_json:
                text_content = result_json['candidates'][0]['content']['parts'][0]['text']
                text_content = text_content.replace("```json", "").replace("```", "").strip()
                return json.loads(text_content)
            else:
                st.error(f"AI 返回了空数据: {result_json}")
                return None
        except Exception as e:
            st.error(f"解析 JSON 失败: {e}")
            return None
            
    except Exception as e:
        st.error(f"网络连接失败: {e}")
        return None

def upload_image(file_bytes, file_name):
    bucket_name = "food-images"
    path = f"{int(time.time())}_{file_name}"
    try:
        supabase.storage.from_(bucket_name).upload(path, file_bytes, {"content-type": "image/jpeg"})
        return f"{st.secrets['supabase']['url']}/storage/v1/object/public/{bucket_name}/{path}"
    except:
        return None

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
    except:
        pass

# --- 3. 界面 ---
st.title("🥑 AI 饮食追踪")

with st.expander("➕ 记一笔", expanded=True):
    up_file = st.file_uploader("拍照", type=["jpg", "png", "jpeg"])
    
    if up_file and st.button("🚀 开始分析"):
        with st.spinner("连接 Google..."):
            bytes_data = up_file.getvalue()
            result = analyze_image_http(bytes_data)
            
            if result:
                url = upload_image(bytes_data, up_file.name)
                save_to_db(result, url)
                st.success(f"已记录: {result['food_name']}")
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
