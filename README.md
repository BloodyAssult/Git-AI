# AI Proxy Chat over GitHub Actions

این نسخه برای وقتی ساخته شده که کاربر فقط به `github.com` و GitHub Pages دسترسی دارد. مرورگر درخواست را در `queue/prompt_<id>.json` می‌گذارد، GitHub Actions آن را می‌خواند، به API مدل‌ها وصل می‌شود و پاسخ را در `queue/response_<id>.json` می‌نویسد.

## تغییرات این نسخه

- همه گزینه‌ها و کدهای مربوط به NVIDIA حذف شد.
- provider جدید `huggingface` اضافه شد و از Hugging Face Router / Inference Providers با endpoint سازگار با OpenAI استفاده می‌کند: `https://router.huggingface.co/v1/chat/completions`.
- مدل‌های Kimi K2.6، GLM-5.1 و MiniMax M2.7 به جای NVIDIA از مسیر Hugging Face اضافه شدند.
- `Fallback` پیش‌فرض خاموش است تا اگر یک مدل خاص را انتخاب کردی، بی‌صدا مدل دیگری جواب ندهد.
- نام‌گذاری چت جدید هوشمند است: بعد از اولین پاسخ، یک عنوان کوتاه فارسی با مدل ارزان/رایگان ساخته می‌شود؛ اگر هیچ کلیدی موجود نباشد، fallback محلی استفاده می‌شود.
- Gemini Direct زیر provider خودش است و OpenRouter برای مدل‌های دقیق با `provider.allow_fallbacks=false` صدا زده می‌شود.

## راه‌اندازی سریع

### 1) فایل‌ها را در repo بریز

کل محتوای این پوشه را در ریشه repo بگذار:

```text
index.html
proxy.py
.github/workflows/ai-proxy.yml
queue/.gitkeep
```

### 2) GitHub Pages را فعال کن

Settings → Pages → Deploy from branch → Branch: `main` → Folder: `/root`

### 3) GitHub Actions را روشن کن

Actions → AI Proxy → Run workflow

این workflow حدود ۶ ساعت loop می‌زند. هر وقت خاموش شد، دوباره Run workflow بزن. برای روشن ماندن خودکار می‌توانی schedule داخل workflow را از کامنت خارج کنی.

## Secretهای لازم

### اجباری برای امنیت صف عمومی

```text
CHAT_QUEUE_KEY=یک عبارت طولانی و تصادفی
```

همین مقدار را در صفحه سایت، قسمت Security Key هم وارد کن.

### برای مدل‌ها

فقط هر کدام را که لازم داری اضافه کن:

```text
HF_TOKEN=...             # برای Hugging Face Router / Inference Providers
OPENROUTER_API_KEY=...   # برای openrouter/free و مدل‌های :free یا پولی OpenRouter
GEMINI_API_KEY=...       # برای Gemini Direct مثل gemini-3-flash-preview
GROQ_API_KEY=...         # برای GPT-OSS روی Groq
XAI_API_KEY=...          # برای xAI direct، اگر در حساب تو فعال باشد
```

برای Hugging Face یک User Access Token بساز که permission مربوط به `Make calls to Inference Providers` داشته باشد. Secret پیشنهادی در این پروژه `HF_TOKEN` است.

GitHub Models داخل Actions معمولاً secret جدا نمی‌خواهد و از `GITHUB_TOKEN` داخلی workflow استفاده می‌کند، ولی permission زیر باید فعال باشد:

```yaml
permissions:
  contents: write
  models: read
```

## مدل‌های آماده در UI

### Hugging Face Router / Inference Providers

- `moonshotai/Kimi-K2.6:deepinfra`
- `moonshotai/Kimi-K2.6:fireworks-ai`
- `zai-org/GLM-5.1:deepinfra`
- `zai-org/GLM-5.1:together`
- `MiniMaxAI/MiniMax-M2.7:novita`
- `MiniMaxAI/MiniMax-M2.7:together`
- `openai/gpt-oss-120b:cerebras`
- `openai/gpt-oss-20b:groq`
- `Qwen/Qwen3.5-122B-A10B:deepinfra`
- `meta-llama/Llama-3.1-8B-Instruct:novita`

### OpenRouter رایگان / محدود

- `openrouter/free`
- `qwen/qwen3.6-plus:free`
- `xiaomi/mimo-v2-flash:free`
- `tencent/hy3-preview:free`
- `inclusionai/ling-2.6-1t:free`
- `poolside/laguna-m.1:free`
- `poolside/laguna-xs.2:free`

### Gemini Direct

- `gemini-3-flash-preview`
- `gemini-3.1-pro-preview`
- `gemini-3.1-flash-lite-preview`
- `gemini-2.5-flash`
- `gemini-2.5-flash-lite`

### Groq

- `openai/gpt-oss-120b`
- `openai/gpt-oss-20b`

### GitHub Models

- `openai/gpt-4.1-mini`
- `openai/gpt-4.1`
- `openai/gpt-4o-mini`

مدل‌های GitHub Models به catalog حساب/سازمان تو وابسته‌اند؛ اگر 403/404 گرفتی یعنی آن مدل در catalog تو فعال نیست.

### OpenRouter پولی / شبیه اسکرین‌شات

- `moonshotai/kimi-k2.6`
- `z-ai/glm-5.1`
- `minimax/minimax-m2.7`
- `xiaomi/mimo-v2-pro`
- `xiaomi/mimo-v2-flash`
- `qwen/qwen3.6-plus`
- `qwen/qwen3.6-max-preview`
- `qwen/qwen3.6-flash`
- `deepseek/deepseek-v4-pro`

## تنظیمات داخل سایت

وقتی سایت باز شد:

- GitHub Username
- Repository Name
- GitHub Fine-grained PAT با دسترسی Contents Read/Write
- Security Key برابر با `CHAT_QUEUE_KEY`

را وارد کن. برای PAT بهتر است fine-grained بسازی و فقط همین repo و فقط Contents: Read and write بدهی.

## عیب‌یابی سریع

- `HF_TOKEN secret is missing`: مدل Hugging Face انتخاب شده ولی secret نداری.
- `OPENROUTER_API_KEY secret is missing`: مدل OpenRouter انتخاب شده ولی secret نداری.
- پاسخ مدل دیگری آمد: دکمه Fallback را خاموش نگه دار. در این نسخه پیش‌فرض خاموش است.
- timeout در سایت: workflow در Actions روشن نیست یا job به خطا خورده است.
- 401 از GitHub: PAT داخل سایت اشتباه است یا Contents Read/Write ندارد.
- 403/404 از GitHub Models: مدل در catalog حساب تو فعال نیست.
- خطای 402/credits در Hugging Face: اعتبار ماهانه یا credit اکانتت تمام شده است.
