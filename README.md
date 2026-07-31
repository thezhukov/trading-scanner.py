# Trading-Scanner.py

Инструменты для анализа рынка и проверки цен перед входом в сделку.

## 📊 market_scanner.py
- Скачивает данные по золоту (XAU/USD), Dow Jones, NASDAQ через Yahoo Finance
- Считает RSI (14), SMA 20, SMA 50
- Строит график с зонами перекупленности/перепроданности
- Сохраняет результат в PNG

## 💰 price_checker.py
- Сравнивает цены Yahoo Finance и Bitget
- Считает расхождение в процентах
- Ищет биржу с ценой, максимально близкой к Yahoo Finance
- Проверяет доступность тикера на TradingView
- Сохраняет результат в CSV

## 🚀 Как запустить
1. Установи библиотеки:
```

pip install yfinance pandas matplotlib
mplfinance pandas-ta numpy ccxt

```
2. Запусти нужный скрипт:
```

python market_scanner.py
python price_checker.py

```

## 👤 Автор
13 yo, trader,thezhkv.  
```
