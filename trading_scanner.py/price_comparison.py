"""
price_comparison.py

Скрипт сравнивает цены на золото и биржевые индексы, полученные с Yahoo Finance,
с ценами на Bitget (и других биржах через ccxt).

Важный нюанс по Bitget:
  У Bitget в интерфейсе есть отдельные разделы "TradFi" и "Stocks" — это
  токенизированные традиционные активы (акции/индексы), а не обычные крипто-пары.
  Неизвестно заранее, торгуются ли они под теми же тикерами, что и в вашем
  торговом терминале, и доступны ли они через тот же публичный API, который
  использует библиотека ccxt (load_markets/fetch_ticker). Поэтому вместо того,
  чтобы жёстко зашивать угаданные названия тикеров, скрипт САМ сканирует все
  рынки, которые видит ccxt на Bitget, и ищет совпадения по ключевым словам
  (например "XAU", "DJI", "DOW", "US30", "NDX", "NAS100", "USTEC" и т.п.).
  Если совпадений не находится - значит эти инструменты либо недоступны через
  публичный API ccxt, либо называются иначе, и скрипт честно об этом сообщает.

Логика:
  1) Собираем "эталонные" цены с Yahoo Finance (GC=F, ^DJI, ^IXIC).
  2) Сканируем рынки Bitget и ищем совпадения по ключевым словам для каждого
     инструмента (золото, Dow Jones, NASDAQ).
  3) Если совпадение найдено - сравниваем цену и считаем расхождение.
     Если нет - сообщаем, что инструмент недоступен через ccxt на этой бирже.
  4) Проверяем наличие тикеров на TradingView по зашитому словарю.
  5) Если расхождение велико - ищем биржу с ценой ближе всего к Yahoo Finance
     (тоже через автоматический поиск по ключевым словам, а не угаданные тикеры).
  6) Сохраняем итоговую таблицу в CSV.

Запуск: python price_comparison.py
"""

import sys
import subprocess
import importlib
from datetime import datetime


# ---------------------------------------------------------------------------
# 1. Автопроверка и автоустановка недостающих библиотек
# ---------------------------------------------------------------------------
REQUIRED_PACKAGES = {
    "yfinance": "yfinance",
    "ccxt": "ccxt",
    "pandas": "pandas",
}


