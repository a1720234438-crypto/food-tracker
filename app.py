import streamlit as st
import requests
import json
import base64
import time
from supabase import create_client

# --- 1. 初始化 ---
st.set_page_config(page_title="AI 饮食日记", page_icon="🍱")

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
    
    # 【最后的核心修复】使用 v1 正式版接口和标准模型名
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                {"text": "识别图中食物。只返回纯JSON: {\"food_name\":\"...\",\"calories\":0,\"nutrients\":\"...\",\"analysis\":\"...\"}"},
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
        
        if response.status_code != 200:
            # 报错时，直接显示最直观的错误原因
            st.error(f"Google API 报错 ({response.status_code})")
            with st.expander("点击查看具体错误原因"):
                st.write(response.text)
            return None
            
        res_data = response.json()
        try:
            # 解析 Google 返回的深层文本
            raw_text = res_data['candidates'][0]['content']['parts'][0]['text']
            # 清理代码块标记
            clean_json = raw_text.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_json)
        except Exception as e:
            st.error("AI 返回格式解析失败")
            return None
            
    except Exception as e:
        st.error(f"网络请求失败: {e}")
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

# --- 3. 页面 ---
st.title("🍱 AI 饮食记录")

with st.expander("➕ 记一笔", expanded=True):
    up_file = st.file_uploader("拍一张照片", type=["jpg", "png", "jpeg"])
    
    if up_file and st.button("🚀 开始分析"):
        with st.spinner("正在呼叫 AI..."):
            img_data = up_file.getvalue()
            result = analyze_image_http(img_data)
            
            if result:
                img_url = upload_image(img_data, up_file.name)
                save_to_db(result, img_url)
                st.success(f"成功记录: {result['food_name']}")
                time.sleep(1)
                st.rerun()

st.divider()
try:
    rows = supabase.table("meals").select("*").order("created_at", desc=True).limit(10).execute().data
    for row in rows:
        with st.container(border=True):
            c1, c2 = st.columns([1, 2])
            with c1:
                if row['image_url']: st.image(row['image_url'])
            with c2:
                st.subheader(row['food_name'])
                st.write(f"🔥 {row['calories']} kcal")
                st.caption(row['analysis'])
except:
    st.info("这里将显示你的历史记录")
