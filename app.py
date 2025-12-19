import streamlit as st
import requests
import json
import base64
import time
from supabase import create_client

# --- 1. 页面设置 ---
st.set_page_config(page_title="AI 饮食日记 (GPT版)", page_icon="🍱")

# 检查配置
required_secrets = ["openai", "supabase"]
if not all(k in st.secrets for k in required_secrets):
    st.error("❌ 请配置 .streamlit/secrets.toml 文件！需要 [openai] 和 [supabase] 字段。")
    st.stop()

# 初始化数据库
try:
    supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
except Exception as e:
    st.error(f"❌ 数据库连接失败: {e}")
    st.stop()

# --- 2. 核心分析逻辑 (OpenAI 版本) ---

def get_proxies():
    """获取代理配置"""
    if "proxy" in st.secrets and st.secrets["proxy"]["url"]:
        p = st.secrets["proxy"]["url"]
        return {"http": p, "https": p}
    return None

def call_gpt_api(image_bytes, mime_type):
    """
    调用 OpenAI GPT-4o 进行识图
    """
    api_key = st.secrets["openai"]["api_key"]
    # 允许自定义 Base URL (方便使用中转站)
    base_url = st.secrets["openai"].get("base_url", "https://api.openai.com/v1").rstrip('/')
    url = f"{base_url}/chat/completions"
    
    # 图片转 Base64
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    data_url = f"data:{mime_type};base64,{base64_image}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    # 构造 GPT-4o 的 Payload
    payload = {
        # 推荐使用 gpt-4o 或 gpt-4o-mini (更便宜)
        "model": "gpt-4o", 
        "messages": [
            {
                "role": "system",
                "content": "你是一个专业的营养师。请分析图片中的食物。必须返回严格的 JSON 格式。"
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": "请识别图片中的食物，返回JSON：{\"food_name\":\"名称\", \"calories\":数字(整数), \"nutrients\":\"简述(蛋白质/碳水/脂肪)\", \"analysis\":\"一句话点评\"}"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": data_url
                        }
                    }
                ]
            }
        ],
        # 强制 GPT 返回 JSON (OpenAI 特有功能，非常稳定)
        "response_format": {"type": "json_object"},
        "max_tokens": 500
    }

    proxies = get_proxies()

    try:
        response = requests.post(
            url, 
            json=payload, 
            headers=headers, 
            timeout=60, # GPT有时比较慢，超时设长一点
            proxies=proxies
        )
        return response
    except requests.exceptions.ConnectionError:
        class MockResp:
            status_code = -1
            text = "无法连接到 OpenAI 服务器。请检查 secrets.toml 中的 base_url 或 proxy 配置。"
        return MockResp()
    except Exception as e:
        class MockResp:
            status_code = -2
            text = f"请求异常: {str(e)}"
        return MockResp()

def analyze_image_gpt(image_bytes, mime_type):
    """
    GPT 分析处理逻辑
    """
    with st.status("🤖 GPT-4o 正在思考...", expanded=False) as status:
        resp = call_gpt_api(image_bytes, mime_type)
        
        if resp.status_code == 200:
            try:
                res_data = resp.json()
                # 提取 GPT 的回复内容
                content_str = res_data['choices'][0]['message']['content']
                
                # 解析 JSON
                result_json = json.loads(content_str)
                status.update(label="✅ 识别成功！", state="complete")
                return result_json
                
            except Exception as e:
                status.update(label="❌ 数据解析失败", state="error")
                st.error(f"解析错误: {e}")
                st.code(resp.text)
                return None
        else:
            status.update(label=f"❌ 请求失败: {resp.status_code}", state="error")
            # 显示详细错误信息（很有用，比如 key 没余额了）
            try:
                err_json = resp.json()
                err_msg = err_json.get('error', {}).get('message', resp.text)
                st.error(f"OpenAI API 报错: {err_msg}")
            except:
                st.error(f"报错内容: {resp.text}")
            return None

# --- 3. 基础功能 (保持不变) ---
def upload_img(file_bytes, name, mime_type):
    ext = mime_type.split('/')[-1]
    if ext == 'jpeg': ext = 'jpg'
    path = f"{int(time.time())}_{name}"
    if not path.endswith(f".{ext}"): path += f".{ext}"
    try:
        supabase.storage.from_("food-images").upload(path, file_bytes, {"content-type": mime_type})
        project_url = st.secrets["supabase"]["url"]
        return f"{project_url}/storage/v1/object/public/food-images/{path}"
    except: return None

def save_to_db(data, url):
    record = {
        "food_name": data.get("food_name", "未知"),
        "calories": data.get("calories", 0),
        "nutrients": data.get("nutrients", ""),
        "analysis": data.get("analysis", ""),
        "image_url": url if url else ""
    }
    try:
        supabase.table("meals").insert(record).execute()
        return True
    except: return False

# --- 4. UI 界面 ---
st.title("🍱 AI 饮食记录 (GPT版)")

with st.sidebar:
    st.write("⚙️ 配置信息")
    if "openai" in st.secrets:
        st.success("GPT Key 已配置")
    else:
        st.error("缺少 GPT 配置")

uploaded_file = st.file_uploader("📸 拍照或上传", type=["jpg", "png", "jpeg", "webp"])

if uploaded_file:
    st.image(uploaded_file, width=300)
    
    if st.button("🚀 识别并记录", type="primary"):
        img_bytes = uploaded_file.getvalue()
        mime_type = uploaded_file.type
        
        # 调用 GPT 函数
        result = analyze_image_gpt(img_bytes, mime_type)
        
        if result:
            with st.spinner("☁️ 正在保存..."):
                img_url = upload_img(img_bytes, uploaded_file.name, mime_type)
            
            if save_to_db(result, img_url):
                st.balloons()
                st.success(f"✅ 已记录: {result['food_name']} ({result['calories']} kcal)")
                time.sleep(1)
                st.rerun()

st.divider()
st.subheader("📅 历史记录")
try:
    rows = supabase.table("meals").select("*").order("created_at", desc=True).limit(5).execute().data
    for row in rows:
        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            if row.get('image_url'): c1.image(row['image_url'], use_container_width=True)
            with c2:
                st.markdown(f"**{row['food_name']}** | 🔥 {row['calories']}")
                st.caption(f"{row['analysis']}")
except: pass
