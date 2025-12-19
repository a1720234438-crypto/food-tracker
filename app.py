import streamlit as st
import requests
import json
import base64
import time
from supabase import create_client

# --- 1. 页面设置 ---
st.set_page_config(page_title="AI 饮食日记 (Gemini Pro)", page_icon="💎")

# 检查配置
required_secrets = ["gemini", "supabase"]
if not all(k in st.secrets for k in required_secrets):
    st.error("❌ 请检查 .streamlit/secrets.toml！必须包含 [gemini] 和 [supabase]。")
    st.stop()

# 初始化数据库
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"❌ 数据库连接失败: {e}")
    st.stop()

# --- 2. 核心分析逻辑 ---

def get_proxies():
    """获取本地代理配置 (解决国内无法连接 Google 的问题)"""
    if "proxy" in st.secrets and st.secrets["proxy"]["url"]:
        p = st.secrets["proxy"]["url"]
        return {"http": p, "https": p}
    return None

def call_gemini_api(image_bytes, mime_type, model_name):
    """
    发送请求给 Google
    """
    api_key = st.secrets["gemini"]["api_key"]
    # 使用 v1beta 接口
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                # 提示词要求返回纯净 JSON
                {"text": "你是一个专业营养师。请分析图片食物。请务必只返回纯JSON字符串，不要包含```json标记。格式：{\"food_name\":\"菜名\", \"calories\":整数卡路里, \"nutrients\":\"蛋白质/脂肪/碳水含量\", \"analysis\":\"营养评价与建议\"}"},
                {
                    "inline_data": {
                        "mime_type": mime_type,
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
            timeout=45, # Pro 模型思考比较慢，超时设长一点
            proxies=proxies
        )
        return response
    except requests.exceptions.ConnectionError:
        return None # 网络不通
    except Exception as e:
        return None

def analyze_with_fallback(image_bytes, mime_type):
    """
    智能尝试模型：优先 Pro，失败转 Flash
    """
    # 【关键修改】这里列出了确切的模型版本号，解决 404 问题
    # 既然你是会员，我们优先跑 Pro (效果最好)
    models_strategy = [
        # 1. 尝试 1.5 Pro (最新稳定版) - 最聪明
        "gemini-1.5-pro-latest", 
        # 2. 尝试 1.5 Pro (旧版本保底)
        "gemini-1.5-pro-001",
        # 3. 如果 Pro 挂了/限流，降级用 Flash (速度快)
        "gemini-1.5-flash-latest",
        # 4. 尝鲜 2.0 (如果可用)
        "gemini-2.0-flash-exp"
    ]
    
    last_error = ""

    for model in models_strategy:
        with st.status(f"💎 正在请求 AI ({model})...", expanded=False) as status:
            resp = call_gemini_api(image_bytes, mime_type, model)
            
            # 1. 网络完全不通
            if resp is None:
                st.error("无法连接 Google 服务器，请检查 secrets.toml 中的 [proxy] 代理地址。")
                return None

            # 2. 成功 (200)
            if resp.status_code == 200:
                try:
                    res_json = resp.json()
                    candidates = res_json.get('candidates', [])
                    if not candidates:
                        # 安全被拦截 (常见于食品看起来像违禁品)
                        status.update(label=f"⚠️ {model} 拒绝回答 (安全拦截)", state="error")
                        continue

                    raw_text = candidates[0]['content']['parts'][0]['text']
                    # 清洗数据
                    clean_text = raw_text.replace("```json", "").replace("```", "").strip()
                    data = json.loads(clean_text)
                    
                    status.update(label=f"✅ {model} 识别成功！", state="complete")
                    return data
                except Exception as e:
                    status.update(label=f"⚠️ {model} 数据解析失败", state="error")
                    last_error = f"解析错误: {e}"
            
            # 3. 常见错误处理
            elif resp.status_code == 429:
                status.update(label=f"⏳ {model} 繁忙(429)，尝试备用模型...", state="error")
                time.sleep(1) # 歇一秒
            elif resp.status_code == 404:
                status.update(label=f"❌ {model} 版本未找到(404)，跳过...", state="error")
            else:
                status.update(label=f"❌ {model} 报错: {resp.status_code}", state="error")
                last_error = resp.text

    # 全部失败
    st.error("所有模型尝试均失败。")
    if last_error:
        with st.expander("查看最后一次报错详情"):
            st.code(last_error)
    return None

# --- 3. 基础功能 ---
def upload_img(file_bytes, name, mime_type):
    # 修正后缀
    ext = mime_type.split('/')[-1]
    if ext == 'jpeg': ext = 'jpg'
    
    path = f"{int(time.time())}_{name}"
    if not path.endswith(f".{ext}"): path += f".{ext}"
    
    try:
        supabase.storage.from_("food-images").upload(path, file_bytes, {"content-type": mime_type})
        return f"{st.secrets['supabase']['url']}/storage/v1/object/public/food-images/{path}"
    except: 
        return None

def save_to_db(data, url):
    try:
        record = {
            "food_name": data.get("food_name", "未识别"),
            "calories": data.get("calories", 0),
            "nutrients": data.get("nutrients", ""),
            "analysis": data.get("analysis", ""),
            "image_url": url if url else ""
        }
        supabase.table("meals").insert(record).execute()
        return True
    except Exception as e:
        st.error(f"存库失败: {e}")
        return False

# --- 4. UI 界面 ---
st.title("💎 AI 饮食记录 (Gemini Pro)")

with st.sidebar:
    st.write("当前模式：**Gemini 1.5 Pro**")
    if get_proxies():
        st.success("✅ 代理已启用")

uploaded_file = st.file_uploader("📸 拍照/上传", type=["jpg", "png", "jpeg", "webp"])

if uploaded_file:
    st.image(uploaded_file, width=300)
    
    if st.button("🚀 智能识别", type="primary"):
        bytes_data = uploaded_file.getvalue()
        mime_type = uploaded_file.type
        
        result = analyze_with_fallback(bytes_data, mime_type)
        
        if result:
            with st.spinner("正在保存数据..."):
                url = upload_img(bytes_data, uploaded_file.name, mime_type)
                if save_to_db(result, url):
                    st.balloons()
                    st.success(f"已记录：{result['food_name']}")
                    time.sleep(1)
                    st.rerun()

st.divider()
try:
    # 历史记录
    rows = supabase.table("meals").select("*").order("created_at", desc=True).limit(5).execute().data
    for row in rows:
        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            if row.get('image_url'): c1.image(row['image_url'], use_container_width=True)
            with c2:
                st.markdown(f"**{row['food_name']}**")
                st.caption(f"🔥 {row['calories']} kcal | {row['nutrients']}")
                st.info(row['analysis'])
except: pass
