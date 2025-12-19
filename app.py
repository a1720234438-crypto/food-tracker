import streamlit as st
import requests
import json
import base64
import time
from supabase import create_client

# --- 1. 页面配置 ---
st.set_page_config(page_title="AI 饮食日记 (2025未来版)", page_icon="🚀")

# 检查配置
if "gemini" not in st.secrets or "supabase" not in st.secrets:
    st.error("❌ 请检查 .streamlit/secrets.toml！必须包含 [gemini] 和 [supabase]。")
    st.stop()

# 初始化数据库
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"❌ 数据库连接失败: {e}")
    st.stop()

# --- 2. 核心逻辑 ---

def get_proxies():
    """获取代理配置"""
    if "proxy" in st.secrets and st.secrets["proxy"]["url"]:
        p = st.secrets["proxy"]["url"]
        return {"http": p, "https": p}
    return None

def call_gemini_api(image_bytes, mime_type, model_name):
    """发送请求"""
    api_key = st.secrets["gemini"]["api_key"]
    # 使用 v1beta 接口
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                {"text": "你是一个营养师。请识别图片食物，返回纯JSON（不要markdown格式）：{\"food_name\":\"菜名\", \"calories\":整数热量, \"nutrients\":\"营养成分\", \"analysis\":\"简短评价\"}"},
                {"inline_data": {"mime_type": mime_type, "data": base64_image}}
            ]
        }]
    }

    try:
        response = requests.post(
            url, 
            json=payload, 
            headers={"Content-Type": "application/json"}, 
            timeout=50, 
            proxies=get_proxies()
        )
        return response
    except requests.exceptions.ConnectionError:
        return None

def analyze_smartly(image_bytes, mime_type):
    """
    智能分析：适配你的 2.5 版本环境
    """
    # 【核心修改】根据你的截图，使用了 2.5 和 2.0 系列
    models_candidates = [
        "gemini-2.5-pro",         # 截图里显示支持的最强模型！
        "gemini-2.5-flash",       # 截图里显示的最快模型
        "gemini-2.0-flash",       # 稳定版 2.0
        "gemini-2.0-flash-exp",   # 之前的备用
        "gemini-flash-latest"     # 通用别名保底
    ]
    
    last_debug_info = ""

    for model in models_candidates:
        # 增加重试机制，防止 429 繁忙
        for attempt in range(2): 
            with st.status(f"🚀 正在尝试旗舰模型: {model} ...", expanded=False) as status:
                resp = call_gemini_api(image_bytes, mime_type, model)
                
                # 1. 网络挂了
                if resp is None:
                    st.error("无法连接 Google。请检查代理设置。")
                    return None

                # 2. 成功
                if resp.status_code == 200:
                    try:
                        res_json = resp.json()
                        text = res_json['candidates'][0]['content']['parts'][0]['text']
                        clean_text = text.replace("```json", "").replace("```", "").strip()
                        status.update(label=f"✅ {model} 识别成功！", state="complete")
                        return json.loads(clean_text)
                    except:
                        pass 

                # 3. 繁忙 (429) -> 等待并重试
                elif resp.status_code == 429:
                    status.update(label=f"⏳ {model} 繁忙(429)，休息2秒...", state="running")
                    time.sleep(2) 
                    continue 
                
                # 4. 不存在 (404) -> 换下一个
                elif resp.status_code == 404:
                    status.update(label=f"❌ {model} 404跳过", state="error")
                    last_debug_info += f"\n{model}: 404"
                    break 

                # 其他错误
                else:
                    status.update(label=f"❌ {model} 报错 {resp.status_code}", state="error")
                    last_debug_info += f"\n{model}: {resp.text}"
                    break
    
    st.error("❌ 所有模型均不可用。请检查下方报错：")
    if last_debug_info:
        st.code(last_debug_info)
            
    return None

# --- 3. UI 部分 ---
def upload_img(file_bytes, name, mime_type):
    ext = mime_type.split('/')[-1]
    if ext == 'jpeg': ext = 'jpg'
    path = f"{int(time.time())}_{name}"
    if not path.endswith(f".{ext}"): path += f".{ext}"
    try:
        supabase.storage.from_("food-images").upload(path, file_bytes, {"content-type": mime_type})
        return f"{st.secrets['supabase']['url']}/storage/v1/object/public/food-images/{path}"
    except: return None

def save_to_db(data, url):
    try:
        supabase.table("meals").insert({
            "food_name": data.get("food_name", "未命名"),
            "calories": data.get("calories", 0),
            "nutrients": data.get("nutrients", ""),
            "analysis": data.get("analysis", ""),
            "image_url": url if url else ""
        }).execute()
        return True
    except: return False

st.title("🚀 AI 饮食记录 (2.5 Pro版)")

with st.sidebar:
    st.info("已启用 Gemini 2.5 Pro 模型")

uploaded_file = st.file_uploader("📸 拍照/上传", type=["jpg", "png", "jpeg", "webp"])

if uploaded_file:
    st.image(uploaded_file, width=300)
    if st.button("✨ 立即识别", type="primary"):
        img_bytes = uploaded_file.getvalue()
        result = analyze_smartly(img_bytes, uploaded_file.type)
        
        if result:
            url = upload_img(img_bytes, uploaded_file.name, uploaded_file.type)
            if save_to_db(result, url):
                st.balloons()
                st.success(f"已记录：{result['food_name']} ({result['calories']} kcal)")
                time.sleep(1)
                st.rerun()

st.divider()
try:
    rows = supabase.table("meals").select("*").order("created_at", desc=True).limit(3).execute().data
    for row in rows:
        with st.container(border=True):
            st.markdown(f"**{row['food_name']}**")
            st.caption(f"{row['calories']} kcal | {row['analysis']}")
except: pass
