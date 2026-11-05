# Logistika Bot

Telegram’da yuk va transport topish, e’lon qo‘shish va kontaktlarni obuna orqali ochish uchun ishlaydigan boshlang‘ich loyiha. Menyular foydalanuvchi taqdim etgan logistika boti ekranlari asosida tuzilgan.

Python 3.12+, aiogram 3.31, SQLite. Bitta server va bitta polling jarayoni uchun mo‘ljallangan. Qidiruvlar, e’lon qoralamalari, obunalar va to‘lovlar bazada saqlanadi. Boshlash uchun alohida ma’lumotlar bazasi serveri yoki domen talab qilinmaydi.

## Tayyor imkoniyatlar

- Bosh menyu, Tezkor Qidiruv, Yuk topish va Moshina topish.
- 15 ta transport toifasi; bir e’londa bir nechta avto turi.
- Yo‘nalish, bitta joy, mamlakat va shahar bo‘yicha qidiruv. Lotin/kirill va asosiy nom variantlari.
- Hududlar bo‘yicha haqiqiy sonlar va Asia/Tashkent bo‘yicha bugungi e’lonlar.
- Beshtadan natija, barqaror qidiruv ro‘yxati, davom ettirish va kartochkaga qaytish.
- Batafsil matn, telefon kontakt kartasi, mavjud Telegram manba havolasi.
- Noyob foydalanuvchilar bo‘yicha ko‘rish va raqam ochish hisoblagichlari.
- E’lonni bosqichma-bosqich qo‘shish, bir nechta manzil, sana/hajm/narx, tasdiqlash, o‘z e’lonini yopish.
- Pullik kirish, admin tomonidan obuna berish va Telegram Stars bilan bir martalik kirish sotish.
- To‘lovning foydalanuvchi/summa/valyutasini tekshirish va bir tranzaksiyani takror hisoblamaslik.
- Ruxsat berilgan kanallardagi kelishilgan format, JSON import va admin boshqaruvi.
- Docker sozlamasi, SQLite zaxiralash buyrug‘i va avtomatik testlar.

## Kompyuterda ishga tushirish

Repozitoriyni yuklab, uning papkasida terminal oching:

```bash
git clone https://github.com/eshmamatovxurshid201-png/logistika-bot.git
cd logistika-bot
python -m venv .venv
```

Windows PowerShell’da virtual muhitni faollashtirmasdan ham quyidagilar ishlaydi:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux/macOS’da:

```bash
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

`.env`ni matn muharririda oching. BotFather orqali olingan tokenni `BOT_TOKEN=`dan keyin yozing. Haqiqiy `.env` GitHub’ga yuborilmaydi. `PAID_ACCESS=false` qilib dastlab ochiq rejimda tekshirish mumkin.

Keyingi buyruqlarda Windows’da `.venv\Scripts\python.exe`, Linux/macOS’da `.venv/bin/python` ishlating. Quyida qisqalik uchun `python` deb ko‘rsatilgan; virtual muhit faollashtirilgan bo‘lsa shu shakl ham ishlaydi.

```bash
python -m logistika_bot check
python -m logistika_bot init-db
python -m logistika_bot run
```

Telegram’da o‘z botingizni ochib `/start` yuboring. `/id` sizning raqamli Telegram ID’ingizni qaytaradi. Uni `.env`dagi `ADMIN_IDS=`ga yozing va botni qayta ishga tushiring. Bir nechta admin ID vergul bilan ajratiladi.

Sinov e’lonlari kerak bo‘lsa, botni ishga tushirishdan oldin:

```bash
python -m logistika_bot seed-demo
```

Bu buyruq 9 ta aniq DEMO deb belgilangan namuna yaratadi. Raqamlari haqiqiy aloqa uchun emas. Demo avtomatik yuklanmaydi; haqiqiy xizmat uchun yangi bo‘sh bazadan boshlang yoki admin `/hide ELON_ID` bilan namunalarni yopsin. `seed-demo` qayta bajarilganda nusxalar ko‘paymaydi.

## Pullik rejim

`.env` standartida `PAID_ACCESS=true`, `PLAN_PRICE_STARS=0`: ro‘yxatlar ochiq, boshqa foydalanuvchi e’lonining batafsil matni, raqami va manba havolasi obuna bilan. E’lon berish ochiq. Admin va e’lon egasi o‘z ma’lumotini ko‘ra oladi. `0` avtomatik sotuvni o‘chiradi; bu bepul tarif narxi degani emas.

Qo‘lda sinash uchun admin botga:

```text
/grant FOYDALANUVCHI_ID 30
/revoke FOYDALANUVCHI_ID
```

Stars orqali sotuvni yoqish uchun o‘zingiz tanlagan musbat butun `PLAN_PRICE_STARS`, `PLAN_DAYS` va haqiqiy `SUPPORT_USERNAME`ni kiriting. Standart 30 kun namuna sozlama bo‘lib, boshqa botning tasdiqlangan tarifi emas. Yordam akkaunti yozilmaguncha pullik sotuv sozlamasi qabul qilinmaydi.

Foydalanuvchi `Sozlamalar → Obuna` yoki `/subscribe` orqali shartlarni qabul qiladi va Telegram hisobini oladi. Kirish faqat `successful_payment` kelgandan keyin ochiladi. To‘lov takror yetib kelsa obuna ikkinchi marta uzaymaydi. Mavjud obuna ustiga yangi muddat qo‘shiladi. Avtomatik takroriy yechish yo‘q. Eski kontakt tugmalari ham joriy kirish huquqini tekshiradi.

`/terms` va `/paysupport` mavjud. Ishga chiqarishdan oldin `ui.terms()`dagi xizmat shartlarini o‘z faoliyatingizga moslashtiring. Qaytarish so‘rovlari support orqali boshqariladi; avtomatik refund buyrug‘i bu versiyaga kiritilmagan. To‘lovni avval Telegram test muhitida tekshiring. Mahalliy testlar haqiqiy Stars sarflamaydi.

Rasmiy to‘lov tartibi: [Telegram Stars](https://core.telegram.org/bots/payments-stars).

## Qidiruv qoidalari

`Toshkent` — jo‘nash yoki yetib borish tomonida Toshkent bo‘lgan e’lonlar.

`Toshkent Samarqand` yoki `Toshkent → Samarqand` — aynan shu tartibdagi yo‘nalish. `Ташкент Самарканд` ham shu joylarga bog‘lanadi.

Lug‘atda yo‘q shahar: `Turkiya / Gebze`. To‘liq yo‘nalish: `Turkiya / Gebze → O‘zbekiston / Toshkent`. Bir nechta manzil e’lon qo‘shishda `;` bilan yoziladi.

Transportlar geografik bo‘limda jo‘nash joyi bo‘yicha guruhlanadi. Bo‘sh shahar maydoni `boshqa` guruhiga kiradi. Sonlar bir xil filtrdan olinadi. Bir nechta avto yoki manzil e’lonni ikki marta sanashga sabab bo‘lmaydi.

`/davom` oxirgi qidiruvni davom ettiradi. Qidiruv ro‘yxati standartda 24 soat saqlanadi; keyin yangidan qidirish kerak. Qidiruv paytida yangi e’lon kelsa u avvalgi ro‘yxat tartibini o‘zgartirmaydi. Standart eng ko‘p 5000 natija saqlanadi; kattaroq natijada foydalanuvchiga chegarasi aytiladi.

## E’lon manbalari

### Bot orqali

`E’lon qo‘shish` menyusidan to‘ldiring. E’lon tasdiqlangach darhol faol bo‘ladi. `Mening e’lonlarim` eng so‘nggi 30 ta faol e’lonni va yopish tugmasini beradi. Admin `/hide ELON_ID` bilan istalgan e’lonni yopishi mumkin. Standart amal muddati 7 kun.

### JSON import

`examples/listings.json` shaklini to‘ldirib:

```bash
python -m logistika_bot import examples/listings.json
```

`external_key` har manba e’loni uchun barqaror va noyob bo‘lsin. Shu kalit bilan qayta import e’lonni yangilaydi. `raw_text` berilsa Batafsilda aynan shu matn, aks holda kiritilgan maydonlardan tayyorlangan matn chiqadi. Import formatidagi country/city maydonlari, avto ID’lari va telefon tekshiriladi. `source_url` faqat haqiqiy shakldagi Telegram xabari havolasi bo‘lishi mumkin.

### Ruxsat berilgan kanal

Botni o‘zingiz boshqaradigan kanalga qo‘shing, kanalning raqamli ID’sini `SOURCE_CHAT_IDS`ga yozing. Kod boshqa kanallardan kelgan postlarni qabul qilmaydi. Ushbu versiya quyidagi kelishilgan formatni o‘qiydi:

```text
#yuk
Jo‘nash: Toshkent
Manzil: Samarqand; Buxoro
Avto: Tent, Ref
Tavsif: Qoplangan mahsulot
Hajm: 20 t
Narx: Kelishiladi
Telefon: +998000000000
```

Namunadagi raqamni haqiqiy raqamga almashtiring. Sana kerak bo‘lsa `Sana: YYYY-MM-DD` qatorini haqiqiy sana bilan qo‘shing. Transport uchun birinchi qator `#transport`. Post tahriri shu e’lonni yangilaydi. Butun postni `#yopildi` deb tahrirlash e’lonni yopadi. Manba URL’si avtomatik tuziladi. Yopiq kanalga o‘tish uchun foydalanuvchining a’zoligi talab qilinishi mumkin.

