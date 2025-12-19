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
    st.error("请配置 .streamlit/secrets.toml 文件！")
    st.stop()

# 初始化数据库
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"数据库连接失败: {e}")
    st.stop()

# --- 2. 核心分析逻辑 ---

def get_proxies():
    """
    获取代理配置。
    如果你在本地运行且无法直连 Google，必须配置代理。
    """
    if "proxy" in st.secrets and st.secrets["proxy"]["url"]:
        p = st.secrets["proxy"]["url"]
        return {"http": p, "https": p}
    return None

def call_gemini_api(image_bytes, mime_type, model_name):
    """
    底层 API 调用：支持动态 MIME 类型和代理
    """
    api_key = st.secrets["gemini"]["api_key"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    payload = {
        "contents": [{
            "parts": [
                {"text": "你是一个营养师。请识别图片中的食物，直接返回纯JSON格式（不要Markdown标记）：{\"food_name\":\"名称\", \"calories\":数字, \"nutrients\":\"简述\", \"analysis\":\"点评\"}"},
                {
                    "inline_data": {
                        "mime_type": mime_type, # 【修复】动态使用传入的图片类型
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
            proxies=proxies # 【修复】加入代理
        )
        return response
    except requests.exceptions.ConnectionError:
        # 伪造一个连接错误的响应对象以便后续处理
        class MockResp:
            status_code = -1
            text = "连接失败：无法连接到 Google 服务器。如果你在国内，请检查 secrets.toml 中的代理配置 (proxy_url)。"
        return MockResp()
    except Exception as e:
        class MockResp:
            status_code = -2
            text = f"请求异常: {str(e)}"
        return MockResp()

def analyze_image_self_healing(image_bytes, mime_type):
    """
    自愈式分析：如果一个模型失败，自动尝试另一个
    """
    # 尝试顺序：Flash (快且稳) -> Flash-8b (极速) -> 2.0 (新模型)
    models_to_try = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-2.0-flash"]
    
    last_error_text = ""

    for model in models_to_try:
        with st.status(f"正在尝试使用 {model} 进行识别...", expanded=False) as status:
            resp = call_gemini_api(image_bytes, mime_type, model)
            
            # 1. 成功情况
            if resp.status_code == 200:
                try:
                    res_data = resp.json()
                    # 安全提取文本
                    if 'candidates' in res_data and res_data['candidates']:
                        raw_text = res_data['candidates'][0]['content']['parts'][0]['text']
                        # 清理 Markdown 标记 (```json ... ```)
                        clean_text = raw_text.replace("```json", "").replace("```", "").strip()
                        status.update(label=f"{model} 识别成功！", state="complete")
                        return json.loads(clean_text)
                    else:
                        last_error_text = f"API 返回结构异常: {res_data}"
                except json.JSONDecodeError:
                    last_error_text = "JSON 解析失败，AI 返回了非标准格式"
                except Exception as e:
                    last_error_text = f"数据处理错误: {e}"

            # 2. 额度超限 (429)
            elif resp.status_code == 429:
                status.update(label=f"{model} 额度已满，切换下一模型...", state="error")
                time.sleep(1)
                continue
            
            # 3. 其他错误 (400, 403, 500 等)
            else:
                last_error_text = resp.text # 保存 Google 返回的具体错误信息
                status.update(label=f"{model} 失败 ({resp.status_code})", state="error")
                # 如果是连接错误(-1)，直接中断循环，因为换模型也没用
                if resp.status_code == -1:
                    st.error(resp.text)
                    return None
                continue
    
    # 如果循环结束还没返回，说明全失败了
    st.error("❌ 所有 AI 模型均不可用。")
    if last_error_text:
        with st.expander("查看详细报错信息 (Debug)", expanded=True):
            st.code(last_error_text, language="json")
    return None

# --- 3. 基础功能 ---
def upload_img(file_bytes, name, mime_type):
    # 生成唯一文件名
    ext = mime_type.split('/')[-1]
    path = f"{int(time.time())}_{name}"
    # 简单的扩展名修正
    if not path.endswith(f".{ext}"): 
        path += f".{ext}"
        
    try:
        supabase.storage.from_("food-images").upload(path, file_bytes, {"content-type": mime_type})
        # 拼接公开访问 URL (确保你的 Bucket 是 Public 的)
        project_url = st.secrets["supabase"]["url"]
        return f"{project_url}/storage/v1/object/public/food-images/{path}"
    except Exception as e:
        st.warning(f"图片上传失败，但将继续保存记录: {e}")
        return None

def save_to_db(data, url):
    record = {
        "food_name": data.get("food_name", "未知食物"),
        "calories": data.get("calories", 0),
        "nutrients": data.get("nutrients", "无"),
        "analysis": data.get("analysis", "无"),
        "image_url": url
    }
    try:
        supabase.table("meals").insert(record).execute()
        return True
    except Exception as e:
        st.error(f"保存数据库失败: {e}")
        return False

# --- 4. UI 界面 ---
st.title("🍱 AI 饮食记录")

# 侧边栏显示状态
with st.sidebar:
    st.write("🔧 系统状态")
    proxies = get_proxies()
    if proxies:
        st.success(f"已启用代理: {proxies['http']}")
    else:
        st.info("未使用代理 (云端部署无需代理)")

uploaded_file = st.file_uploader("拍一张照片", type=["jpg", "png", "jpeg", "webp"])

if uploaded_file:
    # 显示图片
    st.image(uploaded_file, width=300)
    
    if st.button("🚀 识别并记录", type="primary"):
        img_bytes = uploaded_file.getvalue()
        mime_type = uploaded_file.type # 获取真实的 MIME 类型 (如 image/png)
        
        # 1. 分析图片
        result = analyze_image_self_healing(img_bytes, mime_type)
        
        if result:
            # 2. 上传图片
            with st.spinner("正在保存图片..."):
                img_url = upload_img(img_bytes, uploaded_file.name, mime_type)
            
            # 3. 写入数据库
            if save_to_db(result, img_url):
                st.balloons()
                st.success(f"✅ 已记录: {result['food_name']} ({result['calories']} kcal)")
                time.sleep(1.5)
                st.rerun()

st.divider()
st.subheader("📝 最近记录")

# 展示历史记录
try:
    rows = supabase.table("meals").select("*").order("created_at", desc=True).limit(5).execute().data
    if not rows:
        st.caption("暂无记录，快去上传第一顿饭吧！")
        
    for row in rows:
        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            if row['image_url']: 
                c1.image(row['image_url'], use_container_width=True)
            else:
                c1.text("🖼️ 无图")
            
            with c2:
                st.markdown(f"**{row['food_name']}**")
                st.markdown(f"🔥 `{row['calories']} kcal`")
                st.caption(f"💡 {row['analysis']}")
                st.text(f"📊 {row['nutrients']}")
except Exception as e:
    st.error(f"读取历史记录失败: {e}")
