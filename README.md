# AI Proxy Chat over GitHub Actions

این نسخه برای حالتی ساخته شده که کاربر فقط به `github.com` و GitHub Pages دسترسی دارد. مرورگر درخواست را در `queue/prompt_<id>.json` می‌گذارد، GitHub Actions آن را می‌خواند، به API مدل‌ها وصل می‌شود و پاسخ را در `queue/response_<id>.json` می‌نویسد.

## تغییرات امنیتی مهم

- توکن Puter یا کلیدهای مدل‌ها دیگر از مرورگر به repo ارسال نمی‌شوند.
- `OPENROUTER_API_KEY`، `GROQ_API_KEY`، `GEMINI_API_KEY`، `XAI_API_KEY` و `PUTER_TOKEN` فقط در GitHub Secrets خوانده می‌شوند.
- برای repo عمومی، prompt و response با AES-GCM رمزنگاری می‌شوند، به شرط اینکه `CHAT_QUEUE_KEY` را هم در GitHub Secrets و هم در صفحه تنظیمات سایت وارد کنی.
- فایل‌های صف بعد از پردازش حذف می‌شوند، ولی چون repo عمومی history دارد، حتماً از رمزنگاری استفاده کن.

## راه‌اندازی

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

### 3) GitHub Actions را فعال کن

Actions → AI Proxy → Run workflow

این workflow یک loop حدوداً 6 ساعته اجرا می‌کند. هر وقت خاموش شد، دوباره Run workflow بزن.

### 4) Secret اجباری بساز

Settings → Secrets and variables → Actions → New repository secret

```text
CHAT_QUEUE_KEY=یک عبارت طولانی و تصادفی
```

همین مقدار را در صفحه سایت، قسمت Security Key هم وارد کن.

### 5) Secretهای اختیاری برای providerها

فقط هر کدام را که داری اضافه کن:

```text
OPENROUTER_API_KEY=...
GROQ_API_KEY=...
GEMINI_API_KEY=...
XAI_API_KEY=...
PUTER_TOKEN=...
```

GitHub Models معمولاً به secret جدا نیاز ندارد و از `GITHUB_TOKEN` داخلی workflow استفاده می‌کند. در workflow permission زیر فعال است:

```yaml
permissions:
  contents: write
  models: read
```


### نسخه اصلاح‌شده

- منوی تاریخچه در موبایل با کلاس `side.open` باز می‌شود و دکمه `＋` در نوار بالا برای ساخت چت جدید اضافه شده است.
- چت جدید با اولین پیام نام‌گذاری می‌شود و ترتیب تاریخچه بر اساس آخرین فعالیت است.
- مدل‌های OpenRouter رایگان/`free` و چند مدل شبیه اسکرین‌شات به لیست مدل‌ها اضافه شده‌اند. برای مدل‌های غیررایگان باید اعتبار یا مسیر رایگان در حساب OpenRouter داشته باشید.

## تنظیمات داخل سایت

وقتی سایت باز شد:

- GitHub Username
- Repository Name
- GitHub Fine-grained PAT با دسترسی Contents Read/Write
- Security Key برابر با `CHAT_QUEUE_KEY`

را وارد کن.

برای PAT بهتر است fine-grained بسازی و فقط همین repo و فقط Contents: Read and write بدهی.

## مدل‌های آماده در UI

- GitHub Models: `openai/gpt-5.4-mini`, `deepseek/deepseek-v4-flash`
- OpenRouter: `openrouter/free` و مدل‌های دقیق مثل `openai/gpt-5.5`, `anthropic/claude-opus-4.7`, `google/gemini-3.1-pro-preview`, `moonshotai/kimi-k2.6`
- Puter: مدل‌های شبیه عکس مثل GPT-5.5، Claude Opus 4.7، Gemini 3.1 Pro، Kimi K2.6، Grok 4.3، MiMo V2.5 Pro، DeepSeek V4 Pro
- Groq: `openai/gpt-oss-120b`
- Gemini مستقیم: `gemini-3-flash-preview`, `gemini-3.1-pro-preview`
- xAI مستقیم: `grok-4.3`

## نکته درباره رایگان بودن

- GitHub Models رایگانِ rate-limited برای prototyping است، ولی quota دقیق به مدل و حساب بستگی دارد.
- OpenRouter مدل `openrouter/free` و مدل‌های `:free` دارد، ولی مدل‌های flagship مثل GPT-5.5 و Claude Opus معمولاً رایگان دائمی نیستند مگر credit یا route خاص داشته باشی.
- Puter برای توسعه‌دهنده رایگان است، اما مصرف روی حساب کاربر Puter می‌افتد و ممکن است محدودیت داشته باشد.
- Groq free tier دارد، اما مدل‌های دقیق و limitها در console حساب خودت مشخص می‌شوند.

## عیب‌یابی سریع

- خطای `CHAT_QUEUE_KEY secret is missing`: مقدار Secret را در GitHub Actions اضافه نکرده‌ای یا workflow را بعد از اضافه کردن Secret دوباره اجرا نکرده‌ای.
- خطای `OPENROUTER_API_KEY secret is missing`: مدلی از OpenRouter انتخاب شده ولی secret نداری. یا مدل GitHub/Puter/Groq را انتخاب کن، یا secret را بساز.
- timeout در سایت: workflow در Actions روشن نیست یا به خطا خورده است.
- 401 از GitHub: PAT داخل سایت اشتباه است یا Contents Read/Write ندارد.
- 403/404 از GitHub Models: مدل انتخابی در GitHub Models catalog حساب تو فعال نیست. مدل دیگری انتخاب کن یا از OpenRouter/Puter استفاده کن.
