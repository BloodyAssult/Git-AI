# AI Proxy Chat over GitHub Actions

این نسخه برای وقتی ساخته شده که کاربر فقط به `github.com` و GitHub Pages دسترسی دارد. مرورگر درخواست را در `queue/prompt_<id>.json` می‌گذارد، GitHub Actions آن را می‌خواند، به API مدل‌ها وصل می‌شود و پاسخ را در `queue/response_<id>.json` می‌نویسد.

## تغییرات این نسخه

- ظاهر سایت به سبک **Aurora / Glassmorphism** بازطراحی شد: پس‌زمینه aurora متحرک، کارت‌های شیشه‌ای، پیام‌های مدرن‌تر، سایه و glow ملایم، و تجربه بهتر موبایل.
- provider جدید `avalai` اضافه شد و از endpoint سازگار با OpenAI استفاده می‌کند: `https://api.avalai.ir/v1/chat/completions`.
- بخش OpenRouter پولی حذف شد و سه مدل در AvalAI اضافه شدند:
  - `grok-4.3`
  - `kimi-k2.6`
  - `glm-5.1`
- مسیرهای NVIDIA همچنان حذف هستند.
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
AVALAI_API_KEY=...       # برای AvalAI: grok-4.3 / kimi-k2.6 / glm-5.1
HF_TOKEN=...             # برای Hugging Face Router / Inference Providers
OPENROUTER_API_KEY=...   # برای openrouter/free و مدل‌های :free OpenRouter
GEMINI_API_KEY=...       # برای Gemini Direct مثل gemini-3-flash-preview
GROQ_API_KEY=...         # برای GPT-OSS روی Groq
XAI_API_KEY=...          # پشتیبانی کدی باقی مانده، ولی در UI پیش‌فرض نمایش داده نمی‌شود
```

برای AvalAI از داشبورد AvalAI کلید API بساز و همان را با نام `AVALAI_API_KEY` در GitHub Secrets قرار بده.

برای Hugging Face یک User Access Token بساز که permission مربوط به `Make calls to Inference Providers` داشته باشد. Secret پیشنهادی در این پروژه `HF_TOKEN` است.

GitHub Models داخل Actions معمولاً secret جدا نمی‌خواهد و از `GITHUB_TOKEN` داخلی workflow استفاده می‌کند، ولی permission زیر باید فعال باشد:

```yaml
permissions:
  contents: write
  models: read
