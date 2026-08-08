# وضعیت Release مکالمه‌بان

آخرین وضعیت کد: `A0_A1_IMPLEMENTED_PENDING_ENVIRONMENT_GATES`

وضعیت عملیاتی هنوز `READY_FOR_INTERNAL_TESTING` است و تا پاس‌شدن آزمون‌های واقعی نباید به `READY_FOR_CONTROLLED_PILOT` تغییر کند.

## پیاده‌سازی‌شده در A0/A1

- FastAPI/PostgreSQL تنها مسیر داده سرور و پایلوت است؛ D1/R2 فقط Preview توسعه محلی و خارج از Gate است.
- ورود OIDC، Refresh Token واقعی، عضویت فعال PostgreSQL و همگام‌سازی نقش/فعال‌بودن با Keycloak.
- PostgreSQL پایدار جداگانه برای Keycloak و backup/restore شامل PostgreSQL اصلی، MinIO و Keycloak.
- RLS برای تمام جدول‌های tenant، صوت محافظت‌شده با HTTP Range و Rate Limit مبتنی بر Redis.
- Retry و طبقه‌بندی خطای OpenAI، Storage و Database.
- نسخه‌های Immutable متن، تحلیل، شاهد و Artifact و اشاره‌گرهای latest/reviewed/published.
- صف بازبینی انسانی، جلوگیری از self-review، تأیید، رد، درخواست اصلاح، انتشار و Audit.
- سیاست ۵۰ تماس اول، بازبینی ریسک‌محور و نمونه تصادفی پس از آن.
- Shared Folder watcher، تشخیص فایل ناقص/تکراری/خراب، قرنطینه و CDR read-only با وضعیت‌های matched/ambiguous/unmatched.
- خروجی TXT، HTML امن، JSON، PDF و Excel و ثبت checksum نسخه Artifact.
- گزارش تیم Server-side فقط از Published Version، صف پیگیری، عملیات Retry و حذف سرتاسری/Retention روزانه.
- داشبورد صف Review، برچسب Draft/Published، تاریخچه نسخه‌ها و نمایش وضعیت CDR.

## Gateهایی که فقط روی محیط واقعی قابل پاس‌شدن هستند

- اجرای Migration و Cross-tenant RLS روی PostgreSQL واقعی مقصد.
- ورود، MFA، Refresh و غیرفعال‌سازی کاربر روی Keycloak مقصد.
- اتصال Shared Folder و CDR واقعی Issabel با حساب فقط‌خواندنی.
- پردازش و بازبینی ۵۰ تماس واقعی و اندازه‌گیری Transcript و نقش گوینده با آستانه ۸۵٪.
- Backup/Restore کامل روی stack جداگانه.
- تست ۲۴ساعته و سپس هفت‌روزه بدون مداخله زیرساختی.

تا قبل از پاس‌شدن همه موارد بالا، ادعای «آماده پایلوت» یا دقت ۸۵٪ مجاز نیست.

## Releaseهای بعدی

A2 شامل SFTP، کاوه‌نگار/SMTP، Outbox، CRM عمومی، Automation اجرایی، جست‌وجوی Hybrid و گزارش پیشرفته است. Release B شامل سوپرادمین SaaS، Provisioning، سهمیه و Billing دستی است. این دو Release عمداً Gate شروع پایلوت A1 نیستند و در وضعیت فعلی کامل محسوب نمی‌شوند.
