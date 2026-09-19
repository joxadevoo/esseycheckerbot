# 🚀 IELTS Essay Checker Bot — Production Deployment Qo'llanmasi

Ushbu qo'llanma botni **Production (jonli)** muhitga xavfsiz va barqaror chiqarish bo'yicha to'liq bosqichma-bosqich yo'riqnomadir.

---

## 1. ⚙️ Muhim Tayyorgarlik va @BotFather Sozlamalari

Bot guruhlarda va to'lovlarda xatosiz ishlashi uchun `@BotFather`da quyidagi sozlamalarni bajaring:

### A. Guruhdagi xabarlarni o'qish (Privacy Mode) — **SHART!**
Bot guruhlarda o'quvchilar yuborgan `#essay` yoki `#essey` hashtaglari bor insholarni avtomatik aniqlashi uchun:
1. Telegramda `@BotFather` ga kiring.
2. `/mybots` -> Botni tanlang -> **Bot Settings** -> **Group Privacy**.
3. **Turn off** (Disable) tugmasini bosing.
   *(Natija: `Privacy mode is disabled for @your_bot` bo'lishi kerak).*

### B. Guruhga qo'shish ruxsati (Group Permissions)
1. **Bot Settings** -> **Allow Groups?** -> **Turn groups on** ekanligini tekshiring.

### C. Telegram Stars (Yulduzlar orqali to'lov)
Botda Telegram Stars orqali qo'shimcha insholar sotish yoqilgan.
- Stars raqamli tovarlar (Digital Goods) hisoblangani sababli, alohida to'lov provayderi (Stripe/Click/Payme) talab qilinmaydi.
- To'g'ridan-to'g'ri Telegram hisobingizga tushadi.

---

## 2. 🗄 Ma'lumotlar Bazasi (Supabase PostgreSQL)

Loyiha **Supabase PostgreSQL** bilan to'liq integratsiya qilingan.

1. [Supabase.com](https://supabase.com) ga kiring va bepul loyiha oching.
2. **Project Settings** -> **Database** bo'limiga o'ting.
3. **Connection Pooling** (yoki Direct connection) parametrlarini oling:
   ```env
   DATABASE_URL=postgresql+asyncpg://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres
   ```
4. Bot birinchi marta ishga tushganda barcha kerakli jadvallar (`users`, `essays`, `group_topics`, `group_member_roles`, `daily_usage`, `referrals`) avtomatik yaratiladi.

---

## 3. 🌐 Serverga Joylash (Variantlar)

### Variant A: Render.com (Eng oson va bepul/arzon PaaS)

1. [Render.com](https://render.com) da ro'yxatdan o'ting va GitHub repozitoriyangizni ulang.
2. **New +** -> **Web Service** ni tanlang.
3. Repozitoriyani tanlang.
4. Quyidagi parametrlarni kiriting:
   - **Environment:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
   - **Health Check Path:** `/health`
5. **Environment Variables** bo'limiga `.env`dagi o'zgaruvchilarni kiriting:
   - `BOT_TOKEN`
   - `AI_PROVIDER` = `openai`
   - `OPENAI_API_KEY`
   - `OPENAI_MODEL` = `gpt-5.6-luna` (yoki `gpt-4o`)
   - `DATABASE_URL` = (Supabase PostgreSQL URL)
   - `ADMIN_IDS` = `7326292681`
   - `DAILY_USER_LIMIT` = `5`
   - `DAILY_GROUP_LIMIT` = `50`
6. **Deploy** tugmasini bosing. Render portni avtomatik ochadi va `/health` tekshiruvi orqali botni onlayn ushlab turadi.

---

### Variant B: VPS (Ubuntu Server) — Docker & Docker Compose orqali (Tavsiya etiladi!)

Agar o'zingizning VPS serveringiz bo'lsa (Ubuntu 22.04 / 24.04):

1. **Serverga kiring va Docker o'rnating:**
   ```bash
   sudo apt update && sudo apt install -y git docker.io docker-compose
   sudo systemctl enable --now docker
   ```

2. **Loyihani yuklab oling:**
   ```bash
   git clone <REPO_URL> /opt/esseycheckerbot
   cd /opt/esseycheckerbot
   ```

3. **.env faylini sozlang:**
   ```bash
   cp .env.example .env
   nano .env
   ```
   *(Kerakli kalitlarni kiriting: BOT_TOKEN, OPENAI_API_KEY, DATABASE_URL va h.k.)*

4. **Konteynerlarni fonda ishga tushiring:**
   ```bash
   docker-compose up -d --build
   ```

5. **Holat va loglarni tekshirish:**
   ```bash
   docker-compose ps
   docker-compose logs -f bot
   ```

---

### Variant C: VPS — Systemd Service orqali (Docker'siz to'g'ridan-to'g'ri)

1. **Python muhitini tayyorlash:**
   ```bash
   sudo apt update && sudo apt install -y python3-pip python3-venv libfreetype6 fonts-dejavu-core
   cd /opt/esseycheckerbot
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

2. **Systemd service fayli yaratish:**
   ```bash
   sudo nano /etc/systemd/system/essaybot.service
   ```
   Quyidagilarni yozing:
   ```ini
   [Unit]
   Description=IELTS Essay Checker Telegram Bot
   After=network.target

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/opt/esseycheckerbot
   ExecStart=/opt/esseycheckerbot/venv/bin/python main.py
   Restart=always
   RestartSec=5
   Environment=PYTHONUNBUFFERED=1

   [Install]
   WantedBy=multi-user.target
   ```

3. **Xizmatni faollashtirish:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable essaybot
   sudo systemctl start essaybot
   sudo systemctl status essaybot
   ```

4. **Loglarni kuzatish:**
   ```bash
   journalctl -u essaybot -f
   ```

---

## 4. 🛰 24/7 Monitoring (UptimeRobot orqali bepul)

Server uxlamasligi yoki nosozlik bo'lsa darhol xabar topish uchun:
1. [UptimeRobot.com](https://uptimerobot.com) ga kiring.
2. **Add New Monitor** tugmasini bosing:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `IELTS Essay Bot Health`
   - **URL:** `http://<SERVER_IP_YOKI_DOMEN>:8080/health` (yoki Renderni bergan URLi `https://.../health`)
   - **Monitoring Interval:** `5 minutes`
3. Saqlang. Har 5 daqiqada botning salomatligini tekshiradi va uxlab qolishining oldini oladi.

---

## 5. 🔒 Xavfsizlik bo'yicha yakuniy tavsiyalar

1. **Maxfiy kalitlar:** `.env` faylini hech qachon GitHub repozitoriyasiga public qilib push qilmang (`.gitignore`ga kiritilgan).
2. **PostgreSQL ulanishi:** `pool_pre_ping=True` va `statement_cache_size=0` sozlamalari PgBouncer / Supabase uzilishlarining oldini oladi.
3. **Anti-Spam:** `queue_service` foydalanuvchilarning bir vaqtda qayta-qayta so'rov yuborib serverni to'ldirishini avtomatik bloklaydi (`inflight` lock).