```

## مدل‌های آماده در UI

### AvalAI

- `grok-4.3`
- `kimi-k2.6`
- `glm-5.1`

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

## تنظیمات داخل سایت

وقتی سایت باز شد:

- GitHub Username
- Repository Name
- GitHub Fine-grained PAT با دسترسی Contents Read/Write
- Security Key برابر با `CHAT_QUEUE_KEY`

را وارد کن. برای PAT بهتر است fine-grained بسازی و فقط همین repo و فقط Contents: Read and write بدهی.

## عیب‌یابی سریع

- `AVALAI_API_KEY secret is missing`: مدل AvalAI انتخاب شده ولی secret نداری.
- `HF_TOKEN secret is missing`: مدل Hugging Face انتخاب شده ولی secret نداری.
- `OPENROUTER_API_KEY secret is missing`: مدل OpenRouter انتخاب شده ولی secret نداری.
- پاسخ مدل دیگری آمد: دکمه Fallback را خاموش نگه دار. در این نسخه پیش‌فرض خاموش است.
- timeout در سایت: workflow در Actions روشن نیست یا job به خطا خورده است.
- 401 از GitHub: PAT داخل سایت اشتباه است یا Contents Read/Write ندارد.
- 403/404 از GitHub Models: مدل در catalog حساب تو فعال نیست.
- خطای credit/rate limit در AvalAI یا Hugging Face: اعتبار یا محدودیت حساب/پلن تمام شده است.

## Remote Browser / سطح ۲ پیشرفته

این نسخه یک تب «مرورگر» دارد که با GitHub Actions و Playwright اجرا می‌شود. وقتی URL یا دستور می‌دهید، Chromium داخل runner باز می‌شود، JavaScript صفحه اجرا می‌شود، اسکرین‌شات گرفته می‌شود و لینک‌ها/دکمه‌های قابل کلیک به UI برمی‌گردند.

قابلیت‌ها:
- باز کردن URLهای عمومی با Chromium واقعی
- اجرای JavaScript سایت و گرفتن screenshot
- کلیک مستقیم روی اسکرین‌شات یا کلیک روی شماره لینک/دکمه
- اسکرول، برگشت، رفرش، تایپ داخل فیلدها
- تحلیل متن صفحه با مدل انتخابی AI

نکته‌ها:
- اولین اجرای workflow کمی کندتر است چون Playwright و Chromium نصب می‌شود.
- این مرورگر real-time مثل Chrome نیست؛ هر حرکت یک درخواست به Actions می‌فرستد و خروجی جدید می‌گیرد.
- برای امنیت، URLهای localhost و شبکه خصوصی باز نمی‌شوند.
- ورود به حساب‌های حساس، بانک، پرداخت و سایت‌هایی که کپچا یا قوانین ضد automation دارند توصیه نمی‌شود.

## بهبودهای نسخه Video + Math

- بعد از هر عمل مرورگر، یک کلیپ کوتاه چندفریمی با JPEG کیفیت بالا تولید می‌شود و UI آن را مثل ویدیوی کوتاه پخش می‌کند؛ آخرین فریم همان وضعیت نهایی صفحه است.
- رندر پاسخ‌های AI اصلاح شد: Markdown، جدول‌ها، کدبلاک‌ها و فرمول‌های LaTeX با KaTeX/Marked نمایش داده می‌شوند.
- حالت جدید **Codespace Worker Relay** اضافه شد؛ در این حالت مرورگر پشت‌صحنه داخل Codespace اجرا می‌شود ولی خروجی همچنان از مسیر GitHub.io/GitHub API دیده می‌شود.
- اگر CDNهای KaTeX یا Marked در دسترس نبودند، fallback داخلی فرمول‌ها را در باکس خواناتر نشان می‌دهد تا خام و به‌هم‌ریخته نمایش داده نشوند.

## Codespace Worker Relay / حالت سریع‌تر بدون دامنه‌ی Codespaces

اگر دامنه‌ی forwarded port خود Codespaces برایت باز نیست، لازم نیست تصویر noVNC یا پورت Codespace را مستقیم ببینی. در این نسخه یک حالت جدید به مرورگر اضافه شده است:

```text
حالت: Actions  ← اجرای قبلی با GitHub Actions
حالت: Worker   ← اجرای سریع‌تر با codespace_worker.py پشت‌صحنه
```

در حالت Worker، همین سایت `github.io` درخواست مرورگر را داخل `browser_queue/prompt_<id>.json` می‌نویسد. اسکریپت `codespace_worker.py` که در Codespace روشن کرده‌ای، آن را می‌خواند، Chromium/Playwright را اجرا می‌کند و پاسخ را در `browser_queue/response_<id>.json` می‌نویسد. بنابراین مرورگر تو فقط به GitHub Pages و GitHub API وصل است؛ نیاز نیست به دامنه‌ی مستقیم Codespace وصل شوی.

### اجرای Worker در Codespace

در Codespace یک ترمینال باز کن و این‌ها را اجرا کن:

```bash
export GH_TOKEN=ghp_...            # توکن با Contents: Read and write برای همین repo
export REPO=username/repo          # مثلا ali/Git-AI
export CHAT_QUEUE_KEY='همان Security Key سایت و Secret'

./scripts/start_codespace_worker.sh
```

اگر از AvalAI/Hugging Face/OpenRouter برای «تحلیل AI صفحه» داخل Worker استفاده می‌کنی، کلیدهای همان provider را هم در ترمینال Codespace export کن:

```bash
export AVALAI_API_KEY=...
export HF_TOKEN=...
export OPENROUTER_API_KEY=...
export GEMINI_API_KEY=...
export GROQ_API_KEY=...
```

بعد در سایت، تب مرورگر را باز کن و دکمه‌ی `حالت: Actions` را بزن تا به `حالت: Worker` تبدیل شود. از آن به بعد دکمه‌های برو/کلیک/اسکرول/تجدید فریم از Worker جواب می‌گیرند، نه از Actions.

### مزیت‌ها و محدودیت‌ها

- سریع‌تر از Actions است چون مرورگر Chromium داخل Codespace روشن می‌ماند.
- همچنان از مسیر GitHub.io دیده می‌شود و نیاز به باز بودن `*.app.github.dev` برای تصویر زنده ندارد.
- لایو واقعی WebSocket/noVNC نیست؛ اما نسبت به Actions startup کمتری دارد و نزدیک‌تر به لایو است.
- اگر Worker خاموش باشد، سایت روی حالت Worker منتظر می‌ماند و timeout می‌دهد. با زدن دوباره‌ی دکمه می‌توانی به حالت Actions برگردی.
- برای repo عمومی، `CHAT_QUEUE_KEY` را حتماً بگذار تا درخواست‌ها و پاسخ‌ها رمزنگاری شوند.
