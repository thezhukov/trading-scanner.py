"""
market_scan.py

Скрипт для скачивания данных по золоту (GC=F), Dow Jones (^DJI) и NASDAQ (^IXIC)
за последние 3 месяца, расчёта индикаторов RSI(14), SMA(20), SMA(50)
и построения сводного графика с подсветкой зон перекупленности/перепроданности по RSI.

Запуск: python market_scan.py
Требования: Python 3.9+, доступ в интернет для загрузки котировок.
"""

import sys
import subprocess
import importlib


# ---------------------------------------------------------------------------
# 1. Автопроверка и автоустановка недостающих библиотек
# ---------------------------------------------------------------------------
# Список необходимых пакетов: ключ - имя для импорта, значение - имя для pip install
REQUIRED_PACKAGES = {
    "yfinance": "yfinance",
    "pandas": "pandas",
    "matplotlib": "matplotlib",
    "pandas_ta": "pandas-ta",
    "numpy": "numpy",
}


def ensure_packages_installed(packages: dict) -> None:
    """
    Проверяет наличие каждого пакета из словаря packages.
    Если пакет не найден - устанавливает его через pip прямо из скрипта.
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


# Запускаем проверку/установку до основных импортов
ensure_packages_installed(REQUIRED_PACKAGES)

# Теперь можно спокойно импортировать всё необходимое
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

try:
    import yfinance as yf
except ImportError:
    print("[КРИТИЧЕСКАЯ ОШИБКА] Не удалось импортировать yfinance даже после установки.")
    sys.exit(1)

try:
    import pandas_ta as ta
except ImportError:
    print("[КРИТИЧЕСКАЯ ОШИБКА] Не удалось импортировать pandas_ta даже после установки.")
    sys.exit(1)

from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# 2. Настройки: тикеры и период
# ---------------------------------------------------------------------------
TICKERS = {
    "Золото (GLD)": "GLD",
    "Dow Jones (^DJI)": "^DJI",
    "NASDAQ (^IXIC)": "^IXIC",
}

PERIOD = "3mo"      # последние 3 месяца
INTERVAL = "1d"      # дневные свечи

RSI_LENGTH = 14
SMA_SHORT = 20
SMA_LONG = 50


# ---------------------------------------------------------------------------
# 3. Функция загрузки данных с обработкой ошибок
# ---------------------------------------------------------------------------
def download_data(ticker: str, period: str = PERIOD, interval: str = INTERVAL) -> pd.DataFrame:
    """
    Скачивает исторические данные по тикеру с Yahoo Finance.
    Обрабатывает ситуации отсутствия интернета или отсутствия данных.
    Возвращает DataFrame либо пустой DataFrame в случае ошибки.
    """
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False)
    except Exception as e:
        # Сюда попадают, например, ошибки сети (нет интернета) или ошибки API
        print(f"[ОШИБКА] Не удалось скачать данные для {ticker}: {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        print(f"[ПРЕДУПРЕЖДЕНИЕ] Для тикера {ticker} нет данных (пустой ответ от Yahoo Finance).")
        return pd.DataFrame()

    # Если yfinance вернул мультииндекс колонок (бывает при некоторых версиях) - упрощаем
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.dropna(inplace=True)
    return df


# ---------------------------------------------------------------------------
# 4. Функция расчёта индикаторов
# ---------------------------------------------------------------------------
def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Добавляет в DataFrame колонки:
    - RSI_14
    - SMA_20
    - SMA_50
    """
    if df.empty:
        return df

    try:
        df["RSI_14"] = ta.rsi(df["Close"], length=RSI_LENGTH)
        df["SMA_20"] = ta.sma(df["Close"], length=SMA_SHORT)
        df["SMA_50"] = ta.sma(df["Close"], length=SMA_LONG)
    except Exception as e:
        print(f"[ОШИБКА] Не удалось рассчитать индикаторы: {e}")

    return df


