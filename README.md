# Logistika Bot

Telegram’da yuk va transport e’lonlarini yig‘ish, saralash va obunadan keyin ko‘rsatish uchun Python 3.12 loyihasi.

## Asosiy oqim

1. Foydalanuvchi 1, 2, 3 yoki 6 oylik tarifni tanlaydi.
2. Sozlangan karta rekvizitlarini oladi va chekni rasm yoki PDF qilib yuboradi.
3. Admin Telegram ichidagi paneldan chekni ochadi, bankdagi tushumni tekshiradi va muddatni tasdiqlaydi yoki sabab bilan rad etadi.
4. Faqat tasdiqdan keyin qidiruv, e’lonlar ro‘yxati, Batafsil, telefon va manba havolalari ochiladi.
5. Obuna tugasa, eski qidiruv va kartochka tugmalari ham yangi so‘rovda ma’lumot bermaydi.

Chek yuborishning o‘zi to‘lov tasdiqlanishi emas. Bank integratsiyasi va avtomatik chek/OCR tasdiqlashi yo‘q. Bir chekni ikki admin tasdiqlasa ham muddat bir marta qo‘shiladi; tasdiqlash tarixi bazada yoziladi.

Muddat 30 kunlik ko‘paytma bilan emas, kalendar oy bo‘yicha hisoblanadi. Masalan, 2028-yil 31-yanvardan 1 oy — 29-fevralgacha. Amaldagi obuna yangilansa uning tugashidan davom etadi. 0 narxli tarif sotuvga chiqmaydi; haqiqiy narxlarni egasi belgilaydi.

## Imkoniyatlar

- Yuk va mashina qidirish, 15 transport toifasi, bir yoki ikki joyli yo‘nalish.
- Lotin/kirill yozuvi va asosiy joy nomi variantlari.
- Hududlar bo‘yicha haqiqiy hisoblagichlar va Asia/Tashkent bo‘yicha bugungi e’lonlar.
- Beshtadan natija, qidiruvni saqlash, Batafsil va kartochkaga qaytish.
- Telefon kontakt kartasi va mavjud manba xabari.
- Bot orqali e’lon qo‘shish, o‘z e’lonini ko‘rish/yopish. Muallif o‘z e’lonini boshqara oladi.
- Qo‘lda karta/chek tasdiqlashi, to‘rtta tarif va admin panel.
- Tanlangan guruhlardan yangi post/tahrirlarni yig‘ish, doimiy navbat, saralash va takrorlarini birlashtirish.
- Noaniq xabarlar uchun admin tekshiruvi, tahrirlash va chop etish.
- SQLite v1 bazasini ma’lumotlarni saqlagan holda v2 ga yangilash.
- JSON import, DEMO, zaxira buyrug‘i va Docker sozlamasi.

## Kompyuterda ishga tushirish

```bash
git clone https://github.com/eshmamatovxurshid201-png/logistika-bot.git
cd logistika-bot
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-collector.txt
Copy-Item .env.example .env
```

Linux/macOS:

```bash
.venv/bin/python -m pip install -r requirements-collector.txt
cp .env.example .env
```

Keyingi buyruqlarda Windows uchun `.venv\Scripts\python.exe`, Linux/macOS uchun `.venv/bin/python` ishlating. Virtual muhit faollashtirilsa oddiy `python` ham ishlaydi.

`.env`da quyidagilarni to‘ldiring:

| Sozlama | Ma’nosi |
| --- | --- |
| BOT_TOKEN | BotFather tokeni |
| ADMIN_IDS | Adminlarning raqamli Telegram ID’lari, vergul bilan |
| PAYMENT_MODE=manual | Karta va chek oqimi |
| PAYMENT_CARD_NUMBER | To‘lov kartasi |
| PAYMENT_CARD_HOLDER | Karta egasi |
| TARIFF_1_MONTH_UZS | 1 oylik narx, butun so‘mda |
| TARIFF_2_MONTH_UZS | 2 oylik narx |
| TARIFF_3_MONTH_UZS | 3 oylik narx |
| TARIFF_6_MONTH_UZS | 6 oylik narx |
| SUPPORT_USERNAME | Yordam akkaunti, havola o‘rniga username |
| PAID_ACCESS=true | Barcha qidiruv/e’lonlar uchun obuna tekshirish |

Musbat karta tariflari uchun karta, egasi, admin va support sozlanishi shart. Faqat mahalliy sinovda `PAID_ACCESS=false` qilish mumkin. Ishlaydigan xizmatda `true` qoldiring.

```bash
python -m logistika_bot check
python -m logistika_bot init-db
python -m logistika_bot run
```

Botda `/id` o‘z ID’ingizni ko‘rsatadi. ADMIN_IDS’ga kiritib, botni qayta ishga tushiring. Dastlab narxlarni 0 qoldirib /id olish mumkin. Yangi bazada haqiqiy e’lonlar bo‘lmaydi; ular foydalanuvchi, import yoki yig‘uvchi orqali keladi.

