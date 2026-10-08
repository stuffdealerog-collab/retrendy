# retrendy

Локальный маркетплейс Claude Code с плагином **creative-studio**: креативным
движком, который анализирует тренды и генерирует оригинальные, а не
усреднённые идеи. Оригинальность обеспечивает механика:

- verbalized sampling с отбором из хвоста;
- параллельные ветки с разными стратегиями мышления;
- фильтр новизны по эмбеддингам против банка клише и прошлых генераций;
- отдельный критик с доказательными оценками и слепым турниром.

```bash
claude plugin marketplace add /path/to/retrendy
claude plugin install creative-studio@retrendy
# в сессии:
/creative-studio:create Домен: тексты песен. Цель: … Аудитория: … Ограничения: … Табу: …
```

Документация: [plugins/creative-studio/README.md](plugins/creative-studio/README.md).