# ---------------------------------------------------------------------------
# 5. Функция подсветки зон RSI на конкретном subplot'е
# ---------------------------------------------------------------------------
def highlight_rsi_zones(ax, df: pd.DataFrame) -> None:
    """
    Закрашивает фон графика на участках, где RSI > 70 (красный, перекупленность)
    или RSI < 30 (зелёный, перепроданность).
    """
    if "RSI_14" not in df.columns:
        return

    dates = df.index

    # Маски для зон перекупленности и перепроданности
    overbought_mask = df["RSI_14"] > 70
    oversold_mask = df["RSI_14"] < 30

    # axvspan рисуем по индексам, где выполняется условие,
    # используя fill_between с where= для непрерывных зон закраски по всей высоте графика
    ax.fill_between(
        dates, ax.get_ylim()[0], ax.get_ylim()[1],
        where=overbought_mask, color="red", alpha=0.15,
        transform=ax.get_xaxis_transform(), step="mid",
        label="RSI > 70 (перекупленность)"
    )
    ax.fill_between(
        dates, ax.get_ylim()[0], ax.get_ylim()[1],
        where=oversold_mask, color="green", alpha=0.15,
        transform=ax.get_xaxis_transform(), step="mid",
        label="RSI < 30 (перепроданность)"
    )


# ---------------------------------------------------------------------------
# 6. Основная функция
# ---------------------------------------------------------------------------
def main():
    data_by_name = {}

    # --- Загрузка и расчёт индикаторов для каждого инструмента ---
    for name, ticker in TICKERS.items():
        print(f"[INFO] Загружаю данные: {name} ({ticker})...")
        df = download_data(ticker)

        if df.empty:
            print(f"[ПРОПУСК] {name}: данные отсутствуют, инструмент будет пропущен на графике.")
            data_by_name[name] = df
            continue

        df = calculate_indicators(df)
        data_by_name[name] = df

    # Проверяем, есть ли хоть один инструмент с валидными данными
    valid_instruments = {k: v for k, v in data_by_name.items() if not v.empty}
    if not valid_instruments:
        print("[КРИТИЧЕСКАЯ ОШИБКА] Не удалось получить данные ни по одному инструменту. Завершение работы.")
        sys.exit(1)

    # --- Построение графика: 3 строки (subplots) ---
    fig, axes = plt.subplots(nrows=3, ncols=1, figsize=(14, 12), sharex=False)
    fig.suptitle("Market Scan: Золото / Dow Jones / NASDAQ (3 месяца)", fontsize=16, fontweight="bold")

    for ax, (name, df) in zip(axes, data_by_name.items()):
        if df.empty:
            ax.set_title(f"{name} — нет данных")
            ax.text(0.5, 0.5, "Нет данных", ha="center", va="center", transform=ax.transAxes)
            continue

        # Основная линия цены закрытия
        ax.plot(df.index, df["Close"], label="Цена закрытия", color="black", linewidth=1.3)

        # Скользящие средние
        if "SMA_20" in df.columns:
            ax.plot(df.index, df["SMA_20"], label=f"SMA {SMA_SHORT}", color="blue", linewidth=1)
        if "SMA_50" in df.columns:
            ax.plot(df.index, df["SMA_50"], label=f"SMA {SMA_LONG}", color="orange", linewidth=1)

        # Подсветка зон RSI фоном
        highlight_rsi_zones(ax, df)

        ax.set_title(name, fontsize=12, fontweight="bold")
        ax.set_ylabel("Цена")
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(True, alpha=0.3)

        # Форматирование дат по оси X
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m.%Y"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    # --- Сохранение результата в PNG с текущей датой в имени файла ---
    today_str = datetime.now().strftime("%Y-%m-%d")
    output_filename = f"market_scan_{today_str}.png"

    try:
        plt.savefig(output_filename, dpi=150)
        print(f"[INFO] График успешно сохранён в файл: {output_filename}")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось сохранить график: {e}")

    plt.show()

    # --- Вывод текущих значений RSI в консоль ---
    print("\n=== Текущие значения RSI (14) ===")
    for name, df in data_by_name.items():
        if df.empty or "RSI_14" not in df.columns or df["RSI_14"].dropna().empty:
            print(f"{name}: нет данных для расчёта RSI")
            continue

        last_rsi = df["RSI_14"].dropna().iloc[-1]
        last_date = df["RSI_14"].dropna().index[-1].strftime("%d.%m.%Y")
        print(f"{name}: RSI = {last_rsi:.2f} (на {last_date})")


if __name__ == "__main__":
    main()
