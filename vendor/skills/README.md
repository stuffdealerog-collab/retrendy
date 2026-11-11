# Сторонние скиллы для видеомонтажа

Пять внешних репозиториев, подключённых как git-сабмодули (в этом репозитории
хранятся только ссылки на конкретные коммиты, а не сам код).

| Папка | Источник | Коммит | Лицензия |
|---|---|---|---|
| `ghost-editor` | https://github.com/kurbaitaev/ghost-editor | `ce17272` | MIT |
| `claude-shorts` | https://github.com/AgriciDaniel/claude-shorts | `a369fad` | MIT |
| `openmontage` | https://github.com/OpenMontageInc/openmontage | `fecb9a1` | AGPL-3.0 |
| `ffmpeg-skill` | https://github.com/kajisho5/ffmpeg-skill | `532cbe3` | MIT |
| `hyperframes` | https://github.com/heygen-com/hyperframes | `84799bd` | Apache-2.0 |

## Как получить файлы

```bash
git clone --recurse-submodules <url этого репозитория>
# или в уже склонированном:
git submodule update --init --depth 1
```

`hyperframes` хранит часть файлов в Git LFS — для них нужен установленный
`git lfs` (`git lfs install`, затем `git -C vendor/skills/hyperframes lfs pull`).

## Установка

У каждого проекта свой способ установки и свои зависимости (FFmpeg, Node,
Python и т. д.) — следуйте README внутри соответствующей папки. Перед запуском
чужих установочных скриптов просмотрите их.
