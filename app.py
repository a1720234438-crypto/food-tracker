import streamlit as st
import requests
import json
import base64
import time
from supabase import create_client

# --- 1. 页面设置 ---
st.set_page_config(page_title="AI 饮食日记", page_icon="🍱")

# 检查配置
required_secrets = ["gemini", "supabase"]
if not all(k in st.secrets for k in required_secrets):
    st.error("❌ 请配置 .streamlit/secrets.toml 文件！需要 [gemini] 和 [supabase] 字段。")
    st.stop()

# 初始化数据库
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"❌ 数据库连接失败: {e}")
    st.stop()

# --- 2. 核心分析逻辑 ---

def get_proxies():
    """
    获取代理配置。
    """
    # 检查 secrets 中是否有 proxy 配置
    if "proxy" in st.secrets and st.secrets["proxy"]["url"]:
        p = st.secrets["proxy"]["url"]
        return {"http": p, "https": p}
    return None

def call_gemini_api(image_bytes, mime_type, model_name):
    """
    底层 API 调用：支持动态 MIME 类型和代理
    """
    api_key = st.secrets["gemini"]["api_key"]
    # API 地址
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    # 图片转 Base64
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    # 构造请求体
    payload = {
        "contents": [{
            "parts": [
                {"text": "你是一个营养师。请识别图片中的食物，直接返回纯JSON格式（不要Markdown标记，不要```json前缀）：{\"food_name\":\"名称\", \"calories\":数字, \"nutrients\":\"简述\", \"analysis\":\"点评\"}"},
                {
                    "inline_data": {
                        "mime_type": mime_type, # 动态使用传入的图片类型
                        "data": base64_image
                    }
                }
            ]
        }]
    }

    proxies = get_proxies()
    
    try:
        response = requests.post(
            url, 
            json=payload, 
            headers={"Content-Type": "application/json"}, 
            timeout=30,
            proxies=proxies # 使用代理
        )
        return response
    except requests.exceptions.ConnectionError:
        class MockResp:
            status_code = -1
            text = "无法连接到 Google 服务器。请检查 secrets.toml 中的 [proxy] url 配置是否正确。"
        return MockResp()
    except Exception as e:
        class MockResp:
            status_code = -2
            text = f"请求异常: {str(e)}"
        return MockResp()

def analyze_image_self_healing(image_bytes, mime_type):
    """
    自愈式分析：解决 404 和 429 问题
    """
    # 【核心修复】：使用带版本号的完整名称，避免 404
    models_to_try = [
        "gemini-1.5-flash-latest",    # 尝试最新版 Flash
        "gemini-1.5-flash-001",       # 尝试稳定版 Flash (最保险)
        "gemini-1.5-pro-latest",      # 尝试 Pro 模型
        "gemini-2.0-flash-exp",       # 尝试 2.0 实验版
    ]
    
    last_error_text = ""
    error_summary = []

    for model in models_to_try:
        with st.status(f"正在尝试模型: {model} ...", expanded=False) as status:
            resp = call_gemini_api(image_bytes, mime_type, model)
            
            # --- 情况 1: 成功 ---
            if resp.status_code == 200:
                try:
                    res_data = resp.json()
                    if 'candidates' in res_data and res_data['candidates']:
                        raw_text = res_data['candidates'][0]['content']['parts'][0]['text']
                        # 清理 JSON 字符串
                        clean_text = raw_text.replace("```json", "").replace("```", "").strip()
                        status.update(label=f"✅ {model} 识别成功！", state="complete")
                        return json.loads(clean_text)
                    else:
                        error_msg = f"API返回空数据"
                        last_error_text = json.dumps(res_data)
                except Exception as e:
                    error_msg = f"JSON解析失败: {e}"
                    last_error_text = resp.text

            # --- 情况 2: 额度已满 (429) ---
            elif resp.status_code == 429:
                error_msg = "额度已满 (429)"
                status.update(label=f"⚠️ {model} 额度不足，休息2秒...", state="error")
                time.sleep(2) 

            # --- 情况 3: 找不到模型 (404) ---
            elif resp.status_code == 404:
                error_msg = "模型未找到 (404)"
                status.update(label=f"❌ {model} 404不可用，尝试下一个...", state="error")
                last_error_text = resp.text

            # --- 其他错误 ---
            else:
                error_msg = f"错误代码 {resp.status_code}"
                last_error_text = resp.text
                status.update(label=f"❌ {model} 失败: {resp.status_code}", state="error")
            
            # 记录错误以便最后显示
            error_summary.append(f"{model}: {error_msg}")
            
            # 如果是连不上网，直接退出循环
            if resp.status_code == -1:
                st.error(f"网络连接错误：{resp.text}")
                return None
    
    # 如果循环结束还没返回
    st.error("❌ 所有 AI 模型均尝试失败。")
    with st.expander("🔍 查看详细调试信息"):
        st.write("尝试过程：")
        st.json(error_summary)
        st.write("最后一次 API 返回的详细错误：")
        st.code(last_error_text, language="json")
    return None

