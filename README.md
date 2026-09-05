# 🤖 AI Essay Checker Bot (Scalable Telegram Bot)

Minglab talabalar bo'lgan Telegram guruhlarda 24/7 buzilmasdan ishlaydigan, IELTS Writing va ingliz tili insholarini sun'iy intellekt (Groq Llama 3.3 70B) orqali tekshiruvchi Telegram bot tizimi.

---

## 🏗️ Arxitektura va Imkoniyatlar

- **Asinxron Navbat (Queue & Worker Pool):** Telegram Webhook tezkor javob oladi (`#1-o'rindasiz`), orqa fonda bir nechta mustaqil workerlar inshoni tekshiradi va natijani yuboradi.
- **3 Bosqichli Filtr:** 
  1. Komandalar (`/start`, `/help`) filtrlanadi.
  2. Regex hashtag (`#essay`, `#essey`, `#insho`, `#task2`) orqali xatolar bilan yozilsa ham to'g'ri aniqlanadi.
  3. Kamida 40 ta so'z mavjudligi tekshiriladi. Guruhdagi boshqa oddiy suhbatlarga bot umuman xalaqit bermaydi.
- **SHA-256 Kesh (24 soat):** Bir xil insho qayta yuborilsa, AI ga bormasdan keshdan olinadi (AI sarfi 40-70% tejaladi).
- **Kunlik Limitlar (Rate Limiting):** Har bir foydalanuvchi (masalan 5 ta) va guruh (masalan 50 ta) uchun spamga qarshi cheklovlar.
- **Guruh Maxfiyligi (Privacy) va Telegram 4096 belgi nazorati:** Guruhga faqat qisqa badge (Band score) yuboriladi, batafsil qizil xatolar va taqriz esa talabaning shaxsiy chatiga yuboriladi. Xabarlar Telegram limiti bo'yicha avtomatik qismlarga ajratiladi.
- **Retry with Exponential Backoff:** AI provayderi uzilib qolsa yoki rate limit bo'lsa, tizim 3 marta (2s, 5s, 10s) qayta urinadi.

---

## 🚀 O'rnatish va Ishga Tushirish

### 1. Talablar
- Python 3.10+
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))
- Groq API Key ([console.groq.com](https://console.groq.com) - bepul)

### 2. Kutubxonalarni o'rnatish
```bash
pip install -r requirements.txt
```

### 3. `.env` Faylini Sozlash
`.env.example` faylidan nusxa olib `.env` yarating:
```env
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxyz
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# Lokal rivojlantirish uchun SQLite yetarli:
DATABASE_URL=sqlite+aiosqlite:///bot.db

# Redis navbati (agar bo'sh qoldirilsa, avtomatik lokal xotira navbati ishlaydi):
REDIS_URL=

# Cheklovlar
DAILY_USER_LIMIT=5
DAILY_GROUP_LIMIT=50
```

### 4. Tizim Testlarini Tekshirish
```bash
python verify_system.py
```

### 5. Botni Ishga Tushirish
```bash
python main.py
```

---

## 📂 Fayllar Strukturasi

```
esseycheckerbot/
│── db/
│   ├── models.py             # User, Group, Essay, DailyUsage modellari
│   └── database.py           # Async SQLAlchemy, sessiya va limitlar
│── services/
│   ├── filter_service.py     # 3 bosqichli filtr va hashtag tekshiruvi
│   ├── cache_service.py      # SHA-256 xeshlash va 24 soatlik kesh
│   ├── ai_service.py         # Groq AI (Llama 3.3 70B) va IELTS prompt
│   ├── queue_service.py      # Redis / Async Queue xizmati
│   └── worker.py             # Mustaqil Worker lar va hisobot formati
│── handlers/
│   └── messages.py           # Guruh va shaxsiy chat xabarlarini qabul qilish
│── config.py                 # Pydantic Settings sozlamalari
│── main.py                   # Asosiy ishga tushirish fayli
│── verify_system.py          # Tizimni tekshiruvchi test ssenariysi
│── requirements.txt          # Python bog'liqliklari
└── .env.example              # Namuna konfiguratsiya
```
