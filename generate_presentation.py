import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

def create_presentation(output_path="AI_Essay_Checker_Taqdimot.pptx"):
    prs = Presentation()
    # 16:9 Widescreen dimensions
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    # Color Palette (Modern Premium Dark & Tech Theme)
    BG_DARK = RGBColor(15, 23, 42)        # Slate 900
    CARD_BG = RGBColor(30, 41, 59)        # Slate 800
    CARD_BORDER = RGBColor(51, 65, 85)    # Slate 700
    TEXT_LIGHT = RGBColor(248, 250, 252)  # Slate 50
    TEXT_MUTED = RGBColor(148, 163, 184)  # Slate 400
    PRIMARY = RGBColor(59, 130, 246)      # Blue 500
    SECONDARY = RGBColor(99, 102, 241)    # Indigo 500
    SUCCESS = RGBColor(16, 185, 129)      # Emerald 500
    WARNING = RGBColor(245, 158, 11)      # Amber 500
    CYAN = RGBColor(6, 182, 212)          # Cyan 500

    def add_background(slide):
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
        bg.fill.solid()
        bg.fill.fore_color.rgb = BG_DARK
        bg.line.fill.background()
        return bg

    def add_header(slide, title, category="AI ESSAY CHECKER BOT TAQDIMOTI"):
        # Category label
        cat_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.7), Inches(0.4))
        tf_cat = cat_box.text_frame
        tf_cat.word_wrap = True
        p_cat = tf_cat.paragraphs[0]
        p_cat.text = category.upper()
        p_cat.font.size = Pt(11)
        p_cat.font.bold = True
        p_cat.font.color.rgb = PRIMARY

        # Title
        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.75), Inches(11.7), Inches(0.8))
        tf = title_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(24)
        p.font.bold = True
        p.font.color.rgb = TEXT_LIGHT

    def add_card(slide, left, top, width, height, bg_color=CARD_BG, border_color=CARD_BORDER):
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
        card.fill.solid()
        card.fill.fore_color.rgb = bg_color
        card.line.color.rgb = border_color
        card.line.width = Pt(1.5)
        return card

    # ==========================================
    # SLIDE 1: Title Slide
    # ==========================================
    s1 = prs.slides.add_slide(blank_layout)
    add_background(s1)

    # Accent decorative bar
    bar = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.8), Inches(0.15), Inches(3.8))
    bar.fill.solid()
    bar.fill.fore_color.rgb = PRIMARY
    bar.line.fill.background()

    # Title box
    tbox = s1.shapes.add_textbox(Inches(1.2), Inches(1.6), Inches(11), Inches(4.0))
    tf1 = tbox.text_frame
    tf1.word_wrap = True

    p0 = tf1.paragraphs[0]
    p0.text = "SMART TELEGRAM PLATFORMA"
    p0.font.size = Pt(13)
    p0.font.bold = True
    p0.font.color.rgb = CYAN
    p0.space_after = Pt(10)

    p1 = tf1.add_paragraph()
    p1.text = "AI IELTS Essay Checker Bot"
    p1.font.size = Pt(40)
    p1.font.bold = True
    p1.font.color.rgb = TEXT_LIGHT
    p1.space_after = Pt(15)

    p2 = tf1.add_paragraph()
    p2.text = "Tizim qanday ishlaydi, qanday xarajat talab qiladi va biznes sifatida qanday foyda keltiradi?"
    p2.font.size = Pt(18)
    p2.font.color.rgb = TEXT_MUTED
    p2.space_after = Pt(25)

    p3 = tf1.add_paragraph()
    p3.text = "Oddiy va tushunarli tilda: Loyiha asoschilari, o'qituvchilar va hamkorlar uchun"
    p3.font.size = Pt(14)
    p3.font.italic = True
    p3.font.color.rgb = PRIMARY

    # Bottom badge
    badge = add_card(s1, Inches(0.8), Inches(5.9), Inches(11.7), Inches(0.9), bg_color=CARD_BG, border_color=CARD_BORDER)
    b_box = s1.shapes.add_textbox(Inches(1.0), Inches(5.95), Inches(11.3), Inches(0.8))
    b_tf = b_box.text_frame
    b_p = b_tf.paragraphs[0]
    b_p.text = "💡 Asosiy xulosa: 1 ta inshoni tekshirish tannarxi atigi 15-25 so'm (~$0.0015). Har bir tekshiruvdan 95%+ sof foyda marjasi!"
    b_p.font.size = Pt(13)
    b_p.font.bold = True
    b_p.font.color.rgb = SUCCESS

    # ==========================================
    # SLIDE 2: Muammo va Yechim
    # ==========================================
    s2 = prs.slides.add_slide(blank_layout)
    add_background(s2)
    add_header(s2, "Muammo va Bizning Yechim", "01 / LOYIHANING ZARURATI")

    # Card 1: Muammo
    add_card(s2, Inches(0.8), Inches(1.8), Inches(5.6), Inches(5.0))
    tb_m = s2.shapes.add_textbox(Inches(1.1), Inches(2.0), Inches(5.0), Inches(4.5))
    tf_m = tb_m.text_frame
    tf_m.word_wrap = True
    pm_t = tf_m.paragraphs[0]
    pm_t.text = "❌ Bugungi Muammo"
    pm_t.font.size = Pt(20)
    pm_t.font.bold = True
    pm_t.font.color.rgb = RGBColor(248, 113, 113) # Red 400
    pm_t.space_after = Pt(16)

    problems = [
        ("O'qituvchilar vaqti cheklangan:", "1 ta inshoni chuqur tekshirish 10-15 daqiqa oladi. 50 ta o'quvchi bo'lsa, bu 10+ soat uzluksiz mehnat."),
        ("O'quvchilar uzoq kutishadi:", "Insho topshirilgach, javob olish uchun 2-4 kunlab kutishga to'g'ri keladi."),
        ("Xususiy tekshiruv qimmat:", "Malakali ustozlarga har bir inshoni tekshirtirish 15,000 - 30,000 so'm turadi."),
        ("Subyektiv baholash:", "Turli o'qituvchilar turli xil mezonlarda baholaydi, xatolar tushuntirilmay qolib ketadi.")
    ]
    for title, desc in problems:
        p = tf_m.add_paragraph()
        p.text = f"• {title} "
        p.font.size = Pt(13)
        p.font.bold = True
        p.font.color.rgb = TEXT_LIGHT
        run = p.add_run()
        run.text = desc
        run.font.bold = False
        run.font.color.rgb = TEXT_MUTED
        p.space_after = Pt(10)

    # Card 2: Yechim
    add_card(s2, Inches(6.9), Inches(1.8), Inches(5.6), Inches(5.0))
    tb_y = s2.shapes.add_textbox(Inches(7.2), Inches(2.0), Inches(5.0), Inches(4.5))
    tf_y = tb_y.text_frame
    tf_y.word_wrap = True
    py_t = tf_y.paragraphs[0]
    py_t.text = "✅ Bizning AI Yechimimiz"
    py_t.font.size = Pt(20)
    py_t.font.bold = True
    py_t.font.color.rgb = SUCCESS
    py_t.space_after = Pt(16)

    solutions = [
        ("15 soniyada to'liq tahlil:", "O'quvchi insho yuborgan zahoti AI barcha qismlarni lahzada tekshirib beradi."),
        ("Rasmiy IELTS mezonlari:", "Task Achievement, Coherence, Lexical Resource va Grammar bo'yicha Band 0-9 ballar."),
        ("Xatolarni aniq ko'rsatish:", "Qaysi gapda xato bor, nima uchun xato va qanday to'g'rilash kerakligi ko'rsatiladi."),
        ("Namunaviy 8.0/9.0 insho:", "O'quvchining o'z fikrlarini saqlagan holda namunaviy yuqori balli versiya yozib beriladi.")
    ]
    for title, desc in solutions:
        p = tf_y.add_paragraph()
        p.text = f"• {title} "
        p.font.size = Pt(13)
        p.font.bold = True
        p.font.color.rgb = TEXT_LIGHT
        run = p.add_run()
        run.text = desc
        run.font.bold = False
        run.font.color.rgb = TEXT_MUTED
        p.space_after = Pt(10)

    # ==========================================
    # SLIDE 3: Bot Qanday Ishlaydi?
    # ==========================================
    s3 = prs.slides.add_slide(blank_layout)
    add_background(s3)
    add_header(s3, "Bot Qanday Ishlaydi? (4 Oddiy Qadam)", "02 / FOYDALANUVCHI TAJRIBASI")

    steps = [
        ("1", "Inshoni Yuborish", "O'quvchi Telegram guruhda yoki shaxsiy chatda #essay deb inshosini yozadi yoki rasm/matn tarzida jo'natadi.", CYAN),
        ("2", "Aqlli Navbat & Filtr", "Tizim bir zumda javob beradi: 'Qabul qilindi! Navbatingiz: 1-o'rin'. Guruhda shovqin bo'lmaydi.", PRIMARY),
        ("3", "AI Tahlili (Groq/OpenAI)", "Sun'iy intellekt matnni 4 ta IELTS mezoni bo'yicha grammatik va leksik tahlildan o'tkazadi.", SECONDARY),
        ("4", "Shaxsiyga Natija", "O'quvchining lichkasiga ballar, qizil xatolar, tavsiyalar va namunaviy Band 8.5 insho yuboriladi.", SUCCESS),
    ]

    card_w = Inches(2.7)
    card_h = Inches(4.8)
    for i, (num, stitle, sdesc, col) in enumerate(steps):
        left = Inches(0.8 + i * 3.0)
        top = Inches(1.8)
        add_card(s3, left, top, card_w, card_h)

        # Number circle badge
        badge_shape = s3.shapes.add_shape(MSO_SHAPE.OVAL, left + Inches(0.9), top + Inches(0.3), Inches(0.9), Inches(0.9))
        badge_shape.fill.solid()
        badge_shape.fill.fore_color.rgb = col
        badge_shape.line.fill.background()
        tf_b = badge_shape.text_frame
        p_b = tf_b.paragraphs[0]
        p_b.text = num
        p_b.alignment = PP_ALIGN.CENTER
        p_b.font.size = Pt(22)
        p_b.font.bold = True
        p_b.font.color.rgb = RGBColor(255, 255, 255)

        # Content
        stb = s3.shapes.add_textbox(left + Inches(0.2), top + Inches(1.4), card_w - Inches(0.4), card_h - Inches(1.6))
        stf = stb.text_frame
        stf.word_wrap = True

        p_t = stf.paragraphs[0]
        p_t.text = stitle
        p_t.alignment = PP_ALIGN.CENTER
        p_t.font.size = Pt(16)
        p_t.font.bold = True
        p_t.font.color.rgb = TEXT_LIGHT
        p_t.space_after = Pt(12)

        p_d = stf.add_paragraph()
        p_d.text = sdesc
        p_d.alignment = PP_ALIGN.CENTER
        p_d.font.size = Pt(12)
        p_d.font.color.rgb = TEXT_MUTED

    # ==========================================
    # SLIDE 4: Noyob Imkoniyatlar
    # ==========================================
    s4 = prs.slides.add_slide(blank_layout)
    add_background(s4)
    add_header(s4, "Nima Uchun Ushbu Bot Boshqalardan Ustun?", "03 / TEXNOLOGIK USTUNLIKLAR")

    features = [
        ("🔒 Guruh Maxfiyligi (Privacy Mode)", "Guruhda faqat qisqa baho stikeri/badge chiqadi. Xatolar va kamchiliklar faqat o'quvchining shaxsiyiga yuboriladi (o'quvchi uyalmaydi, guruh esa toza qoladi).", PRIMARY),
        ("⚡️ 24 Soatlik Aqlli Kesh (Smart Cache)", "Agar o'quvchi bir xil inshoni qayta jo'natsa, tizim AI ga bormasdan bazadan chiqaradi. Bu sun'iy intellekt xarajatini 40-70% gacha tejaydi!", SUCCESS),
        ("👨‍🏫 O'qituvchi Kabineti & Excel Tahlil", "O'qituvchi /topic komandasi orqali mavzu beradi. O'quvchilar natijalarini umumlashtirib, chiroyli Excel va PDF hisobot ko'rinishida yuklab oladi.", CYAN),
        ("🛡 Barqaror Navbat (Queue & Worker Pool)", "Bir vaqtning o'zida 1,000 ta talaba insho yuborsa ham bot 'qotib' qolmaydi. Navbat tizimi orqali har biriga ketma-ket, uzilishsiz xizmat ko'rsatiladi.", WARNING),
    ]

    for i, (ftitle, fdesc, col) in enumerate(features):
        row = i // 2
        col_idx = i % 2
        left = Inches(0.8 + col_idx * 5.95)
        top = Inches(1.8 + row * 2.6)
        add_card(s4, left, top, Inches(5.75), Inches(2.35))

        tb = s4.shapes.add_textbox(left + Inches(0.3), top + Inches(0.2), Inches(5.15), Inches(1.95))
        tf = tb.text_frame
        tf.word_wrap = True

        p1 = tf.paragraphs[0]
        p1.text = ftitle
        p1.font.size = Pt(16)
        p1.font.bold = True
        p1.font.color.rgb = col
        p1.space_after = Pt(8)

        p2 = tf.add_paragraph()
        p2.text = fdesc
        p2.font.size = Pt(13)
        p2.font.color.rgb = TEXT_MUTED

    # ==========================================
    # SLIDE 5: Xarajatlar Tahlili (Bir Insho Tannarxi)
    # ==========================================
    s5 = prs.slides.add_slide(blank_layout)
    add_background(s5)
    add_header(s5, "Texnik Xarajatlar Tahlili (Bir Insho Qanchaga Tushadi?)", "04 / MOLIYAVIY HISOB-KITOBLAR")

    # 3 Comparison cards for AI models
    models = [
        ("Groq (Llama 3.3 70B)", "Ultra-tezkor & Bepul/Arzon", [
            ("1 ta insho narxi:", "~15 - 25 so'm ($0.0015)"),
            ("1,000 ta insho:", "taxminan 20,000 so'm ($1.5)"),
            ("Tezlik:", "3-5 soniya"),
            ("Bepul limit:", "Kuniga bir necha yuz insho mutlaqo bepul!")
        ], SUCCESS),
        ("OpenAI (GPT-4o-mini)", "Optimal & Sifatli Muvozanat", [
            ("1 ta insho narxi:", "~20 so'm ($0.0016)"),
            ("1,000 ta insho:", "taxminan 20,000 so'm ($1.6)"),
            ("Tezlik:", "6-10 soniya"),
            ("Afzalligi:", "Mukammal grammatik va leksik aniqlik")
        ], PRIMARY),
        ("OpenAI (GPT-4o Flagman)", "Eng Yuqori Premium Sifat", [
            ("1 ta insho narxi:", "~300 so'm ($0.025)"),
            ("1,000 ta insho:", "taxminan 300,000 so'm ($25)"),
            ("Tezlik:", "10-15 soniya"),
            ("Qo'llanishi:", "Faqat VIP / pullik foydalanuvchilar uchun")
        ], SECONDARY),
    ]

    for i, (m_title, m_sub, m_items, m_col) in enumerate(models):
        left = Inches(0.8 + i * 3.95)
        top = Inches(1.8)
        card = add_card(s5, left, top, Inches(3.8), Inches(4.3))

        tb = s5.shapes.add_textbox(left + Inches(0.25), top + Inches(0.25), Inches(3.3), Inches(3.8))
        tf = tb.text_frame
        tf.word_wrap = True

        p = tf.paragraphs[0]
        p.text = m_title
        p.font.size = Pt(16)
        p.font.bold = True
        p.font.color.rgb = m_col

        p_sub = tf.add_paragraph()
        p_sub.text = m_sub
        p_sub.font.size = Pt(11)
        p_sub.font.color.rgb = TEXT_MUTED
        p_sub.space_after = Pt(14)

        for label, val in m_items:
            pl = tf.add_paragraph()
            pl.text = label + " "
            pl.font.size = Pt(12)
            pl.font.bold = True
            pl.font.color.rgb = TEXT_LIGHT
            r = pl.add_run()
            r.text = val
            r.font.bold = False
            r.font.color.rgb = SUCCESS if "$" in val or "so'm" in val else TEXT_MUTED
            pl.space_after = Pt(8)

    # Infrastructure summary box at bottom
    inf_card = add_card(s5, Inches(0.8), Inches(6.25), Inches(11.7), Inches(0.85), bg_color=CARD_BG, border_color=PRIMARY)
    tb_inf = s5.shapes.add_textbox(Inches(1.0), Inches(6.3), Inches(11.3), Inches(0.75))
    tf_inf = tb_inf.text_frame
    p_inf = tf_inf.paragraphs[0]
    p_inf.text = "🌐 Server (VPS/Render): $0 - $5/oy  |  🗄 Ma'lumotlar bazasi (Supabase): $0 (50,000 foydalanuvchigacha bepul)  |  🤖 Telegram Bot API: $0"
    p_inf.font.size = Pt(12)
    p_inf.font.bold = True
    p_inf.font.color.rgb = TEXT_LIGHT

    # ==========================================
    # SLIDE 6: Oylik Xarajatlar & Miqyos (Skalirlash)
    # ==========================================
    s6 = prs.slides.add_slide(blank_layout)
    add_background(s6)
    add_header(s6, "Har Xil O'quvchilar Soni Bo'yicha Oylik Xarajat", "05 / AMALIY BYUDJET REJASI")

    # Table of scenarios
    rows, cols = 4, 5
    left = Inches(0.8)
    top = Inches(1.8)
    width = Inches(11.7)
    height = Inches(3.2)

    table_shape = s6.shapes.add_table(rows, cols, left, top, width, height)
    table = table_shape.table

    # Column widths
    table.columns[0].width = Inches(2.5)
    table.columns[1].width = Inches(2.2)
    table.columns[2].width = Inches(2.2)
    table.columns[3].width = Inches(2.4)
    table.columns[4].width = Inches(2.4)

    headers = ["Oylik Ko'lam", "Server Xarajati", "Baza (Supabase)", "AI Xarajati (Groq/Mini)", "Jami Oylik Xarajat"]
    data = [
        ["Boshlang'ich (500 insho/oy)\n~100 ta o'quvchi", "$0 (Render bepul)", "$0 (Bepul)", "~$1.0 (13,000 so'm)", "~$1.0 (13,000 so'm)"],
        ["O'rta hajm (2,500 insho/oy)\n~500 ta o'quvchi", "$5 (Arzon VPS/Cloud)", "$0 (Bepul)", "~$4.0 (52,000 so'm)", "~$9.0 (115,000 so'm)"],
        ["Katta maktab (10,000 insho/oy)\n~2,000 ta o'quvchi", "$7 (Kuchli VPS)", "$0 (Bepul)", "~$15.0 (195,000 so'm)", "~$22.0 (280,000 so'm)"],
    ]

    for col_idx, text in enumerate(headers):
        cell = table.cell(0, col_idx)
        cell.fill.solid()
        cell.fill.fore_color.rgb = PRIMARY
        p = cell.text_frame.paragraphs[0]
        p.text = text
        p.alignment = PP_ALIGN.CENTER
        p.font.size = Pt(13)
        p.font.bold = True
        p.font.color.rgb = RGBColor(255, 255, 255)

    for row_idx, row_data in enumerate(data):
        for col_idx, text in enumerate(row_data):
            cell = table.cell(row_idx + 1, col_idx)
            cell.fill.solid()
            cell.fill.fore_color.rgb = CARD_BG if row_idx % 2 == 0 else RGBColor(38, 52, 74)
            p = cell.text_frame.paragraphs[0]
            p.text = text
            p.alignment = PP_ALIGN.CENTER
            p.font.size = Pt(12)
            if col_idx == 4:
                p.font.bold = True
                p.font.color.rgb = SUCCESS
            else:
                p.font.color.rgb = TEXT_LIGHT

    # Key insight card
    c_ins = add_card(s6, Inches(0.8), Inches(5.3), Inches(11.7), Inches(1.7))
    tb_ins = s6.shapes.add_textbox(Inches(1.0), Inches(5.4), Inches(11.3), Inches(1.5))
    tf_ins = tb_ins.text_frame
    tf_ins.word_wrap = True

    p1 = tf_ins.paragraphs[0]
    p1.text = "🎯 Asosiy Xulosa va Tejamkorlik Ko'rsatkichi:"
    p1.font.size = Pt(15)
    p1.font.bold = True
    p1.font.color.rgb = CYAN
    p1.space_after = Pt(6)

    p2 = tf_ins.add_paragraph()
    p2.text = "• Hatto 10,000 ta insho tekshirilganda ham oylik barcha texnik xarajatlar $25 (300 ming so'm) atrofida bo'ladi!\n• Bironta o'qituvchining maoshi yoki ish vaqti bu darajada tejamkor va kengayuvchan (scalable) bo'la olmaydi."
    p2.font.size = Pt(13)
    p2.font.color.rgb = TEXT_LIGHT

    # ==========================================
    # SLIDE 7: Qanday Pul Ishlanadi? (Monetizatsiya)
    # ==========================================
    s7 = prs.slides.add_slide(blank_layout)
    add_background(s7)
    add_header(s7, "Monetizatsiya va Biznes Model", "06 / DAROMAD MANBALARI")

    ways = [
        ("⭐️ Telegram Stars Paketlari", "Foydalanuvchi to'g'ridan-to'g'ri Telegram orqali xarid qiladi:\n• 3 ta insho — 15 Stars (~$0.30)\n• 10 ta insho — 35 Stars (~$0.70)\n• 30 ta insho — 75 Stars (~$1.50)\nHech qanday murakkab to'lov tizimi shart emas, barchasi Telegram ichida!", PRIMARY),
        ("🏫 B2B Obuna (O'quv Markazlari)", "IELTS markazlar o'z guruhlariga botni ulab berish uchun oylik to'lov to'laydi:\n• 1 ta guruh uchun oyiga: 150,000 - 300,000 so'm\n• 10 ta o'quv markazi = oyiga 2 - 3 million so'm passiv daromad!", SUCCESS),
        ("🎁 Referal (Do'stini Taklif Qilish)", "Organik va bepul o'sish:\nO'quvchi o'z havolasi bilan do'stini taklif qilsa, unga bepul qo'shimcha insho beriladi. Bot hech qanday reklama xarajatisiz virusli tarqaladi.", CYAN),
    ]

    for i, (wtitle, wdesc, wcol) in enumerate(ways):
        left = Inches(0.8 + i * 3.95)
        top = Inches(1.8)
        add_card(s7, left, top, Inches(3.8), Inches(5.0))

        tb = s7.shapes.add_textbox(left + Inches(0.25), top + Inches(0.25), Inches(3.3), Inches(4.5))
        tf = tb.text_frame
        tf.word_wrap = True

        p1 = tf.paragraphs[0]
        p1.text = wtitle
        p1.font.size = Pt(16)
        p1.font.bold = True
        p1.font.color.rgb = wcol
        p1.space_after = Pt(14)

        p2 = tf.add_paragraph()
        p2.text = wdesc
        p2.font.size = Pt(13)
        p2.font.color.rgb = TEXT_LIGHT

    # ==========================================
    # SLIDE 8: Rentabellik (Unit Economics)
    # ==========================================
    s8 = prs.slides.add_slide(blank_layout)
    add_background(s8)
    add_header(s8, "Rentabellik: Har 1 ta Inshodan Qancha Qoladi?", "07 / UNIT ECONOMICS")

    cards_eco = [
        ("Tushum (1 insho)", "650 - 1,300 so'm", "(Telegram Stars orqali $0.05 - $0.10 sotiladi)", PRIMARY),
        ("Tannarx (AI + Server)", "20 - 25 so'm", "(AI API sarfi ~$0.0015)", RGBColor(248, 113, 113)),
        ("Sof Foyda (1 inshodan)", "630 - 1,275 so'm", "(Har bitta inshodan sof tushum)", SUCCESS),
        ("Foyda Marjasi", "95% - 98%", "(Klassik bizneslarda kamdan-kam ko'rinadigan ko'rsatkich)", CYAN),
    ]

    for i, (etitle, evalue, esub, ecol) in enumerate(cards_eco):
        left = Inches(0.8 + i * 2.95)
        top = Inches(1.8)
        add_card(s8, left, top, Inches(2.8), Inches(3.0))

        tb = s8.shapes.add_textbox(left + Inches(0.15), top + Inches(0.2), Inches(2.5), Inches(2.6))
        tf = tb.text_frame
        tf.word_wrap = True

        p1 = tf.paragraphs[0]
        p1.text = etitle
        p1.alignment = PP_ALIGN.CENTER
        p1.font.size = Pt(14)
        p1.font.bold = True
        p1.font.color.rgb = TEXT_MUTED
        p1.space_after = Pt(14)

        p2 = tf.add_paragraph()
        p2.text = evalue
        p2.alignment = PP_ALIGN.CENTER
        p2.font.size = Pt(20)
        p2.font.bold = True
        p2.font.color.rgb = ecol
        p2.space_after = Pt(10)

        p3 = tf.add_paragraph()
        p3.text = esub
        p3.alignment = PP_ALIGN.CENTER
        p3.font.size = Pt(11)
        p3.font.color.rgb = TEXT_MUTED

    # Bottom comparison banner
    b_card = add_card(s8, Inches(0.8), Inches(5.1), Inches(11.7), Inches(1.9), bg_color=CARD_BG, border_color=SUCCESS)
    b_tb = s8.shapes.add_textbox(Inches(1.0), Inches(5.2), Inches(11.3), Inches(1.7))
    b_tf = b_tb.text_frame
    b_tf.word_wrap = True

    bp1 = b_tf.paragraphs[0]
    bp1.text = "💰 Oylik Moliyaviy Potensial:"
    bp1.font.size = Pt(16)
    bp1.font.bold = True
    bp1.font.color.rgb = SUCCESS
    bp1.space_after = Pt(6)

    bp2 = b_tf.add_paragraph()
    bp2.text = "• Agar oyiga 3,000 ta pullik insho tekshirilsa: ~2,500,000 - 3,500,000 so'm sof daromad.\n• Xarajat esa bor-yo'g'i ~80,000 so'mni tashkil etadi.\n• Bot 1 marta ishga tushirilsa, keyin inson omilisiz to'liq avtomatik rejimda ishlaydi!"
    bp2.font.size = Pt(13)
    bp2.font.color.rgb = TEXT_LIGHT

    # ==========================================
    # SLIDE 9: Xulosa va Keyingi Qadamlar
    # ==========================================
    s9 = prs.slides.add_slide(blank_layout)
    add_background(s9)
    add_header(s9, "Xulosa va Rivojlantirish Qadamlari", "08 / KEYINGI BOSQICHLAR")

    # Left: Afzalliklar
    add_card(s9, Inches(0.8), Inches(1.8), Inches(5.6), Inches(5.0))
    tb_l = s9.shapes.add_textbox(Inches(1.1), Inches(2.0), Inches(5.0), Inches(4.5))
    tf_l = tb_l.text_frame
    tf_l.word_wrap = True
    pl_t = tf_l.paragraphs[0]
    pl_t.text = "🏆 Loyihaning Yutuqlari"
    pl_t.font.size = Pt(20)
    pl_t.font.bold = True
    pl_t.font.color.rgb = SUCCESS
    pl_t.space_after = Pt(16)

    pros = [
        ("Tayyor va sinovdan o'tgan:", "Tizim to'liq yozilgan, arxitekturasi asinxron va minglab yuklamalarga chidamli."),
        ("Nolga teng boshlang'ich risk:", "Bepul AI va server imkoniyatlari orqali $0 boshlang'ich byudjet bilan ishga tushirish mumkin."),
        ("O'qituvchilar uchun haqiqiy najot:", "Ustozlarning insho tekshirishdagi mashaqqatli 90% vaqtini tejab beradi."),
        ("Global masshtablash oson:", "O'zbekiston, MDH yoki butun dunyo IELTS auditoriyasiga oson moslashtiriladi.")
    ]
    for title, desc in pros:
        p = tf_l.add_paragraph()
        p.text = f"✔ {title} "
        p.font.size = Pt(13)
        p.font.bold = True
        p.font.color.rgb = TEXT_LIGHT
        run = p.add_run()
        run.text = desc
        run.font.bold = False
        run.font.color.rgb = TEXT_MUTED
        p.space_after = Pt(10)

    # Right: Reja
    add_card(s9, Inches(6.9), Inches(1.8), Inches(5.6), Inches(5.0))
    tb_r = s9.shapes.add_textbox(Inches(7.2), Inches(2.0), Inches(5.0), Inches(4.5))
    tf_r = tb_r.text_frame
    tf_r.word_wrap = True
    pr_t = tf_r.paragraphs[0]
    pr_t.text = "🚀 Keyingi Qadamlar (Reja)"
    pr_t.font.size = Pt(20)
    pr_t.font.bold = True
    pr_t.font.color.rgb = CYAN
    pr_t.space_after = Pt(16)

    steps_plan = [
        ("1. O'quv markazlar bilan pilot loyiha:", "3-5 ta yetakchi o'quv markazning guruhlariga botni sinov uchun ulab berish."),
        ("2. O'quvchilar bazasini kengaytirish:", "IELTS Telegram kanallar va referal dastur orqali o'quvchilar sonini 5,000+ ga yetkazish."),
        ("3. Telegram Mini App (Web App):", "Keyingi bosqichda insho tahlilini yanada interaktiv va zamonaviy veb-interfeysda ko'rsatish."),
        ("4. Ovozli & Listening tahlillar:", "IELTS Speaking va Listening modullarini ham sun'iy intellekt orqali qamrab olish.")
    ]
    for title, desc in steps_plan:
        p = tf_r.add_paragraph()
        p.text = f"➔ {title} "
        p.font.size = Pt(13)
        p.font.bold = True
        p.font.color.rgb = TEXT_LIGHT
        run = p.add_run()
        run.text = desc
        run.font.bold = False
        run.font.color.rgb = TEXT_MUTED
        p.space_after = Pt(10)

    prs.save(output_path)
    print(f"Taqdimot muvaffaqiyatli saqlandi: {output_path}")

if __name__ == "__main__":
    create_presentation()
