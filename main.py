import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
import nltk
from nltk.corpus import words
import random
import aiohttp
import os
from pathlib import Path
from collections import defaultdict
import requests
import csv
from datetime import datetime, timedelta

nltk.download('words')

bot = Bot(token="")
dp = Dispatcher()

ru_to_en = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
}

def load_checked_usernames():
    checked = {}
    try:
        with open('checked_usernames.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                check_date = datetime.fromisoformat(row['check_date'])
                if datetime.now() - check_date <= timedelta(days=7):
                    checked[row['username']] = row['available'].lower() == 'true'
        print(f"Загружено {len(checked)} проверенных никнеймов из CSV")
    except FileNotFoundError:
        print("CSV файл с проверенными никнеймами не найден")
    return checked

def save_checked_username(username, is_available):
    file_exists = os.path.isfile('checked_usernames.csv')
    
    with open('checked_usernames.csv', 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['username', 'available', 'check_date'])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            'username': username,
            'available': str(is_available),
            'check_date': datetime.now().isoformat()
        })

checked_usernames_cache = load_checked_usernames()

used_words_per_user = defaultdict(set)

def download_russian_words():
    sources = [
        "https://raw.githubusercontent.com/danakt/russian-words/master/russian.txt",
        "https://raw.githubusercontent.com/Harrix/Russian-Nouns/main/dist/russian_nouns.txt",
        "https://raw.githubusercontent.com/hingston/russian/master/50000-russian-words.txt"
    ]
    
    all_words = set()
    
    for url in sources:
        try:
            response = requests.get(url)
            if response.status_code == 200:
                words = response.text.split('\n')
                all_words.update(word.strip().lower() for word in words if word.strip())
                print(f"Загружено {len(words)} слов из {url}")
        except Exception as e:
            print(f"Ошибка при загрузке {url}: {e}")
    
    filtered_words = {
        word for word in all_words 
        if len(word) >= 4
        and len(word) <= 20
        and word.isalpha()
        and all(char in ru_to_en for char in word)
    }
    
    with open("russian_words.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(filtered_words)))
    
    print(f"Сохранено {len(filtered_words)} уникальных слов в russian_words.txt")
    return list(filtered_words)

def load_russian_words():
    """Загружает список русских слов из файла или скачивает новый"""
    words_file = Path("russian_words.txt")
    
    if not words_file.exists():
        print("Словарь не найден. Скачиваю новый словарь...")
        words = download_russian_words()
    else:
        if words_file.stat().st_size < 10000:
            print("Словарь слишком мал. Скачиваю новый словарь...")
            words = download_russian_words()
        else:
            with open(words_file, "r", encoding="utf-8") as f:
                words = [word.strip() for word in f.readlines() if word.strip()]
    
    print(f"Загружено {len(words)} слов из словаря")
    return words

async def check_username(session, username):
    headers = {
        "User-Agent": "",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    }
    
    try:
        check_url = f"https://fragment.com/username/{username}"
        async with session.get(check_url, headers=headers, allow_redirects=False) as response:
            is_available = response.status != 200
            
            print(f"Проверка @{username} (статус {response.status}):")
            if is_available:
                print(f"✅ @{username} свободен")
            else:
                print(f"❌ @{username} занят")
                
            print(f"URL: {check_url}")
            print(f"Статус: {response.status}")
            
            return is_available
            
    except Exception as e:
        print(f"❌ Ошибка при проверке @{username}: {e}")
        return False

async def transliterate(text):
    text = text.lower()
    result = ''
    for char in text:
        result += ru_to_en.get(char, char)
    return result

async def get_word_with_correct_translit_length(words, target_length):
    """Находит слово, которое после транслитерации будет нужной длины"""
    for word in words:
        translit = await transliterate(word)
        if len(translit) == target_length:
            return word, translit
    return None, None

async def check_username_with_retry(session, username, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = await check_username(session, username)
            return result
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Ошибка при проверке {username}: {e}")
                return False
            await asyncio.sleep(1)
    return False

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я генератор никнеймов для Telegram.\n"
        "Используй /generate <длина_ника> <количество> для генерации никнеймов.\n"
        "Например: /generate 6 50 - сгенерирует 50 никнеймов длиной 6 букв"
    )

@dp.message(Command("generate"))
async def generate_usernames(message: types.Message):
    try:
        args = message.text.split()
        if len(args) != 3:
            await message.answer("Пожалуйста, укажите длину ника и количество.\nПример: /generate 6 50")
            return
            
        name_length = int(args[1])
        count = int(args[2])
        
        if name_length < 4 or name_length > 20:
            await message.answer("Длина ника должна быть от 4 до 20 символов")
            return
            
        if count > 150:
            await message.answer("Максимальное количество - 150 никнеймов за раз")
            return
        
        await message.answer(f"Начинаю генерацию никнеймов длиной {name_length} букв... Это может занять некоторое время.")
        
        russian_words = load_russian_words()
        
        valid_words = []
        for word in russian_words:
            translit = await transliterate(word)
            if len(translit) == name_length:
                valid_words.append(word)
        
        if not valid_words:
            await message.answer(f"❌ Не найдено слов, дающих никнейм длиной {name_length} букв после транслитерации")
            return
            
        print(f"Найдено {len(valid_words)} слов, дающих никнейм длиной {name_length} букв")
        
        user_used_words = used_words_per_user[message.from_user.id]
        
        available_usernames = []
        checked_count = 0
        status_message = await message.answer("Проверено: 0 никнеймов\nНайдено доступных: 0")
        
        async with aiohttp.ClientSession() as session:
            while len(available_usernames) < count and checked_count < count:
                available_words = [w for w in valid_words if w not in user_used_words]
                if not available_words:
                    await message.answer("⚠️ Закончились доступные слова для проверки. Очищаю историю проверок.")
                    user_used_words.clear()
                    available_words = valid_words
                
                word = random.choice(available_words)
                username = await transliterate(word)
                
                if len(username) != name_length:
                    continue
                    
                checked_count += 1
                user_used_words.add(word)
                
                print(f"Проверяю никнейм: {username} ({checked_count}/{count} проверено)")
                
                if username in checked_usernames_cache:
                    is_available = checked_usernames_cache[username]
                    print(f"[Кэш] Найден результат для @{username}")
                else:
                    is_available = await check_username(session, username)
                    checked_usernames_cache[username] = is_available
                    save_checked_username(username, is_available)
                
                if is_available:
                    available_usernames.append(f"@{username} ({word})")
                    print(f"✅ Никнейм @{username} свободен! ({len(available_usernames)}/{count})")
                    
                    if len(available_usernames) % 5 == 0:
                        try:
                            await status_message.edit_text(
                                f"Проверено: {checked_count}/{count} никнеймов\n"
                                f"Найдено доступных: {len(available_usernames)}/{count}\n"
                                f"(Использовано {len(user_used_words)} уникальных слов)"
                            )
                        except:
                            pass
                else:
                    print(f"❌ Никнейм @{username} занят")
                
                await asyncio.sleep(0.5)
        
        if checked_count >= count and len(available_usernames) < count:
            await message.answer(
                f"⚠️ Проверка завершена.\n"
                f"Найдено только {len(available_usernames)} из {count} запрошенных никнеймов.\n"
                f"Проверено {len(user_used_words)} уникальных слов."
            )
        
        if available_usernames:
            filename = f"fragment_usernames_{message.from_user.id}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(available_usernames))
            
            file = FSInputFile(filename)
            await message.answer(f"✅ Готово! Найдено {len(available_usernames)} свободных никнеймов длиной {name_length} букв:")
            await message.answer("\n".join(available_usernames[:10]) + "\n...")
            await message.answer_document(file, caption=f"Полный список доступных никнеймов длиной {name_length} букв")
            
            os.remove(filename)
        else:
            await message.answer("❌ К сожалению, не удалось найти свободные никнеймы.")
        
    except (IndexError, ValueError):
        await message.answer("Пожалуйста, укажите длину ника и количество.\nПример: /generate 6 50")

@dp.message(Command("clear_cache"))
async def clear_cache(message: types.Message):
    global checked_usernames_cache
    checked_usernames_cache.clear()
    if os.path.exists('checked_usernames.csv'):
        os.remove('checked_usernames.csv')
    await message.answer("✅ Кэш проверенных никнеймов очищен")

@dp.message(Command("check"))
async def check_single_username(message: types.Message):
    try:
        username = message.text.split()[1].strip('@')
        
        if username in checked_usernames_cache:
            is_available = checked_usernames_cache[username]
            await message.answer(
                f"[Кэш] {'✅ Доступен' if is_available else '❌ Занят'}: @{username}"
            )
            return
            
        async with aiohttp.ClientSession() as session:
            is_available = await check_username(session, username)
            checked_usernames_cache[username] = is_available
            save_checked_username(username, is_available)
            
            await message.answer(
                f"{'✅ Доступен' if is_available else '❌ Занят'}: @{username}"
            )
    except (IndexError, ValueError):
        await message.answer("Пожалуйста, укажите никнейм для проверки.\nПример: /check username")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