## Telegram admin paneli

Admin `/admin` yuboradi:

- **To‘lov cheklari:** navbat → chek rasmi/PDF → 1/2/3/6 oy → yakuniy tasdiq.
- **Rad etish:** sabab foydalanuvchiga yuboriladi, kirish ochilmaydi.
- **Saralash navbati:** noaniq asl matnni ko‘rish, tasdiqlash, tuzatib chop etish yoki o‘tkazish.
- **Guruhlar:** ro‘yxat, holatini yoqish/o‘chirish va yangi ID qo‘shish.
- Hisoblagichlar: faol obuna, chek, manba, navbat va takroriy e’lonlar.

```text
/grant_months FOYDALANUVCHI_ID 1
/grant_months FOYDALANUVCHI_ID 2
/grant_months FOYDALANUVCHI_ID 3
/grant_months FOYDALANUVCHI_ID 6
/revoke FOYDALANUVCHI_ID
/hide ELON_ID
/sources
/template
```

Oldingi versiyadagi `/grant ID KUN` buyrug‘i moslik uchun saqlangan. Yangi tariflar uchun oyli buyruq yoki chek panelini ishlating. Chek faqat adminlarga ochiladi; fayl Telegram file_id bilan saqlanadi, ochiq GitHub yoki veb havolaga yuklanmaydi. Bir xil Telegram fayli qayta ishlatilsa qabul qilinmaydi, ammo faylni o‘zgartirish yangi identifikator berishi mumkin — bank tushumini admin tekshirishi zarur.

## Taxminan 500 guruhni kuzatish

Oddiy Bot API istalgan guruh tarixini ochmaydi. Alohida **Telethon yig‘uvchi** o‘z Telegram akkauntingizning sessiyasi bilan ishlaydi. U faqat ro‘yxatdagi va akkaunt kirish huquqiga ega bo‘lgan guruhlardan kelgan yangi postlarni oladi. Guruhga avtomatik qo‘shilish, limitlarni chetlab o‘tish yoki shaxsiy yozishmalarga xabar yuborish amalga oshirilmaydi.