def ensure_packages_installed(packages: dict) -> None:
    """
    Проверяет наличие каждого пакета. Если пакет не найден - устанавливает
    его через pip прямо из скрипта.
    """
    for import_name, pip_name in packages.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            print(f"[INFO] Библиотека '{import_name}' не найдена. Устанавливаю '{pip_name}'...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])
            except subprocess.CalledProcessError as e:
                print(f"[ОШИБКА] Не удалось установить '{pip_name}': {e}")
                sys.exit(1)


ensure_packages_installed(REQUIRED_PACKAGES)

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("[КРИТИЧЕСКАЯ ОШИБКА] Не удалось импортировать yfinance даже после установки.")
    sys.exit(1)

try:
    import ccxt
except ImportError:
    print("[КРИТИЧЕСКАЯ ОШИБКА] Не удалось импортировать ccxt даже после установки.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 2. Настройки: инструменты и ключевые слова для поиска на биржах
# ---------------------------------------------------------------------------

# Тикеры Yahoo Finance -> человекочитаемое имя инструмента (для вывода и TradingView)
YF_INSTRUMENTS = {
    "GC=F": "XAUUSD",   # золото
    "^DJI": "DJI",       # Dow Jones
    "^IXIC": "NDX",      # NASDAQ
}

# Ключевые слова для автоматического поиска подходящего рынка на бирже.
# Скрипт ищет их как подстроку в ID/символе рынка (без учёта регистра).
# Порядок важен: первое найденное совпадение используется.
SEARCH_KEYWORDS = {
    "XAUUSD": ["XAUT/USDT", "PAXG/USDT", "XAU/USDT", "XAUUSD"],
    "DJI": ["US30", "DJI", "DOWJONES", "DOW30"],
    "NDX": ["NAS100", "USTEC", "NDX", "NASDAQ100"],
}

# Список бирж для проверки (порядок = приоритет; bitget - основная для части 2)
EXCHANGES_TO_CHECK = ["bitget", "binance", "bybit", "okx", "kraken"]

# Зашитый словарь доступности тикеров на TradingView
TRADINGVIEW_TICKERS = {
    "XAUUSD": True,
    "DJI": True,
    "NDX": True,
}

# Пороговые значения вердикта (в процентах)
THRESHOLD_OK = 0.1
THRESHOLD_WARNING = 0.5
THRESHOLD_DEEP_CHECK = 1.0  # если расхождение выше - ищем лучшую биржу


# ---------------------------------------------------------------------------
# 3. ЧАСТЬ 1 — Получение цен с Yahoo Finance
# ---------------------------------------------------------------------------
def get_yahoo_price(ticker: str):
    """
    Получает последнюю доступную цену закрытия по тикеру с Yahoo Finance.
    Возвращает float либо None при ошибке.
    """
    try:
        data = yf.Ticker(ticker).history(period="1d", interval="1m")
        if data.empty:
            # Если минутных данных нет (например, рынок закрыт) - берём дневные
            data = yf.Ticker(ticker).history(period="5d", interval="1d")
        if data.empty:
            print(f"[ПРЕДУПРЕЖДЕНИЕ] Нет данных для {ticker} на Yahoo Finance.")
            return None
        last_price = float(data["Close"].dropna().iloc[-1])
        return last_price
    except Exception as e:
        print(f"[ОШИБКА] Не удалось получить цену {ticker} с Yahoo Finance: {e}")
        return None


def collect_yahoo_prices() -> dict:
    """
    Собирает цены по всем инструментам и выводит их в требуемом формате:
    XAUUSD,31.07.2026,14:00,4981$,Yahoo Finance
    Возвращает словарь {человекочитаемое_имя: цена}
    """
    print("\n=== ЧАСТЬ 1: Цены с Yahoo Finance ===")
    now = datetime.now()
    date_str = now.strftime("%d.%m.%Y")
    time_str = now.strftime("%H:%M")

    prices = {}
    for yf_ticker, name in YF_INSTRUMENTS.items():
        price = get_yahoo_price(yf_ticker)
        prices[name] = price
        if price is not None:
            print(f"{name},{date_str},{time_str},{price:.2f}$,Yahoo Finance")
        else:
            print(f"{name},{date_str},{time_str},НЕТ ДАННЫХ,Yahoo Finance")

    return prices


# ---------------------------------------------------------------------------
# 4. Работа с рынками бирж через ccxt: загрузка и поиск по ключевым словам
# ---------------------------------------------------------------------------
def load_exchange_markets(exchange_id: str):
    """
    Инициализирует биржу через ccxt и загружает список её рынков.
    Возвращает (объект_биржи, словарь_рынков) либо (None, None) при ошибке.
    """
    try:
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({"enableRateLimit": True})
    except AttributeError:
        print(f"[ОШИБКА] Биржа '{exchange_id}' не поддерживается библиотекой ccxt.")
        return None, None
    except Exception as e:
        print(f"[ОШИБКА] Не удалось инициализировать биржу '{exchange_id}': {e}")
        return None, None

    try:
        markets = exchange.load_markets()
        return exchange, markets
    except Exception as e:
        # Сюда попадают ошибки сети, недоступность биржи, региональные блокировки и т.п.
        print(f"[ОШИБКА] Биржа '{exchange_id}' недоступна (нет интернета или блокировка): {e}")
        return None, None


def find_symbol_by_keywords(markets: dict, keywords: list):
    """
    Ищет среди ключей рынков (символов) первое совпадение с одним из ключевых
    слов (без учёта регистра, поиск подстроки). Возвращает найденный символ
    рынка либо None.
    """
    if not markets:
        return None

    market_symbols = list(markets.keys())

    for keyword in keywords:
        keyword_upper = keyword.upper()
        for symbol in market_symbols:
            if keyword_upper in symbol.upper():
                return symbol

    return None


def get_price_for_instrument(exchange_id: str, exchange, markets: dict, name: str):
    """
    Ищет подходящий рынок для инструмента 'name' на уже загруженной бирже
    и возвращает (цена, использованный_символ) либо (None, None), если
    подходящего рынка не нашлось или не удалось получить цену.
    """
    keywords = SEARCH_KEYWORDS.get(name, [])
    symbol = find_symbol_by_keywords(markets, keywords)

    if symbol is None:
        return None, None

    try:
        ticker = exchange.fetch_ticker(symbol)
        last_price = ticker.get("last")
        if last_price is not None:
            return float(last_price), symbol
    except Exception as e:
        print(f"[ПРЕДУПРЕЖДЕНИЕ] Не удалось получить тикер {symbol} на {exchange_id}: {e}")

    return None, None


def calculate_deviation(price_yahoo: float, price_crypto: float) -> float:
    """
    Считает расхождение в процентах: (цена биржи - цена Yahoo) / цена Yahoo * 100
    """
    return (price_crypto - price_yahoo) / price_yahoo * 100.0


def get_verdict(deviation_percent: float) -> str:
    """
    Определяет вердикт по модулю расхождения в процентах.
    """
    abs_dev = abs(deviation_percent)
    if abs_dev < THRESHOLD_OK:
        return "ПОДХОДИТ"
    elif abs_dev <= THRESHOLD_WARNING:
        return "ОПАСНО"
    else:
        return "НЕ ТОРГОВАТЬ"


# ---------------------------------------------------------------------------
# 5. ЧАСТЬ 3 — Проверка доступности на TradingView
# ---------------------------------------------------------------------------
def check_tradingview(name: str) -> bool:
    """
    Проверяет наличие тикера в зашитом словаре TRADINGVIEW_TICKERS.
    """
    available = TRADINGVIEW_TICKERS.get(name, False)
    status = "ДА" if available else "НЕТ"
    print(f"{name} есть на TradingView: {status}")
    if available:
        print(f"Тикер {name} доступен на TradingView — можно строить график")
    return available


# ---------------------------------------------------------------------------
# 6. ДОПОЛНИТЕЛЬНО — Поиск лучшей биржи при большом расхождении
# ---------------------------------------------------------------------------
def find_best_exchange(name: str, price_yahoo: float, exclude_exchange: str = None):
    """
    Проходит по списку бирж EXCHANGES_TO_CHECK (кроме исключённой), для каждой
    загружает рынки и ищет подходящий инструмент по ключевым словам, затем
    выбирает биржу с ценой ближе всего к цене Yahoo Finance.
    Возвращает (биржа, цена, расхождение%) либо (None, None, None).
    """
    best_exchange = None
    best_price = None
    best_deviation = None

    for exchange_id in EXCHANGES_TO_CHECK:
        if exchange_id == exclude_exchange:
            continue

        exchange, markets = load_exchange_markets(exchange_id)
        if exchange is None:
            continue

        price, used_symbol = get_price_for_instrument(exchange_id, exchange, markets, name)
        if price is None:
            continue

        deviation = calculate_deviation(price_yahoo, price)
        if best_deviation is None or abs(deviation) < abs(best_deviation):
            best_exchange = exchange_id
            best_price = price
            best_deviation = deviation

    return best_exchange, best_price, best_deviation


# ---------------------------------------------------------------------------
# 7. Основная функция
# ---------------------------------------------------------------------------
def main():
    # --- Часть 1: цены с Yahoo Finance ---
    yahoo_prices = collect_yahoo_prices()

    # --- Часть 2: сравнение с Bitget ---
    print("\n=== ЧАСТЬ 2: Сравнение с Bitget ===")

    results_table = []  # список строк для итоговой таблицы / CSV

    print("[INFO] Загружаю список рынков Bitget через ccxt...")
    bitget_exchange, bitget_markets = load_exchange_markets("bitget")

    if bitget_markets is not None:
        print(f"[INFO] На Bitget найдено рынков: {len(bitget_markets)}")

    for name, price_yahoo in yahoo_prices.items():
        if price_yahoo is None:
            print(f"{name}: пропущено (нет цены Yahoo Finance)")
            continue

        if bitget_markets is None:
            print(f"{name}: Bitget недоступен, сравнение невозможно")
            results_table.append({
                "Инструмент": name,
                "Цена Yahoo": round(price_yahoo, 2),
                "Цена Bitget": None,
                "Расхождение %": None,
                "Вердикт": "БИРЖА НЕДОСТУПНА",
            })
            continue

        price_bitget, used_symbol = get_price_for_instrument("bitget", bitget_exchange, bitget_markets, name)

        if price_bitget is None:
            print(f"{name}: подходящий рынок на Bitget (через ccxt) не найден по ключевым словам {SEARCH_KEYWORDS.get(name)}")
            results_table.append({
                "Инструмент": name,
                "Цена Yahoo": round(price_yahoo, 2),
                "Цена Bitget": None,
                "Расхождение %": None,
                "Вердикт": "НЕТ ДАННЫХ",
            })
            continue

        deviation = calculate_deviation(price_yahoo, price_bitget)
        verdict = get_verdict(deviation)

        print(f"{name}: Yahoo={price_yahoo:.2f} | Bitget ({used_symbol})={price_bitget:.2f} "
              f"| Расхождение={deviation:+.3f}% | Вердикт={verdict}")

        results_table.append({
            "Инструмент": name,
            "Цена Yahoo": round(price_yahoo, 2),
            "Цена Bitget": round(price_bitget, 2),
            "Расхождение %": round(deviation, 3),
            "Вердикт": verdict,
        })

        # --- Дополнительно: если расхождение больше 1% - ищем лучшую биржу ---
        if abs(deviation) > THRESHOLD_DEEP_CHECK:
            print(f"[INFO] Расхождение по {name} превышает {THRESHOLD_DEEP_CHECK}% — ищу лучшую биржу среди {EXCHANGES_TO_CHECK}...")
            best_exchange, best_price, best_deviation = find_best_exchange(
                name, price_yahoo, exclude_exchange="bitget"
            )
            if best_exchange is not None:
                print(f"Лучшая биржа для {name}: {best_exchange} (расхождение {best_deviation:+.2f}%)")
            else:
                print(f"[ПРЕДУПРЕЖДЕНИЕ] Не удалось найти альтернативную биржу с данными по {name}")

    # --- Вывод итоговой таблицы в консоль ---
    print("\n=== ИТОГОВАЯ ТАБЛИЦА ===")
    df = pd.DataFrame(results_table)
    if not df.empty:
        print(df.to_string(index=False))
    else:
        print("Нет данных для отображения.")

    # --- Часть 3: проверка TradingView ---
    print("\n=== ЧАСТЬ 3: Проверка тикеров на TradingView ===")
    for name in yahoo_prices.keys():
        check_tradingview(name)

    # --- Сохранение результатов в CSV ---
    today_str = datetime.now().strftime("%Y-%m-%d")
    output_filename = f"price_comparison_{today_str}.csv"
    try:
        df.to_csv(output_filename, index=False, encoding="utf-8-sig")
        print(f"\n[INFO] Результаты сохранены в файл: {output_filename}")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось сохранить CSV-файл: {e}")


if __name__ == "__main__":
    main()
