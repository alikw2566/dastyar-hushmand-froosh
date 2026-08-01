# ممیزی سیستم مکالمه‌بان

تاریخ ممیزی و سخت‌سازی: ۲۰۲۶-۰۸-۰۱
مبنای بررسی: commit `22505f6`، نسخه پیش‌انتشار `0.1.0`

## جمع‌بندی

نسخه مبنا یک داشبورد فارسی، API آپلود و Worker اولیه رونویسی/تحلیل داشت، اما برای کار مستقل پایلوت فاقد Watcher ایزابل، state machine قابل مشاهده، اعتبارسنجی صوت و شواهد، Retry عملیاتی، خروجی‌های مدیریتی و پوشش تست کافی بود. این موارد اکنون در کد و قراردادهای API اضافه شده‌اند. وضعیت Release Gate همچنان `READY_FOR_INTERNAL_TESTING` است، زیرا دقت روی تماس واقعی، اجرای کامل Docker/Issabel، تست واقعی PostgreSQL RLS و soak طولانی در این میزبان اثبات نشده‌اند.

## معماری فعلی

- `web/`: Vinext/Next.js، TypeScript، رابط فارسی RTL، اجرای کامل از طریق FastAPI و حالت توسعه محلی D1/R2.
- `backend/`: FastAPI، SQLAlchemy async، PostgreSQL، Alembic و RLS اجباری برای جدول‌های tenantدار.
- `worker`: Celery/Redis با `acks_late`، retry/backoff، ثبت رخداد و خطای پردازش.
- `watcher`: پایش recursive پوشه Local/Shared Folder ایزابل، پایداری فایل، SHA-256، جلوگیری از تکرار، قرنطینه و heartbeat. SFTP عمداً readiness نمی‌گیرد و پیاده‌سازی‌شده معرفی نمی‌شود.
- `storage`: MinIO/S3-compatible با namespace شرکت/تماس و URL موقت.
- `identity`: Keycloak/OIDC با نقش‌های admin، manager، supervisor، agent، viewer و seller قدیمی. claim شرکت از attribute هر کاربر تولید می‌شود، نه مقدار ثابت.
- `evaluation/`, `load-tests/`, `scripts/`: ارزیابی نسخه‌دار، load/soak harness، backup/restore و فرمان جامع تست.

## جریان فعلی تماس

1. فایل consented از API یا drop-folder اختصاصی Issabel دریافت می‌شود.
2. Watcher وضعیت `waiting_for_file/discovered`، زمان کشف، مسیر، اندازه و hash را پایدار ثبت می‌کند.
3. ffprobe فایل را از نظر قالب، مدت، اندازه و خرابی بررسی می‌کند؛ فایل نامعتبر با کد امن قرنطینه می‌شود.
4. فایل سالم در Object Storage ذخیره، تماس idempotent ساخته و job صف می‌شود.
5. Worker صوت اصلی را تغییر نمی‌دهد؛ یک WAV mono/16kHz استاندارد می‌سازد و trace پیش‌پردازش را ثبت می‌کند.
6. `gpt-4o-transcribe-diarize` قطعات زمان‌دار را می‌سازد؛ واژه‌نامه شرکت روی متن نرمال‌شده اعمال و متن خام حفظ می‌شود.
7. نقش گوینده از metadata/قواعد/مدل تعیین و با `agent/customer/unknown/other` و confidence ذخیره می‌شود.
8. تحلیل فروش ساختاریافته تولید می‌شود. validator مستقل quote، segment و timestamp را تطبیق می‌دهد؛ ادعا یا فیلد بی‌شاهد حذف و تماس برای بازبینی علامت‌گذاری می‌شود.
9. extraction قابل فیلتر، evidence، KPI، task پیگیری بدون duplicate و draft پیام ذخیره می‌شوند.
10. داشبورد متن/صوت همگام، اصلاحات، خط زمانی، خطا، Retry/Re-analysis مجاز، PDF و Excel را نمایش می‌دهد.

## تغییرات انجام‌شده نسبت به نسخه مبنا

- Alembic و مدل‌های `source_imports`، `pipeline_events`، `processing_errors`، `watcher_heartbeats`، `call_extractions`، `extraction_evidence`، `transcript_corrections` و `glossary_terms` اضافه شد.
- وضعیت‌های کشف تا تکمیل/بازبینی/Retry/خطا و taxonomy خطا اضافه شد.
- تشخیص فایل ناقص/تکراری/خراب، parser نام فایل Issabel و حفاظت از symlink خارج از drop-folder اضافه شد.
- آپلود و ورود Watcher به‌صورت streaming انجام می‌شود تا فایل بزرگ کامل وارد حافظه نشود.
- استخراج نام، تلفن، شرکت، شهر/استان، محصول، مبلغ/بودجه، تعهد، اعتراض، مرحله فروش، ریسک، نتیجه و پیگیری ساختاریافته شد.
- فیلتر، sorting و pagination سمت سرور، دسته‌های پیگیری، Call Detail، Processing Operations و اصلاح نقش/متن اضافه شد.
- PDF فارسی و Excel چندبرگی منطبق با فیلترها اضافه شد.
- نقش‌های جدید، محدودسازی تماس‌های کارشناس به مالک، first-admin idempotent و Keycloak tenant mapper اصلاح شد.
- تنظیم production ناامن رد می‌شود و کلید Fernet معتبر الزامی است.
- مستندات استقرار، ایزابل، کاربر/مدیر، امنیت، عیب‌یابی، backup/recovery، تست و soak تهیه شد.

## ریسک‌ها و محدودیت‌های باقی‌مانده

- معیار «حداقل ۸۵٪ تماس واقعی فارسی» هنوز اندازه‌گیری نشده؛ گزارش موجود فقط fixture ساختگی و `NOT_MEASURED_ON_REAL_CALLS` است.
- صحت نقش فروشنده/مشتری در تماس تک‌کاناله واقعی هنوز dataset انسانی کافی ندارد.
- Docker روی میزبان ممیزی نصب نبود؛ full-stack، migration upgrade، MinIO/PostgreSQL restore و E2E واقعی Issabel اجرا نشده‌اند.
- آزمون symlink در Windows بدون مجوز ساخت symlink skip می‌شود، هرچند guard کد و تست آن وجود دارد.
- soak واقعی ۲۴ساعته/هفت‌روزه و load علیه deployment اجرا نشده است.
- connector اجرایی CRM/SMS/WhatsApp/Email، SFTP، semantic search کامل، purge زمان‌بندی‌شده retention، TLS/Keycloak production persistence و rate-limit middleware هنوز Release Blocker هستند.
- حالت Local D1/R2 پردازش AI، PDF/Excel و Retry واقعی ندارد؛ UI این قابلیت‌ها را غیرفعال و محدودیت را صریح نمایش می‌دهد.

جزئیات Release Blockerها در `KNOWN_LIMITATIONS.md` و معیارهای قابل تکرار در `TESTING.md` ثبت شده‌اند. هیچ عدد تخمینی به‌عنوان نتیجه واقعی منتشر نمی‌شود.