# --- 3. 基础功能 ---
def upload_img(file_bytes, name, mime_type):
    # 根据 mimetype 决定后缀
    ext = mime_type.split('/')[-1]
    if ext == 'jpeg': ext = 'jpg'
    
    path = f"{int(time.time())}_{name}"
    if not path.endswith(f".{ext}"):
        path += f".{ext}"
        
    try:
        supabase.storage.from_("food-images").upload(path, file_bytes, {"content-type": mime_type})
        project_url = st.secrets["supabase"]["url"]
        return f"{project_url}/storage/v1/object/public/food-images/{path}"
    except Exception as e:
        st.warning(f"⚠️ 图片上传云端失败 (可能是文件名重复或权限问题)，但不影响分析。错误: {e}")
        return None # 返回 None，后续逻辑要处理

def save_to_db(data, url):
    record = {
        "food_name": data.get("food_name", "未知食物"),
        "calories": data.get("calories", 0),
        "nutrients": data.get("nutrients", "无"),
        "analysis": data.get("analysis", "无"),
        "image_url": url if url else "" # 处理 url 为 None 的情况
    }
    try:
        supabase.table("meals").insert(record).execute()
        return True
    except Exception as e:
        st.error(f"❌ 保存数据库失败: {e}")
        return False

# --- 4. UI 界面 ---
st.title("🍱 AI 饮食记录")

# 侧边栏状态
with st.sidebar:
    st.write("🛠️ 系统配置")
    proxies = get_proxies()
    if proxies:
        st.success(f"代理已开启: {proxies['http']}")
    else:
        st.info("未使用代理 (适合云端/非大陆环境)")

uploaded_file = st.file_uploader("📸 拍一张照片或上传图片", type=["jpg", "png", "jpeg", "webp"])

if uploaded_file:
    # 预览图片
    st.image(uploaded_file, width=300)
    
    if st.button("🚀 开始识别", type="primary"):
        img_bytes = uploaded_file.getvalue()
        mime_type = uploaded_file.type # 获取真实格式 (image/png 等)
        
        # 1. 识别
        result = analyze_image_self_healing(img_bytes, mime_type)
        
        if result:
            # 2. 上传
            with st.spinner("☁️ 正在保存图片到云端..."):
                img_url = upload_img(img_bytes, uploaded_file.name, mime_type)
            
            # 3. 存库
            if save_to_db(result, img_url):
                st.balloons()
                st.success(f"✅ 记录成功！{result['food_name']} - {result['calories']} 卡路里")
                time.sleep(2)
                st.rerun()

st.divider()
st.subheader("📅 历史记录")

# 读取历史
try:
    rows = supabase.table("meals").select("*").order("created_at", desc=True).limit(5).execute().data
    if not rows:
        st.caption("还没有记录，快去上传第一顿饭吧！")
        
    for row in rows:
        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            if row.get('image_url'): 
                c1.image(row['image_url'], use_container_width=True)
            else:
                c1.text("🚫 图片未保存")
            
            with c2:
                st.markdown(f"**{row['food_name']}**")
                st.markdown(f"🔥 `{row['calories']} kcal`")
                st.info(f"{row['analysis']}")
                st.caption(f"营养成分: {row['nutrients']}")
except Exception as e:
    st.error(f"读取历史记录失败: {e}")
