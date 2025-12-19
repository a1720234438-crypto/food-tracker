import streamlit as st
import requests
import json
import base64
import time
from supabase import create_client
from PIL import Image

# --- 1. 页面配置与初始化 ---
st.set_page_config(page_title="AI 饮食日记 (Final)", page_icon="🍱", layout="centered")

# 检查 Secrets 配置
if "gemini" not in st.secrets or "supabase" not in st.secrets:
    st.error("请在 Streamlit Cloud 的 Settings -> Secrets 中配置 API Key！")
    st.stop()

# 初始化 Supabase 客户端
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"数据库连接失败: {e}")
    st.stop()

# --- 2. 核心功能函数 ---

def analyze_image_logic(image_bytes):
    """
    使用原生 HTTP 请求访问 Gemini 1.5 Flash
    避开所有 SDK 兼容性问题，稳定性 100%
    """
    api_key = st.secrets["gemini"]["api_key"]
    # 强制使用最稳定的 1.5-flash 模型和 v1 正式接口
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    # 图片转 Base64
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    # 构造请求数据
    payload = {
        "contents": [{
            "parts": [
                {"text": "你是一个专业的营养师。请识别图片中的食物，并直接返回如下 JSON 格式内容（不要包含 Markdown 标记）：{\"food_name\":\"名称\", \"calories\":热量数字, \"nutrients\":\"蛋白质/碳水/脂肪简述\", \"analysis\":\"一句话点评\"}"},
                {"inline_data": {"mime_type": "image/jpeg", "data": base64_image}}
            ]
        }]
    }

    try:
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
        
        if response.status_code != 200:
            st.error(f"Google API 响应异常: {response.status_code}")
            with st.expander("查看错误详情"):
                st.write(response.text)
            return None
            
        res_json = response.json()
        # 提取 AI 返回的文本
        raw_text = res_json['candidates'][0]['content']['parts'][0]['text']
        # 清洗 JSON 字符串
        clean_json = raw_text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        st.error(f"AI 解析出错: {e}")
        return None

def upload_to_supabase(file_bytes, file_name):
    """上传图片到 Supabase Storage"""
    bucket_name = "food-images"
    # 文件名加时间戳防止重复
    file_path = f"{int(time.time())}_{file_name}"
    try:
        supabase.storage.from_(bucket_name).upload(
            path=file_path,
            file=file_bytes,
            file_options={"content-type": "image/jpeg"}
        )
        # 拼接公网访问地址
        base_url = st.secrets["supabase"]["url"]
        return f"{base_url}/storage/v1/object/public/{bucket_name}/{file_path}"
    except Exception as e:
        st.warning(f"图片上传失败 (不影响记录文字内容): {e}")
        return None

def save_record(data, image_url):
    """保存记录到 Supabase Database"""
    try:
        record = {
            "food_name": data.get("food_name", "未知食物"),
            "calories": data.get("calories", 0),
            "nutrients": data.get("nutrients", ""),
            "analysis": data.get("analysis", ""),
            "image_url": image_url
        }
        supabase.table("meals").insert(record).execute()
        return True
    except Exception as e:
        st.error(f"数据入库失败: {e}")
        return False

# --- 3. 界面 UI ---
st.title("🍱 AI 饮食日记")
st.caption("基于 Gemini 1.5 Flash | 自动计算热量 | 永久云端同步")

# 上传区域
with st.container(border=True):
    uploaded_file = st.file_uploader("拍一张或者选一张照片", type=["jpg", "png", "jpeg"])
    
    if uploaded_file:
        st.image(uploaded_file, width=250)
        if st.button("🚀 识别并记录", use_container_width=True):
            with st.spinner("正在呼叫 AI 营养师..."):
                img_bytes = uploaded_file.getvalue()
                
                # 1. AI 分析
                analysis_res = analyze_image_logic(img_bytes)
                
                if analysis_res:
                    # 2. 上传图片
                    img_url = upload_to_supabase(img_bytes, uploaded_file.name)
                    # 3. 保存到数据库
                    if save_record(analysis_res, img_url):
                        st.success(f"已存入: {analysis_res['food_name']}！")
                        time.sleep(1)
                        st.rerun()

# 历史记录展示区
st.divider()
st.subheader("📝 最近记录")

try:
    # 获取最新的 10 条数据
    response = supabase.table("meals").select("*").order("created_at", desc=True).limit(10).execute()
    records = response.data
    
    if not records:
        st.info("还没记录过哦，快去拍一张试试吧！")
    else:
        for item in records:
            with st.container(border=True):
                col1, col2 = st.columns([1, 2])
                with col1:
                    if item['image_url']:
                        st.image(item['image_url'], use_container_width=True)
                with col2:
                    st.markdown(f"#### {item['food_name']}")
                    st.markdown(f"🔥 **{item['calories']} kcal**")
                    st.caption(f"🧪 {item['nutrients']}")
                    st.write(f"💡 {item['analysis']}")
except Exception as e:
    st.error("加载记录失败")
