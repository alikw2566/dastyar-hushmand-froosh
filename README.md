# مکالمه‌بان — دستیار هوشمند فروش

«مکالمه‌بان» سامانه فارسی و راست‌چین تحلیل تماس فروش است که به سفارش شرکت فرازما توسعه داده شده است. نام محصول مکالمه‌بان است؛ فرازما فقط سفارش‌دهنده پروژه است.

وضعیت Release Gate فعلی: `READY_FOR_INTERNAL_TESTING`. کد، مهاجرت‌ها و آزمون‌های خودکار آماده‌اند، اما تا اجرای آزمایش با تماس‌های واقعی فارسی، سرویس‌های واقعی Docker و آزمون مداوم ۲۴ ساعته/هفت‌روزه، پروژه نباید «آماده پایلوت کنترل‌شده» معرفی شود.

## قابلیت‌های پیاده‌سازی‌شده

- دریافت خودکار فایل Issabel/Asterisk از پوشه محلی، Network Share یا SMB mount
- تشخیص پایداری فایل، SHA-256، جلوگیری از تکرار، قرنطینه و Retry مرحله‌ای
- پیش‌پردازش صوت و رونویسی گوینده‌بندی‌شده با `gpt-4o-transcribe-diarize`
- تشخیص نقش فروشنده/مشتری و امکان اصلاح انسانی بدون ازبین‌رفتن تاریخچه
- تحلیل فروش ساختاریافته، استخراج مشتری/شرکت/محصول/مبلغ/تاریخ/قول پیگیری
- الزام شاهد زمانی و حذف ادعاهای بدون پشتوانه پیش از نمایش قطعی
- ساخت پیگیری بدون تکرار، دسته‌بندی امروز/عقب‌افتاده/بدون زمان/انجام‌شده
- فیلتر، مرتب‌سازی و صفحه‌بندی تماس‌ها در سرور
- جزئیات تماس، متن کامل، صوت، KPI، اعتراض‌ها، فرصت‌ها و اصلاحات
- خروجی HTML، PDF فارسی و Excel چندبرگی از Backend
- پنل مدیریت کاربران، تیم، KPI، اتوماسیون، اتصال‌ها، عملیات، دقت مدل، واژه‌نامه، Issabel، AI، امنیت و Audit Log
- احراز هویت OIDC/Keycloak، نقش‌ها، `tenant_id` و PostgreSQL Row-Level Security
- Health check، متریک، لاگ ساختاریافته، Backup/Restore و ابزار Load/Soak

اتصال SFTP، Connectorهای اجرایی CRM/SMS/WhatsApp/Email و جست‌وجوی معنایی کامل هنوز عملیاتی نیستند و در رابط یا مستندات به‌عنوان محدودیت نمایش داده می‌شوند.

## ساختار پروژه

- `web/`: داشبورد Next.js/Vinext فارسی، RTL و API محلی D1 برای توسعه
- `backend/`: FastAPI، PostgreSQL، Celery، Watcher و سرویس‌های پردازش/گزارش
- `evaluation/`: اندازه‌گیری WER/CER و دقت عددها و موجودیت‌ها
- `scripts/`: تست جامع، Backup و Restore
- `load-tests/`: ابزار Load و Soak
- `docs/`: معماری، نصب، مدیریت، امنیت، آزمون و محدودیت‌ها

## اجرای سریع رابط روی Windows

```powershell
cd "C:\Users\LOQ\OneDrive\Documents\voice agent farazma\web"
npm.cmd install
npm.cmd run dev
```

سپس `http://localhost:3000` را باز کنید، حساب بسازید و وارد شوید. این حالت برای تست رابط است؛ Worker هوش مصنوعی، Issabel watcher و خروجی PDF/Excel به Backend کامل نیاز دارند.

## اجرای کامل خصوصی

پیش‌نیازها: Docker Desktop، کلید معتبر OpenAI و یک مسیر ضبط Mount‌شده از Issabel.

```powershell
Copy-Item .env.example .env
# مقادیر امن و مسیر ISSABEL_RECORDINGS_PATH را در .env تنظیم کنید
docker compose up -d --build
```

- داشبورد: `http://localhost:3000`
- API: `http://localhost:8000/api/v1/docs`
- Keycloak: `http://localhost:8081`
- MinIO: `http://localhost:9001`

راهنمای کامل: [استقرار](docs/DEPLOYMENT.md)، [اتصال Issabel](docs/ISSABEL_INTEGRATION.md) و [راهنمای مدیر](docs/ADMIN_GUIDE.md).

## اجرای آزمون‌ها

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_all.ps1
```

آزمون‌های مستقل:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q
.venv\Scripts\python.exe -m pytest evaluation/tests scripts/tests load-tests/tests -q
cd web
npm.cmd run lint
npx.cmd tsc --noEmit
npm.cmd test
npm.cmd run build
```

## ارزیابی دقت، Backup و Restore

```powershell
.venv\Scripts\python.exe evaluation/run_evaluation.py
.venv\Scripts\python.exe scripts/backup.py --help
.venv\Scripts\python.exe scripts/restore.py --help
```

گزارش نمونه ارزیابی فقط سلامت ابزار را می‌سنجد و اثبات دقت تماس واقعی نیست. برای معیار ۸۵٪ باید دیتاست تماس‌های واقعیِ غیرحساس و Transcript مرجع وارد و گزارش جدید تولید شود.

## امنیت و تحویل

- هیچ Secret یا کلید API را Commit نکنید؛ `.env` فقط روی سرور نگهداری شود.
- در محیط عملیاتی `AUTH_DISABLED=false`، HTTPS و MFA فعال باشند.
- پیش از تحویل، Backup/Restore روی زیرساخت مقصد و سیاست نگهداری صوت آزمایش شود.
- محدودیت‌های اثبات‌شده در [KNOWN_LIMITATIONS](docs/KNOWN_LIMITATIONS.md) و نتیجه نهایی تست‌ها در [RELEASE_GATE](docs/RELEASE_GATE.md) ثبت می‌شوند.
