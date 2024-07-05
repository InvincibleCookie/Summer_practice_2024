import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import requests
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv
import os
import re

load_dotenv()

logging.basicConfig(level=logging.INFO)

API_TOKEN = os.getenv('API_TOKEN')

DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASS = os.getenv('DB_PASS')

try:
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=DB_PORT
    )
    cursor = conn.cursor()
    logging.info("Successfully connected to PostgreSQL")
except psycopg2.Error as err:
    logging.error(f"Error connecting to PostgreSQL: {err}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [
            InlineKeyboardButton("Название", callback_data='name'),
            InlineKeyboardButton("Зарплата", callback_data='salary')
        ],
        [InlineKeyboardButton("График работы", callback_data='schedule'),
         InlineKeyboardButton("Стаж", callback_data='experience')
         ],
        [InlineKeyboardButton("Страна", callback_data='country')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_chat.send_message('Выберите параметр поиска:', reply_markup=reply_markup)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    match query.data:
        case 'search':
            await update.effective_chat.send_message("Идёт поиск")
            await to_search(update, context)
        case 'filter_search':
            await update.effective_chat.send_message("Идёт поиск")
            await filter_by(update, context)
        case 'reset_search_filters':
            context.user_data.clear()
            await update.effective_chat.send_message("Поисковые параметры сброшены.")
            await start(update, context)
        case 'reset_filters':
            await reset_filters(update, context)
        case 'to_start':
            await start(update, context)
        case 'name':
            await query.edit_message_text(text="Введите название работы:")
            context.user_data['next'] = 'name_input'
        case 'salary':
            keyboard = [
                [InlineKeyboardButton("Российский рубль ₽", callback_data='s_RUR')],
                [InlineKeyboardButton("Американский доллар $", callback_data='s_USD')],
                [InlineKeyboardButton("Евро €", callback_data='s_EUR'),
                 InlineKeyboardButton("Тенге ₸", callback_data='KZT')],
                [InlineKeyboardButton("Узбекский сум Soʻm", callback_data='s_UZS')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text="В какой валюте? (значения пересчитываются по текущим курсам ЦБ РФ):",
                reply_markup=reply_markup
            )
        case 's_RUR' | 's_USD' | 's_EUR':
            context.user_data['s_currency'] = query.data[2:]
            await query.edit_message_text(
                text="Введите ожидаемую заработную плату (При указании значения будут найдены вакансии, "
                     "в которых вилка зарплаты близка к указанной в запросе):"
            )
            context.user_data['next'] = 'salary_input'
        case 'schedule':
            keyboard = [
                [InlineKeyboardButton("Полный день", callback_data='fullDay')],
                [InlineKeyboardButton("Сменный график", callback_data='shift')],
                [InlineKeyboardButton("Гибкий график", callback_data='flexible')],
                [InlineKeyboardButton("Удаленная работа", callback_data='remote')],
                [InlineKeyboardButton("Вахтовый метод", callback_data='flyInFlyOut')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text="Выберите подходящий график работы:", reply_markup=reply_markup)
        case 'fullDay' | 'shift' | 'flexible' | 'remote' | 'flyInFlyOut':
            context.user_data['schedule'] = query.data
            await start_menu(update, context)
        case 'experience':
            keyboard = [
                [InlineKeyboardButton("Без опыта", callback_data='noExperience'),
                 InlineKeyboardButton("От 1 до 3 лет", callback_data='between1And3')],
                [InlineKeyboardButton("От 3 до 6 лет", callback_data='between3And6'),
                 InlineKeyboardButton("Более 6 лет", callback_data='moreThan6')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text='Выберите стаж:', reply_markup=reply_markup)
        case 'noExperience' | 'between1And3' | 'between3And6' | 'moreThan6':

            context.user_data['experience'] = query.data
            await start_menu(update, context)
        case 'country':
            await query.edit_message_text(text="Введите страну:")
            context.user_data['next'] = 'country_input'
        case 'city':
            await query.edit_message_text(text="Введите город (или регион):")
            context.user_data['next'] = 'city_input'
        case 'salary_size':
            keyboard = [
                [InlineKeyboardButton("₽", callback_data='RUR')],
                [InlineKeyboardButton("$", callback_data='USD'),
                 InlineKeyboardButton("€", callback_data='EUR')],
                [InlineKeyboardButton("$", callback_data='KZT'),
                 InlineKeyboardButton("Soʻm", callback_data='UZS')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text='Выберите валюту, в которой хотите получать зарплату',
                reply_markup=reply_markup
            )
        case 'RUR' | 'USD' | 'EUR' | 'KZT' | 'UZS':
            context.user_data['currency'] = query.data
            await filter_menu(update, context)
        case 'skills':
            await query.edit_message_text(
                text="Введите через запятую ключевые навыки, по которым искать вакансии \n"
                     "(Пример: git, python, docker):"
            )
            context.user_data['next'] = 'skills_input'
        case 'employment':
            keyboard = [
                [InlineKeyboardButton("Полная занятость", callback_data='Полная занятость'),
                 InlineKeyboardButton("Частичная занятость", callback_data='Частичная занятость')],
                [InlineKeyboardButton("Стажировка", callback_data='Стажировка')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text='Выберите занятость', reply_markup=reply_markup)
        case 'Полная занятость' | 'Частичная занятость' | 'Стажировка':
            context.user_data['employment'] = query.data
            await filter_menu(update, context)
        case 'languages':
            await query.edit_message_text(
                text="Напишите языки, которые вы знаете помимо русского и ваш уровень "
                     "владения этим языком через запятую и пробел. \n\n"
                     "Уровни владения:\nA1 — Начальный\nA2 — Элементарный\nB1 — Средний\nB2 — Средне-продвинутый"
                     "\nC1 — Продвинутый\nC2 — В совершенстве\n"
                     "\n Пример: Английский B2, Китайский A1"
            )
            context.user_data['next'] = 'language_input'


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    next_action = context.user_data.get('next')

    match next_action:
        case 'name_input':
            profession_name = update.message.text.capitalize()
            context.user_data['name'] = profession_name
            del context.user_data['next']
            await start_menu(update, context)
        case 'salary_input':
            min_salary = update.message.text
            context.user_data['salary'] = min_salary
            del context.user_data['next']
            await start_menu(update, context)
        case 'country_input':
            country_name = update.message.text
            areas = requests.get("https://api.hh.ru/areas").json()
            for country in areas:

                if country['name'].lower() == country_name.lower():
                    context.user_data['country_id'] = country['id']
                    context.user_data['country_name'] = country_name
                    del context.user_data['next']
                    await start_menu(update, context)
                    break
            else:
                await update.message.reply_text(f"Такая страна не найдена")
                await start_menu(update, context)
        case 'city_input':
            def find_city_id(city_name, areas):
                for area in areas:
                    if area['name'].lower() == city_name.lower():
                        return area['id']
                    if 'areas' in area:
                        city_id = find_city_id(city_name, area['areas'])
                        if city_id:
                            return city_id
                return None

            city_name = update.message.text
            country_name = context.user_data.get('country_name')
            areas = requests.get("https://api.hh.ru/areas").json()
            for country in areas:
                if country['name'].lower() == country_name.lower():
                    city_id = find_city_id(city_name, country['areas'])
                    if city_id is None:
                        await update.message.reply_text(f"Такой город (регион) не найден")
                        await start_menu(update, context)
                    else:
                        context.user_data['city_id'] = city_id
                        context.user_data['city_name'] = city_name
                        del context.user_data['next']
                        await start_menu(update, context)
        case 'skills_input':
            skills = update.message.text
            context.user_data['skills'] = skills
            del context.user_data['next']
            await filter_menu(update, context)
        case 'language_input':
            languages = update.message.text
            context.user_data['languages'] = languages
            del context.user_data['next']
            await filter_menu(update, context)


async def start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get('name')
    salary = context.user_data.get('salary')
    experience = context.user_data.get('experience')
    schedule = context.user_data.get('schedule')
    country = context.user_data.get('country_id')
    city = context.user_data.get('city_id')

    buttons = []

    if not name:
        buttons.append(InlineKeyboardButton("Название", callback_data='name'))
    if not salary:
        buttons.append(InlineKeyboardButton("Зарплата", callback_data='salary'))
    if not schedule:
        buttons.append(InlineKeyboardButton("График работы", callback_data='schedule'))
    if not experience:
        buttons.append(InlineKeyboardButton("Стаж", callback_data='experience'))
    if not country:
        buttons.append(InlineKeyboardButton("Страна", callback_data='country'))
    elif not city:
        buttons.append(InlineKeyboardButton("Город", callback_data='city'))

    # Разделить кнопки на строки по две
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

    if name or salary or experience or schedule or country:
        keyboard.append([
            InlineKeyboardButton("Сбросить", callback_data='reset_search_filters'),
            InlineKeyboardButton("Поиск", callback_data='search')
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_chat.send_message('Выберите параметр поиска:', reply_markup=reply_markup)


async def to_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = context.user_data.get('name')
    salary = context.user_data.get('salary')
    schedule = context.user_data.get('schedule')
    experience = context.user_data.get('experience')
    s_currency = context.user_data.get('s_currency')
    country = context.user_data.get('country_id')
    city = context.user_data.get('city_id')

    url = 'https://api.hh.ru/vacancies'
    params = {
        'per_page': '20',
        'only_with_salary': 'true'
    }
    if title:
        params['text'] = title
    if salary:
        params['salary'] = salary
    if schedule:
        params['schedule'] = schedule
    if s_currency:
        params['currency'] = s_currency
    if experience:
        params['experience'] = experience
    if city:
        params['area'] = city
    elif country:
        params['area'] = country

    response = requests.get(url, params=params)
    if response.status_code == 200:
        vacancies = response.json().get('items', [])
        if vacancies:
            areas = requests.get("https://api.hh.ru/areas").json()
            message_parts = []
            for vacancy in vacancies:
                vacancy_data = requests.get(f"https://api.hh.ru/vacancies/{vacancy.get('id')}").json()
                if vacancy_data['key_skills']:
                    key_skills_str = ', '.join(skill['name'] for skill in vacancy_data['key_skills'])
                else:
                    key_skills_str = ''

                if vacancy_data['languages']:
                    languages_str = ', '.join(
                        f"{lang['name']} {lang['level']['name'][:2]}" for lang in vacancy_data['languages'])
                else:
                    languages_str = ''

                def find_country_city_by_id(area_id, areas, parent_country=""):
                    for area in areas:
                        if area['id'] == str(area_id):
                            if not area['parent_id']:
                                return area['name'], ""
                            else:
                                return parent_country, area['name']
                        if 'areas' in area and area['areas']:
                            country, city = find_country_city_by_id(area_id, area['areas'],
                                                                    parent_country if parent_country else area['name'])
                            if country:
                                return country, city
                    return "", ""

                country, city = find_country_city_by_id(vacancy_data['area']['id'], areas)
                cursor.execute("""
                    INSERT INTO vacancies (
                        id, name, country, city, salary_from, salary_to, currency, gross, type_id, 
                        experience_id, schedule_id, employment_name, description, key_skills, 
                        accept_handicapped, accept_kids, employer_name, alternate_url, languages,
                        professional_role
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                """, (
                    vacancy_data['id'], vacancy_data['name'], country, city,
                    vacancy_data['salary']['from'], vacancy_data['salary']['to'],
                    vacancy_data['salary']['currency'], vacancy_data['salary']['gross'],
                    vacancy_data['type']['id'], vacancy_data['experience']['id'],
                    vacancy_data['schedule']['id'], vacancy_data['employment']['name'],
                    vacancy_data['description'], key_skills_str,
                    vacancy_data['accept_handicapped'], vacancy_data['accept_kids'],
                    vacancy_data['employer']['name'], vacancy_data['alternate_url'],
                    languages_str, vacancy_data['professional_roles'][0]['name']
                ))
                conn.commit()
            for vacancy in vacancies[:5]:
                message_part = (
                    f"{vacancy['name']} в {vacancy['employer']['name']}, {vacancy['area']['name']}\n"
                    f"{vacancy['alternate_url']}"
                )
                message_parts.append(message_part)

            message = "\n\n".join(message_parts)
            await update.effective_chat.send_message(message)
            await filter_menu(update, context)

        else:
            await update.effective_chat.send_message('По вашему запросу вакансии не найдены.')
            context.user_data.clear()
            await start(update, context)
    else:
        await update.effective_chat.send_message('Ошибка при получении данных с hh.ru')
        context.user_data.clear()
        await start(update, context)


async def filter_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    currency = context.user_data.get('currency')
    employment = context.user_data.get('employment')
    skills = context.user_data.get('skills')
    languages = context.user_data.get('languages')

    buttons = []

    if not currency:
        buttons.append(InlineKeyboardButton("Размер зарплаты", callback_data='salary_size'))
    if not skills:
        buttons.append(InlineKeyboardButton("Ключевые навыки", callback_data='skills'))
    if not employment:
        buttons.append(InlineKeyboardButton("Занятость", callback_data='employment'))
    if not languages:
        buttons.append(InlineKeyboardButton("Языки", callback_data='languages'))

    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

    if currency or skills or employment or languages:
        keyboard.append([
            InlineKeyboardButton("Сбросить фильтры", callback_data='reset_filters'),
            InlineKeyboardButton("Поиск", callback_data='filter_search')
        ])

    keyboard.append([InlineKeyboardButton("Вернуться на начало", callback_data='to_start')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_chat.send_message('Выберите параметр для фильтрации из базы данных:',
                                             reply_markup=reply_markup)


async def reset_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keys_to_clear = ['currency', 'skills', 'employment', 'languages']
    for key in keys_to_clear:
        if key in context.user_data:
            del context.user_data[key]
    await update.effective_chat.send_message("Фильтры сброшены.")
    await filter_menu(update, context)


async def filter_by(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get('name')
    salary = context.user_data.get('salary')
    experience = context.user_data.get('experience')
    schedule = context.user_data.get('schedule')
    country = context.user_data.get('country_name')
    city = context.user_data.get('city_name')

    currency = context.user_data.get('currency')
    employment = context.user_data.get('employment')
    skills = context.user_data.get('skills')
    languages = context.user_data.get('languages')

    conditions = []
    params = []
    if currency:
        conditions.append("currency = %s")
        params.append(currency)

    if name:
        conditions.append("(name ILIKE %s OR professional_role ILIKE %s OR description ILIKE %s)")
        params.extend([f"%{name}%", f"%{name}%", f"%{name}%"])

    if schedule:
        conditions.append("schedule_id = %s")
        params.append(schedule)

    if city:
        conditions.append("city = %s")
        params.append(city)

    if country:
        conditions.append("country = %s")
        params.append(country)

    if salary:
        conditions.append(
            "((salary_from IS NULL AND salary_to IS NULL) OR (salary_from IS NULL AND salary_to >= %s)"
            " OR (salary_to IS NULL AND salary_from <= %s) OR (salary_from <= %s AND salary_to >= %s))"
        )
        params.extend([salary, salary, salary, salary])

    if experience:
        conditions.append("experience_id = %s")
        params.append(experience)

    if employment:
        conditions.append("employment_name = %s")
        params.append(employment)

    if skills:
        skill_conditions = " AND ".join([f"LOWER(key_skills) ILIKE %s"] * len(skills.split(', ')))
        conditions.append(f"({skill_conditions})")
        params.extend([f"%{skill.lower()}%" for skill in skills.split(', ')])

    base_query = sql.SQL("SELECT * FROM vacancies WHERE " + " AND ".join(conditions))
    if currency:
        base_query += sql.SQL(" ORDER BY COALESCE(salary_to, 0) DESC, COALESCE(salary_from, 0) DESC")

    try:
        cursor.execute(base_query, params)
        results = cursor.fetchall()
        if languages:
            user_languages = parse_languages(languages)
            results = [vacancy for vacancy in results if filter_languages(vacancy[18], user_languages)]
        message_filter_parts = ["Найденные вакансии:\n"]
        if results:
            relevant_results = await update_db(results)
            for vacancy in relevant_results[:5]:
                salary_from = vacancy[4]
                salary_to = vacancy[5]
                currency = vacancy[6]

                if salary_from and salary_to:
                    salary = f"{salary_from} — {salary_to} {currency}"
                elif salary_from:
                    salary = f"От {salary_from} {currency}"
                elif salary_to:
                    salary = f"До {salary_to} {currency}"
                else:
                    salary = "Зарплата не указана"
                message_part = (
                    f"{vacancy[1]}\n{vacancy[16]}\n{salary}\n{vacancy[17]}\n"
                )
                message_filter_parts.append(message_part)
            message = "\n\n".join(message_filter_parts)
            await update.effective_chat.send_message(message)
        else:
            response = "Вакансии не найдены по указанным критериям."
            await update.effective_chat.send_message(response)
    except psycopg2.Error as e:
        logging.error(f"Error executing query: {e}")
        await update.effective_chat.send_message("Произошла ошибка при выполнении запроса.")
    await filter_menu(update, context)


async def update_db(results):
    relevant_vacancies = []
    for vacancy in results:
        response = requests.get(f'https://api.hh.ru/vacancies/{vacancy[0]}')
        data = response.json()
        if data.get('type', {}).get('id') == 'open':
            relevant_vacancies.append(vacancy)
        else:
            try:
                cursor.execute("DELETE FROM vacancies WHERE id = %s", (vacancy[1],))
                conn.commit()
                logging.info(f"Vacancy with id {vacancy[1]} deleted from database")
            except psycopg2.Error as err:
                logging.error(f"Error deleting vacancy with id {vacancy[1]}: {err}")

    return relevant_vacancies


def language_level_to_number(level):
    levels = {
        'A1': 1,
        'A2': 2,
        'B1': 3,
        'B2': 4,
        'C1': 5,
        'C2': 6,
    }
    return levels.get(level, 0)


def parse_languages(languages_str):
    languages = {}
    if languages_str:
        for lang in languages_str.split(', '):
            match = re.match(r'(\w+)\s+(\w\d)', lang)
            if match:
                languages[match.group(1)] = language_level_to_number(match.group(2))
    return languages


def filter_languages(vacancy_languages, user_languages):
    if not vacancy_languages:
        return True
    vacancy_languages = parse_languages(vacancy_languages)
    for lang, level in vacancy_languages.items():

        if lang != 'Русский' and (lang not in user_languages or user_languages[lang] < level):
            return False
    return True


if __name__ == '__main__':
    app = ApplicationBuilder().token(API_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
