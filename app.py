import streamlit as st
import requests
import json
import base64
import time
from supabase import create_client

# --- 1. 页面配置 ---
st.set_page_config(page_title="AI 饮食日记 (终极修复版)", page_icon="🛡️")

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

def check_available_models():
    """
    【诊断工具】查询当前 Key 支持的所有模型名字
    """
    api_key = st.secrets["gemini"]["api_key"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    proxies = get_proxies()
    try:
        resp = requests.get(url, proxies=proxies, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # 过滤出支持生成内容的模型
            names = [m['name'].replace('models/', '') for m in data.get('models', []) if 'generateContent' in m['supportedGenerationMethods']]
            return names
        return []
    except:
        return []

def call_gemini_api(image_bytes, mime_type, model_name):
    """发送请求"""
    api_key = st.secrets["gemini"]["api_key"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                {"text": "你是一个营养师。请识别图片食物，返回纯JSON：{\"food_name\":\"菜名\", \"calories\":整数热量, \"nutrients\":\"营养成分\", \"analysis\":\"简短评价\"}"},
                {"inline_data": {"mime_type": mime_type, "data": base64_image}}
            ]
        }]
    }

    try:
        response = requests.post(
            url, 
            json=payload, 
            headers={"Content-Type": "application/json"}, 
            timeout=50, # 延长超时时间
            proxies=get_proxies()
        )
        return response
    except requests.exceptions.ConnectionError:
        return None

def analyze_smartly(image_bytes, mime_type):
    """
    智能分析：优先尝试 2.0，并带有重试机制
    """
    # 既然 2.0 存在但繁忙，我们把它放第一个，并只用最标准的名字
    # 去掉了 -latest 等后缀，使用最纯粹的模型名
    models_candidates = [
        "gemini-2.0-flash-exp", # 你截图里证明存在的模型
        "gemini-1.5-pro",       # 尝试标准名 (无后缀)
        "gemini-1.5-flash",     # 尝试标准名 (无后缀)
        "gemini-pro-vision"     # 老版本保底
    ]
    
    last_debug_info = ""

    for model in models_candidates:
        # 对每个模型尝试最多 2 次 (处理 429 繁忙)
        for attempt in range(2): 
            with st.status(f"尝试 {model} (第 {attempt+1} 次)...", expanded=False) as status:
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
                        status.update(label=f"✅ {model} 成功！", state="complete")
                        return json.loads(clean_text)
                    except:
                        pass # 解析失败就重试

                # 3. 繁忙 (429) -> 核心修复：等待并重试
                elif resp.status_code == 429:
                    status.update(label=f"⏳ {model} 繁忙，休息 3 秒...", state="running")
                    time.sleep(3) # 强制休息
                    continue # 继续下一次 attempt
                
                # 4. 不存在 (404) -> 直接换下一个模型
                elif resp.status_code == 404:
                    status.update(label=f"❌ {model} 不存在，跳过", state="error")
                    last_debug_info += f"\n{model}: 404 Not Found"
                    break # 跳出 attempt 循环，换下一个 model

                # 其他错误
                else:
                    status.update(label=f"❌ {model} 报错 {resp.status_code}", state="error")
                    last_debug_info += f"\n{model}: {resp.text}"
                    break
    
    # 如果全挂了，运行诊断
    st.error("❌ 所有模型均不可用。正在自动诊断...")
    with st.spinner("正在查询你的 Key 支持哪些模型..."):
        valid_models = check_available_models()
    
    if valid_models:
        st.warning(f"🔍 你的 API Key 仅支持以下模型：\n\n" + ", ".join(valid_models))
        st.info("请修改代码中的 `models_candidates` 列表，使用上面列出的名字。")
    else:
        st.error("诊断失败：无法获取模型列表。请检查网络或 Key 是否有效。")
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

st.title("🛡️ AI 饮食记录 (诊断修复版)")

uploaded_file = st.file_uploader("📸 拍照/上传", type=["jpg", "png", "jpeg", "webp"])

if uploaded_file:
    st.image(uploaded_file, width=300)
    if st.button("🚀 开始识别", type="primary"):
        img_bytes = uploaded_file.getvalue()
        result = analyze_smartly(img_bytes, uploaded_file.type)
        
        if result:
            url = upload_img(img_bytes, uploaded_file.name, uploaded_file.type)
            if save_to_db(result, url):
                st.balloons()
                st.success(f"已记录：{result['food_name']}")
                time.sleep(1)
                st.rerun()

st.divider()
try:
    rows = supabase.table("meals").select("*").order("created_at", desc=True).limit(3).execute().data
    for row in rows:
        with st.container(border=True):
            st.markdown(f"**{row['food_name']}** - {row['calories']} kcal")
except: pass