Bot API kanal posti o‘chirilganini doimo bildirmaydi; shuning uchun yopish belgisi, admin boshqaruvi va amal muddati ishlatiladi. Botni kanalga qo‘shish avvalgi tarixni avtomatik import qilmaydi. Erkin yozilgan barcha Telegram matnlarini avtomatik tushunish bu versiyada yo‘q.

## Serverda Docker bilan

`.env`ni to‘ldiring, so‘ng:

```bash
docker compose up -d --build
docker compose logs -f bot
```

Baza `bot-data` doimiy volume’da saqlanadi. Bitta token bilan bir vaqtda faqat bitta bot jarayonini ishlating. Mavjud webhook aniqlansa dastur uni o‘zicha o‘chirmaydi; eski xizmatni to‘xtatib keyin pollingga o‘ting. Qolgan to‘lov xabarlarini o‘chirish uchun `drop_pending_updates` ishlatilmaydi.

Zaxira nusxasi:

```bash
python -m logistika_bot backup backups/bot-backup.sqlite3
```

Yangi fayl nomini tanlang; mavjud fayl ustiga yozilmaydi. Faol SQLite bazasini oddiy nusxalash o‘rniga shu buyruqni ishlating. `.env` va bazani alohida saqlang.

## Testlar

```bash
python -m unittest discover -s tests -v
python -m compileall -q logistika_bot
```

Testlar marshrut, yozuv variantlari, hisoblagichlar, kirish huquqi, qidiruvni davom ettirish, saqlanadigan qoralama, e’lon egasi, kanal ruxsati va takroriy to‘lovni tekshiradi. Aiogram so‘rov modellari va haqiqiy dispatcher tarmoqsiz sinaladi. Haqiqiy Telegramga xabar yoki haqiqiy to‘lov yuborilmaydi.

## Fayllar

| Fayl | Vazifa |
| --- | --- |
| `config.py` | Muhit sozlamalari va tekshiruv |
| `domain.py` | Transport/joy lug‘ati, marshrut, telefon va import tekshiruvi |
| `db.py` | SQLite, atomar to‘lov, qidiruv va doimiy holat |
| `ui.py` | O‘zbekcha matn va klaviaturalar |
| `service.py` | Bot jarayonlari va kirish qoidalari |
| `telegram.py` | Aiogram bilan ulanish va dispatcher |
| `__main__.py` | Ishga tushirish, import, demo va zaxira buyruqlari |

## Hozirgi chegaralar

Bu versiya masofa va yo‘l vaqtini to‘qib ko‘rsatmaydi: aniq yo‘l hisoblash uchun xarita xizmati keyin ulanadi. “Ehtimol dispetcher”ni avtomatik aniqlash, ko‘rsatilmagan YukOn veb ilovasi va tasdiqlanmagan tariflar nusxalanmagan. Bular uchun alohida manba yoki qoida kerak.

SQLite tanlovi bir jarayonli boshlang‘ich xizmatni soddalashtiradi. Ko‘p serverli yoki katta trafikdagi xizmat uchun umumiy navbat, tashqi baza va tarqatilgan qulf qo‘shiladi. Telegramga jo‘natish bilan mahalliy yozuvni bitta tranzaksiyaga birlashtirib bo‘lmaydi: yuborilgandan so‘ng yozuv saqlanishidan oldingi keskin uzilish xabarni takror yuborishga olib kelishi mumkin. E’lon va to‘lov yozuvlari noyob kalitlar bilan himoyalangan.