`TELEGRAM_API_ID` va `TELEGRAM_API_HASH`ni [my.telegram.org](https://my.telegram.org) orqali olib `.env`ga kiriting. So‘ng o‘z terminalingizda bir marta:

```bash
python -m logistika_bot collector-login
```

Telefon, tasdiqlash kodi va ikki bosqichli parol kerak bo‘lsa terminalning o‘zida so‘raladi. Ularni kodga yoki GitHub’ga yozmang. Sessiya standartda `data/collector.session`da saqlanadi va git’dan chiqarilgan.

Guruh ID’larini ko‘rish uchun aniq chaqiriladigan yordamchi buyruq:

```bash
python -m logistika_bot collector-dialogs
```

Kerakli guruhlarni tanlab, `groups.private.json` kabi mahalliy faylga joylang:

```json
[
  {"chat_id": -1001234567890, "title": "Haqiqiy guruh nomi"}
]
```

Bu ID namuna; o‘zingizning haqiqiy guruhlaringizga almashtiring. `*.private.json` git’dan chiqarilgan.

```bash
python -m logistika_bot sources-import groups.private.json
python -m logistika_bot collect
```

`SOURCE_LIMIT=500` standart ro‘yxat chegarasi. 500 ta yozuv mavjudligi akkaunt hammasiga a’zo ekanini isbotlamaydi; haqiqiy kirish huquqi Telegram’ga bog‘liq. `SOURCE_CHAT_IDS`dagi ID’lar ham boshlang‘ich ro‘yxatga qo‘shiladi. Panelda o‘chirilgan guruh qayta ishga tushganda o‘zicha yoqilmaydi.

Yig‘uvchi har guruhni alohida davriy tekshirish o‘rniga yangi xabar va tahrir hodisalarini oladi. Har xabar uchun foydalanuvchi profili yoki tarix so‘ralmaydi. Tahrirlar manba+xabar kaliti bilan yangilanadi, eski tahrir yangisini bosib ketmaydi. Kuzatuvchi qayta ulanganda Telethon’ning catch-up imkoniyati ishlatiladi. Tarixni ommaviy to‘liq ko‘chirib olish bu versiyaga kiritilmagan.

Xabar kelgach doimiy SQLite navbatiga yoziladi. Bot yoki yig‘uvchi jarayon navbatni ishlaydi. Bir nechta ishchi bir xabarni olsa ham yakuniy yozuv tranzaksiya bilan himoyalangan. Xabarni olish va navbatga yozish orasidagi nosozliklar uchun Telegram’dan mutlaq yetkazib berish kafolati yo‘q; katta hajmda monitoring va alohida baza/navbat talab qilinadi.

## Saralash va shablon

Parser tashqi AI xarajatisiz mahalliy qoidalar bilan ishlaydi:

1. Logistika bo‘lmagan oddiy suhbat va aniq spam ajratiladi.
2. Yo‘nalish, yuk/bo‘sh transport turi, avto, telefon, hajm, narx va mavjud sana olinadi.
3. Maydonlar yetarlicha aniq bo‘lsa e’lon chiqariladi.
4. Yo‘nalish yoki tur noaniq bo‘lsa admin navbatida qoladi.
5. Bir xil mazmun bir nechta manbada kelsa 24 soatlik oynada takrorlari birlashtiriladi.

`Toshkent → Samarqand`, `Ташкент - Самарканд`, `Toshkentdan Samarqandga` kabi yo‘nalishlar qo‘llanadi. Avto turi yoki yo‘nalish topilmagan xabar taxmin bilan ochiq ro‘yxatga chiqarilmaydi. Barcha erkin matnlarni 100% to‘g‘ri anglash kafolatlanmaydi; haqiqiy guruh namunalari asosida lug‘at va qoidalar kengaytiriladi.

Shablonda: e’lon turi, jo‘nash, manzil, avto, tavsif, hajm, narx, sana va mavjud telefon. Batafsilda asl matnning ko‘rinadigan nusxasi ham qoladi. To‘liq asl xabar saralash bazasida saqlanadi, uzun matn Telegram ko‘rsatish chegarasiga mos qisqartiriladi. Masofa/yo‘l vaqti uchun xarita xizmati hali ulanmagan.

Admin xabarni tuzatishda `/template` formatini yuborishi mumkin:

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

Namunadagi raqamni haqiqiy raqamga almashtiring. Transport e’loni uchun `#transport`. Noma’lum shahar: `Turkiya / Gebze`. Sana kerak bo‘lsa `Sana: YYYY-MM-DD` qatorini haqiqiy sana bilan yozing.

Bot kanalga qo‘shilgan bo‘lsa, ro‘yxatdagi kanal postlari ham shu navbat orqali ishlanadi. Butun postni `#yopildi`ga tahrirlash uni yopadi. Telegram ayrim o‘chirish hodisalarini manbasi bilan bermaydi; aniqlanmagan o‘chirish uchun admin yopishi va amal muddati ishlatiladi. Standart e’lon muddati 7 kun.

## Boshqa buyruqlar

```bash
python -m logistika_bot import examples/listings.json
python -m logistika_bot seed-demo
python -m logistika_bot process-queue
python -m logistika_bot backup backups/bot-backup.sqlite3
```

`seed-demo` faqat aniq DEMO belgili namuna kiritadi; avtomatik ishlamaydi. `external_key` bir xil bo‘lsa JSON import nusxani ko‘paytirmay yangilaydi. `process-queue` mavjud tayyor navbatni bir marta tugatadi. Zaxira uchun mavjud bo‘lmagan fayl yo‘lini tanlang. Eski bazani yangilashdan oldin shu zaxira buyrug‘ini ishlating; v1 → v2 yangilanishi foydalanuvchi, obuna va qoralamalarni saqlaydi.

## Docker

```bash
docker compose up -d --build bot
docker compose run --rm collector python -m logistika_bot collector-login
docker compose --profile collector up -d collector
docker compose logs -f bot collector
```

Manbalar ro‘yxatini botning admin panelidan qo‘shish mumkin. Ikkala xizmat bir xil `bot-data` volume’dan foydalanadi. Bitta token uchun bitta bot, bitta akkaunt sessiyasi uchun bitta yig‘uvchi jarayon ishlating. Bazani o‘chiradigan `down -v` yangilash tartibining bir qismi emas.

## Tekshiruv

```bash
python -m unittest discover -s tests -v
python -m compileall -q logistika_bot
python -m pip check
```

Testlar haqiqiy to‘lov, login kodi yoki Telegram xabari yubormaydi. Ular karta-chek tasdiqlashi, admin huquqi, kalendar oy, parallel tasdiqlash, to‘lovdan oldingi yopiq kirish, parser, 500 ta sun’iy manba, deduplikatsiya, tahrir va migratsiyani tekshiradi. Haqiqiy 500 guruhda ishlab chiqarish yuklamasi sinovi uchun akkaunt va haqiqiy ro‘yxat kerak.

## To‘lov platformasi talabi

Telegram raqamli xizmatlarni ilova ichida sotishda [Stars talabini](https://core.telegram.org/bots/payments-stars) belgilaydi. Karta/chek oqimini ishga chiqarishdan oldin shu talabni hisobga oling. `PAYMENT_MODE=stars` avvalgi integratsiya bilan moslik uchun saqlangan; standart qo‘lda tasdiqlash rejimidir.
