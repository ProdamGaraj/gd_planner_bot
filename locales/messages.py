"""Тексты бота на русском и узбекском."""

LATE_WARNING = {
    "ru": (
        "⚠️ Просим приходить строго к назначенному времени. "
        "При опоздании более чем на 15 минут встреча отменяется — "
        "потребуется оформить новую запись."
    ),
    "uz": (
        "⚠️ Iltimos, belgilangan vaqtda keling. "
        "15 daqiqadan ortiq kechiksangiz, uchrashuv bekor qilinadi — "
        "yangi yozuv rasmiylashtirishingiz kerak bo'ladi."
    ),
}

MESSAGES: dict[str, dict[str, str]] = {
    "welcome": {
        "ru": "👋 Здравствуйте!\nЗдесь можно записаться на встречу с генеральным директором. "
              "Используйте кнопки ниже.",
        "uz": "👋 Assalomu alaykum!\nBu yerda bosh direktor bilan uchrashuvga yozilishingiz mumkin. "
              "Quyidagi tugmalardan foydalaning.",
    },
    "welcome_admin": {
        "ru": "🔧 <b>Админ-панель</b>\n\nИспользуйте кнопки ниже.\n• /start — перезапуск бота",
        "uz": "🔧 <b>Admin panel</b>\n\nQuyidagi tugmalardan foydalaning.\n• /start — botni qayta ishga tushirish",
    },
    "welcome_employee": {
        "ru": "👔 <b>Панель сотрудника</b>\n\nИспользуйте кнопки ниже.\n• /start — перезапуск бота",
        "uz": "👔 <b>Xodim paneli</b>\n\nQuyidagi tugmalardan foydalaning.\n• /start — botni qayta ishga tushirish",
    },
    "language_changed": {
        "ru": "✅ Язык изменён на русский.",
        "uz": "✅ Til o'zbek tiliga o'zgartirildi.",
    },
    "contacts": {
        "ru": "📞 <b>Контакты</b>\n\n📱 Телефон: {phone}\n📍 Адрес: {address}\n🕐 Приём: {hours}",
        "uz": "📞 <b>Aloqa</b>\n\n📱 Telefon: {phone}\n📍 Manzil: {address}\n🕐 Qabul: {hours}",
    },

    "use_menu": {
        "ru": "Пожалуйста, используйте кнопки меню ниже 👇",
        "uz": "Iltimos, quyidagi menyu tugmalaridan foydalaning 👇",
    },

    "session_expired": {
        "ru": "⌛ Эта кнопка устарела. Начните заново через меню.",
        "uz": "⌛ Bu tugma eskirgan. Menyu orqali qaytadan boshlang.",
    },

    # ---------- Запись: договор ----------
    "enter_contract": {
        "ru": "📝 Введите номер вашего договора долевого участия, например 12345-GHP\n\n"
              "⚠️ При записи договор будет привязан к этому Telegram-аккаунту. "
              "Управлять встречами по договору можно будет только с него. "
              "Чтобы привязать договор к другому аккаунту, обратитесь в поддержку.",
        "uz": "📝 Ulushdorlik shartnomasi raqamingizni kiriting, masalan, 12345-GHP\n\n"
              "⚠️ Yozilganda shartnoma ushbu Telegram akkauntiga bog'lanadi. "
              "Shartnoma bo'yicha uchrashuvlarni faqat shu akkauntdan boshqarish mumkin. "
              "Shartnomani boshqa akkauntga bog'lash uchun qo'llab-quvvatlash xizmatiga murojaat qiling.",
    },
    "contract_not_found": {
        "ru": "❌ Договор не найден. Проверьте номер и введите заново:",
        "uz": "❌ Shartnoma topilmadi. Raqamni tekshirib, qaytadan kiriting:",
    },
    "contract_unavailable": {
        "ru": "⚠️ Запись по этому договору недоступна: он привязан к другому Telegram-аккаунту. "
              "Введите другой номер договора или обратитесь в поддержку: {phone}",
        "uz": "⚠️ Bu shartnoma bo'yicha yozilish mumkin emas: u boshqa Telegram akkauntiga bog'langan. "
              "Boshqa shartnoma raqamini kiriting yoki qo'llab-quvvatlash xizmatiga murojaat qiling: {phone}",
    },
    "has_active_meeting": {
        "ru": "ℹ️ По этому договору у вас уже есть встреча {date} в {time}.\n\n"
              "Чтобы выбрать другое время — «📅 Перенести встречу», чтобы отменить — «❌ Отменить встречу».",
        "uz": "ℹ️ Bu shartnoma bo'yicha sizda {date} kuni soat {time} da uchrashuv bor.\n\n"
              "Boshqa vaqtni tanlash uchun — «📅 Uchrashuvni ko'chirish», bekor qilish uchun — "
              "«❌ Uchrashuvni bekor qilish».",
    },
    "no_dates_available": {
        "ru": "😔 Сейчас нет доступных дат для записи по этому договору. Попробуйте позже.",
        "uz": "😔 Hozircha bu shartnoma bo'yicha yozilish uchun mavjud sanalar yo'q. Keyinroq urinib ko'ring.",
    },
    "no_show_ban": {
        "ru": "⚠️ Вы не пришли на встречу {missed}. Поэтому следующая запись возможна не раньше {until}.",
        "uz": "⚠️ Siz {missed} kungi uchrashuvga kelmadingiz. Shu sababli keyingi yozilish {until} dan oldin "
              "mumkin emas.",
    },
    "contract_confirmed": {
        "ru": "✅ Договор подтверждён: {fio}",
        "uz": "✅ Shartnoma tasdiqlandi: {fio}",
    },

    # ---------- Запись: дата и время ----------
    "select_date": {
        "ru": "📅 Выберите дату встречи.\nБлижайшая доступная дата: {date}\n❌ — всё время занято",
        "uz": "📅 Uchrashuv sanasini tanlang.\nEng yaqin mavjud sana: {date}\n❌ — barcha vaqtlar band",
    },
    "date_full_alert": {
        "ru": "❌ На эту дату всё время занято. Выберите другую.",
        "uz": "❌ Bu sanada barcha vaqtlar band. Boshqasini tanlang.",
    },
    "date_unavailable_alert": {
        "ru": "❌ Эта дата недоступна. Выберите другую.",
        "uz": "❌ Bu sana mavjud emas. Boshqasini tanlang.",
    },
    "select_time": {
        "ru": "📅 {date}\n⏰ Выберите время встречи (30 минут):\n\n{late}",
        "uz": "📅 {date}\n⏰ Uchrashuv vaqtini tanlang (30 daqiqa):\n\n{late}",
    },
    "slot_taken_alert": {
        "ru": "❌ Это время занято. Выберите другое.",
        "uz": "❌ Bu vaqt band. Boshqasini tanlang.",
    },
    "slot_selected": {
        "ru": "✅ Выбрано: {date} в {time}",
        "uz": "✅ Tanlandi: {date}, soat {time}",
    },
    "btn_back_to_calendar": {"ru": "⬅️ Назад к календарю", "uz": "⬅️ Taqvimga qaytish"},

    # ---------- Запись: тема ----------
    "enter_topic": {
        "ru": "📝 Кратко опишите тему встречи (до {max} символов) или нажмите «Пропустить».",
        "uz": "📝 Uchrashuv mavzusini qisqacha yozing ({max} belgigacha) yoki «O'tkazib yuborish» tugmasini bosing.",
    },
    "topic_too_long": {
        "ru": "❌ Слишком длинно ({length} симв.). Сократите до {max} символов.",
        "uz": "❌ Juda uzun ({length} belgi). {max} belgigacha qisqartiring.",
    },
    "topic_text_only": {
        "ru": "✏️ Пожалуйста, напишите тему текстом или нажмите «Пропустить».",
        "uz": "✏️ Iltimos, mavzuni matn bilan yozing yoki «O'tkazib yuborish» tugmasini bosing.",
    },
    "btn_skip": {"ru": "⏭ Пропустить", "uz": "⏭ O'tkazib yuborish"},
    "topic_skipped": {"ru": "⏭ Тема не указана.", "uz": "⏭ Mavzu ko'rsatilmadi."},

    # ---------- Запись: телефон ----------
    "enter_phone": {
        "ru": "📱 Отправьте номер телефона кнопкой ниже или введите его вручную:",
        "uz": "📱 Telefon raqamingizni quyidagi tugma orqali yuboring yoki qo'lda kiriting:",
    },
    "phone_choice": {
        "ru": "📱 Использовать сохранённый номер или ввести новый?",
        "uz": "📱 Saqlangan raqamdan foydalanasizmi yoki yangisini kiritasizmi?",
    },
    "btn_use_saved_phone": {"ru": "📱 Использовать {phone}", "uz": "📱 {phone} dan foydalanish"},
    "btn_new_phone": {"ru": "✏️ Ввести новый номер", "uz": "✏️ Yangi raqam kiritish"},
    "btn_send_phone": {"ru": "📱 Отправить мой номер", "uz": "📱 Raqamimni yuborish"},
    "invalid_phone": {
        "ru": "❌ Допускаются только номера Узбекистана (+998), России и Казахстана (+7). Попробуйте снова.",
        "uz": "❌ Faqat O'zbekiston (+998), Rossiya va Qozog'iston (+7) raqamlari qabul qilinadi. "
              "Qayta urinib ko'ring.",
    },

    # ---------- Запись: итог ----------
    "booking_confirmed": {
        "ru": "✅ Вы записаны на встречу с генеральным директором!\n\n"
              "📅 Дата: {date}\n⏰ Время: {time}\n📍 Адрес: {address}\n"
              "📄 Договор: {contract}\n👤 ФИО: {fio}\n📱 Телефон: {phone}\n📝 Тема: {topic}\n\n{late}",
        "uz": "✅ Siz bosh direktor bilan uchrashuvga yozildingiz!\n\n"
              "📅 Sana: {date}\n⏰ Vaqt: {time}\n📍 Manzil: {address}\n"
              "📄 Shartnoma: {contract}\n👤 FIO: {fio}\n📱 Telefon: {phone}\n📝 Mavzu: {topic}\n\n{late}",
    },
    "error_slot_taken": {
        "ru": "⚠️ Извините, это время только что заняли. Выберите другое:",
        "uz": "⚠️ Kechirasiz, bu vaqt hozirgina band qilindi. Boshqasini tanlang:",
    },
    "error_date_unavailable": {
        "ru": "⚠️ Эта дата больше недоступна. Выберите другую:",
        "uz": "⚠️ Bu sana endi mavjud emas. Boshqasini tanlang:",
    },

    # ---------- Отмена встречи ----------
    "cancel_rule": {
        "ru": "Отменить или перенести встречу можно не позднее чем за один рабочий день (если до 12:00) "
              "или за два рабочих дня (после 12:00).",
        "uz": "Uchrashuvni kamida bir ish kuni oldin (soat 12:00 gacha) "
              "yoki ikki ish kuni oldin (soat 12:00 dan keyin) bekor qilish yoki ko'chirish mumkin.",
    },

    # ---------- Мои встречи ----------
    "no_meetings": {
        "ru": "📋 У вас нет предстоящих встреч.",
        "uz": "📋 Sizda rejalashtirilgan uchrashuvlar yo'q.",
    },
    "my_meetings_header": {"ru": "📋 Ваши встречи:", "uz": "📋 Sizning uchrashuvlaringiz:"},
    "my_meeting_item": {
        "ru": "📅 {date} ⏰ {time}\n📄 Договор: {contract}\n📝 Тема: {topic}",
        "uz": "📅 {date} ⏰ {time}\n📄 Shartnoma: {contract}\n📝 Mavzu: {topic}",
    },
    "my_meetings_footer": {
        "ru": "📍 Адрес: {address}\n\n{late}",
        "uz": "📍 Manzil: {address}\n\n{late}",
    },

    # ---------- Перенос ----------
    "no_meetings_to_reschedule": {
        "ru": "📋 У вас нет активных встреч для переноса.",
        "uz": "📋 Sizda ko'chirish uchun faol uchrashuvlar yo'q.",
    },
    "select_meeting_to_reschedule": {
        "ru": "📋 Выберите встречу для переноса:\n🔒 — перенести уже нельзя\n\n{rule}",
        "uz": "📋 Ko'chirish uchun uchrashuvni tanlang:\n🔒 — ko'chirib bo'lmaydi\n\n{rule}",
    },
    "all_meetings_locked_reschedule": {
        "ru": "🔒 Ваши встречи уже нельзя перенести через бота.\n\n{rule}\n\n"
              "Если не сможете прийти, позвоните: {phone}",
        "uz": "🔒 Uchrashuvlaringizni bot orqali ko'chirib bo'lmaydi.\n\n{rule}\n\n"
              "Kela olmasangiz, qo'ng'iroq qiling: {phone}",
    },
    "reschedule_locked_alert": {
        "ru": "🔒 Срок переноса этой встречи истёк.",
        "uz": "🔒 Bu uchrashuvni ko'chirish muddati o'tgan.",
    },
    "reschedule_header": {
        "ru": "🔄 Перенос встречи {date} в {time}",
        "uz": "🔄 {date} kuni soat {time} dagi uchrashuvni ko'chirish",
    },
    "confirm_reschedule": {
        "ru": "⚠️ Перенести встречу?\n\nБыло: {old_date} в {old_time}\nСтанет: {new_date} в {new_time}",
        "uz": "⚠️ Uchrashuvni ko'chirasizmi?\n\nOldin: {old_date}, soat {old_time}\n"
              "Keyin: {new_date}, soat {new_time}",
    },
    "btn_confirm_reschedule": {"ru": "✅ Да, перенести", "uz": "✅ Ha, ko'chirish"},
    "meeting_rescheduled": {
        "ru": "✅ Встреча перенесена!\n\n📅 Дата: {date}\n⏰ Время: {time}\n📍 Адрес: {address}\n\n{late}",
        "uz": "✅ Uchrashuv ko'chirildi!\n\n📅 Sana: {date}\n⏰ Vaqt: {time}\n📍 Manzil: {address}\n\n{late}",
    },
    "reschedule_error_too_late": {
        "ru": "🔒 Срок переноса этой встречи истёк. Если не сможете прийти, позвоните: {phone}",
        "uz": "🔒 Bu uchrashuvni ko'chirish muddati o'tgan. Kela olmasangiz, qo'ng'iroq qiling: {phone}",
    },

    # ---------- Напоминания ----------
    "reminder_day": {
        "ru": "🔔 Напоминание!\n\nЗавтра у вас встреча с генеральным директором.\n\n"
              "📅 Дата: {date}\n⏰ Время: {time}\n📍 Адрес: {address}\n\n{late}",
        "uz": "🔔 Eslatma!\n\nErtaga sizda bosh direktor bilan uchrashuv bor.\n\n"
              "📅 Sana: {date}\n⏰ Vaqt: {time}\n📍 Manzil: {address}\n\n{late}",
    },
    "reminder_hour": {
        "ru": "🔔 Напоминание!\n\nСегодня в {time} у вас встреча с генеральным директором.\n\n"
              "📅 Дата: {date}\n📍 Адрес: {address}\n\n{late}",
        "uz": "🔔 Eslatma!\n\nBugun soat {time} da sizda bosh direktor bilan uchrashuv bor.\n\n"
              "📅 Sana: {date}\n📍 Manzil: {address}\n\n{late}",
    },
    "no_meetings_to_cancel": {
        "ru": "📋 У вас нет активных встреч для отмены.",
        "uz": "📋 Sizda bekor qilish uchun faol uchrashuvlar yo'q.",
    },
    "select_meeting_to_cancel": {
        "ru": "📋 Выберите встречу для отмены:\n🔒 — отменить уже нельзя\n\n{rule}",
        "uz": "📋 Bekor qilish uchun uchrashuvni tanlang:\n🔒 — bekor qilib bo'lmaydi\n\n{rule}",
    },
    "all_meetings_locked": {
        "ru": "🔒 Ваши встречи уже нельзя отменить через бота.\n\n{rule}\n\n"
              "Если не сможете прийти, позвоните: {phone}",
        "uz": "🔒 Uchrashuvlaringizni bot orqali bekor qilib bo'lmaydi.\n\n{rule}\n\n"
              "Kela olmasangiz, qo'ng'iroq qiling: {phone}",
    },
    "cancel_locked_alert": {
        "ru": "🔒 Срок отмены этой встречи истёк.",
        "uz": "🔒 Bu uchrashuvni bekor qilish muddati o'tgan.",
    },
    "confirm_cancel": {
        "ru": "⚠️ Отменить встречу?\n\n📅 Дата: {date}\n⏰ Время: {time}\n📄 Договор: {contract}",
        "uz": "⚠️ Uchrashuvni bekor qilasizmi?\n\n📅 Sana: {date}\n⏰ Vaqt: {time}\n📄 Shartnoma: {contract}",
    },
    "btn_confirm_cancel": {"ru": "✅ Да, отменить", "uz": "✅ Ha, bekor qilish"},
    "btn_keep": {"ru": "❌ Нет, оставить", "uz": "❌ Yo'q, qoldirish"},
    "btn_back": {"ru": "🔙 Назад", "uz": "🔙 Orqaga"},
    "meeting_cancelled": {
        "ru": "✅ Встреча {date} в {time} отменена.",
        "uz": "✅ {date} kuni soat {time} dagi uchrashuv bekor qilindi.",
    },
    "cancel_aborted": {
        "ru": "↩️ Встречи остались без изменений.",
        "uz": "↩️ Uchrashuvlar o'zgarishsiz qoldi.",
    },
    "cancel_error_too_late": {
        "ru": "🔒 Срок отмены этой встречи истёк. Если не сможете прийти, позвоните: {phone}",
        "uz": "🔒 Bu uchrashuvni bekor qilish muddati o'tgan. Kela olmasangiz, qo'ng'iroq qiling: {phone}",
    },
    "cancel_error_not_found": {
        "ru": "⚠️ Встреча не найдена или уже отменена.",
        "uz": "⚠️ Uchrashuv topilmadi yoki allaqachon bekor qilingan.",
    },

    # ---------- Отмена со стороны компании ----------
    "meeting_cancelled_by_company": {
        "ru": "ℹ️ Ваша встреча {date} в {time} отменена: {reason}.\n\n"
              "Пожалуйста, выберите другое время через «📝 Записаться на встречу».",
        "uz": "ℹ️ {date} kuni soat {time} dagi uchrashuvingiz bekor qilindi: {reason}.\n\n"
              "Iltimos, «📝 Uchrashuvga yozilish» tugmasi orqali boshqa vaqtni tanlang.",
    },
    "cancel_reason_holiday": {
        "ru": "этот день стал нерабочим",
        "uz": "bu kun dam olish kuniga aylandi",
    },
    "cancel_reason_ceo": {
        "ru": "генеральный директор не сможет провести встречу в это время",
        "uz": "bosh direktor bu vaqtda uchrashuv o'tkaza olmaydi",
    },
}


MONTHS = {
    "ru": ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
           "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"],
    "uz": ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
           "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"],
}

WEEKDAYS = {
    "ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
    "uz": ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"],
}


def get_message(key: str, lang: str = "ru", **kwargs) -> str:
    variants = MESSAGES.get(key, {})
    msg = variants.get(lang) or variants.get("ru") or key
    return msg.format(**kwargs) if kwargs else msg
