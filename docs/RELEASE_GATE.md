# گزارش Release Gate

تاریخ اجرا: ۱ اوت ۲۰۲۶
وضعیت نهایی: `READY_FOR_INTERNAL_TESTING`

این وضعیت یعنی کد و ابزارهای استقرار برای تست داخلی آماده‌اند؛ به معنی اثبات آمادگی پایلوت واقعی یا پایداری هفت‌روزه نیست.

## نتایج پاس‌شده

| بخش | نتیجه |
|---|---|
| Ruff lint برای Backend و ابزارهای عملیاتی | پاس |
| Ruff format check | ۴۸ فایل، پاس |
| Backend pytest | ۲۴ پاس، ۱ Skip وابسته به مجوز Symlink ویندوز |
| تست Evaluation | ۳ پاس |
| تست Backup/Restore | ۳ پاس |
| تست Load harness | ۴ پاس |
| Load harness dry-run | پاس؛ تست فشار واقعی اجرا نشده |
| Web ESLint | پاس |
| TypeScript `tsc --noEmit` | پاس |
| Web production build | پاس |
| Web tests | ۵ پاس |
| Python compileall | پاس |
| Python dependency check | بدون وابستگی شکسته |
| Alembic | یک Head با شناسه `20260801_01` |
| Keycloak JSON | معتبر؛ realm برابر `mokalemeban` |
| Docker Compose YAML | معتبر؛ ۸ سرویس |
| Secret scan | کلید OpenAI یا Secret واقعی پیدا نشد |
| npm production audit | ۰ آسیب‌پذیری |

فرمان جامع:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_all.ps1
```

خروجی آخر این فرمان: ۱۰ مرحله پاس، ۰ مرحله ناموفق و `release_gate=PASS`.

## تست دستی رابط

در مرورگر واقعی روی `127.0.0.1:3000` این سناریوها پاس شدند:

- بازشدن صفحه ورود بدون داده نمونه
- ساخت حساب مدیر و فضای کاری مستقل
- ورود خودکار پس از ثبت‌نام
- نمایش داشبورد با آمار واقعی صفر
- ورود به پنل مدیریت و مشاهده همه تب‌ها
- ذخیره تعریف اتصال و غیرفعال‌بودن شفاف Connector اجرایی در حالت محلی
- نمایش وضعیت واقعی Watcher و محدودیت SFTP
- نمایش «دقت هنوز اندازه‌گیری نشده» به‌جای عدد ساختگی
- فیلتر شهر تماس و ماندگاری فیلتر در URL
- دسته پیگیری عقب‌افتاده و ماندگاری دسته در URL
- نبود Error یا Warning در Console مرورگر هنگام آزمون

در جریان این تست، مهاجرت تدریجی دیتابیس D1 یک نصب قدیمی هنگام ثبت‌نام خطا می‌داد. ترتیب ساخت Indexها اصلاح و یک تست Regression اضافه شد؛ ثبت‌نام پس از اصلاح پاس شد.

## اندازه‌گیری‌هایی که ادعای عملیاتی محسوب نمی‌شوند

- گزارش Evaluation فعلی روی ۲ نمونه مصنوعی، WER برابر ۱۲٫۵۰٪ و CER برابر ۱۰٫۷۱٪ تولید می‌کند، اما با `measured=false` و `NOT_MEASURED_ON_REAL_CALLS` ثبت شده است.
- ابزار Load/Soak در حالت Dry-run تست شده؛ بار واقعی ۱۰۰/۵۰۰ فایل اجرا نشده است.
- Docker، ffmpeg و ffprobe روی ماشین فعلی موجود نبودند؛ اجرای واقعی ۸ سرویس، پردازش صوت و Export در کانتینر تست نشد.
- PostgreSQL، Redis، MinIO، Keycloak، OpenAI و Issabel واقعی در این اجرا در دسترس نبودند.
- تست مداوم ۲۴ ساعته و پایلوت هفت‌روزه اجرا نشده است.

## محدودیت‌های باقی‌مانده

- تنها Watcher پوشه Local/Network Share/SMB عملیاتی است؛ SFTP Puller هنوز پیاده نشده است.
- Connectorهای اجرایی CRM، پیامک، WhatsApp و Email هنوز آماده نیستند.
- جست‌وجوی معنایی کامل و Purge زمان‌بندی‌شده Retention باقی مانده‌اند.
- `npm audit` برای وابستگی‌های Production صفر است؛ ۴ هشدار Moderate فقط در زنجیره قدیمی توسعه `drizzle-kit → @esbuild-kit → esbuild` باقی مانده‌اند. اصلاح پیشنهادی npm نیازمند Downgrade شکننده Drizzle Kit است و عمداً اعمال نشده است.
- بازگردانی کامل Backup روی زیرساخت واقعی و سناریوهای قطع سرویس باید در محیط مقصد اجرا شوند.

جزئیات بیشتر در [محدودیت‌های شناخته‌شده](KNOWN_LIMITATIONS.md)، [راهنمای آزمون](TESTING.md) و [برنامه Soak](SOAK_TEST_PLAN.md) موجود است.

## تصمیم

`READY_FOR_INTERNAL_TESTING`

ارتقا به `READY_FOR_CONTROLLED_PILOT` فقط بعد از اجرای موفق Docker روی سرور مقصد، اتصال واقعی Shared Folder ایزابل، ارزیابی تماس‌های واقعی فارسی، تست Backup/Restore واقعی و حداقل تست مداوم ۲۴ ساعته مجاز است.
