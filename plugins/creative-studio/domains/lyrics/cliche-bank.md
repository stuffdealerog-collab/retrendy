# Cliché bank: lyrics

Machine-read by `scripts/novelty_check.py`. Format of an entry:

`- **LY-NNN** {optional tags} text / variant / variant`

- One entry = one recognisable cliché. Variants separated by ` / ` are embedded
  separately (max similarity wins), so put the RU and EN phrasing of the same
  cliché in one entry rather than two.
- `{rhyme}` entries are checked lexically against line endings of the sample
  lyrics (a warning, not a filter).
- `{structure}` entries describe form (how the chorus repeats, a whispered
  bridge, a dialogue). Every concept description talks about its own form, so
  embeddings match these by vocabulary rather than by idea (measured: 0.65-0.75
  against fresh concepts). They are judged by cliche-hunter, which reads this
  file, and are skipped by the embedding filter.
- Every other entry is checked semantically against the concept (hard filter
  at the configured threshold, collage rule) and against individual sample
  lines (warning).
- IDs are stable: never renumber, append new ones at the end of a section with
  the next free number. Local additions go to `<home>/cliche-bank/lyrics.md`
  (same format, prefix `LYL-`), not here, so plugin updates don't erase them.
- A cliché is not banned forever. It is banned **as the core of a concept**. A
  director may deliberately subvert one, but then the concept text has to
  name the subversion so the filter sees a different idea.

## Imagery

- **LY-001** Танец под дождём как жест свободы / dancing in the rain as a symbol of freedom
- **LY-002** Огни ночного города, неон и отражения в лужах / city lights and neon reflections on wet streets
- **LY-003** Разбитое сердце, осколки как стекло / broken heart shattered like glass
- **LY-004** Слёзы как дождь, дождь вместо слёз / tears falling like rain
- **LY-005** Звёзды и луна как свидетели любви / under the moon and stars, only the stars know
- **LY-006** Сгорать в огне страсти, пламя любви / burning with fire and desire
- **LY-007** Тонуть в твоих глазах, океан чувств / drowning in your eyes, an ocean of love
- **LY-008** Ты подарила мне крылья, летать рядом с тобой / you gave me wings to fly
- **LY-009** Восстать из пепла как феникс / rising from the ashes like a phoenix
- **LY-010** Шрамы как память о боли / my scars tell my story
- **LY-011** Пустая половина кровати, холодная постель / the empty side of the bed
- **LY-012** Телефон молчит, жду звонка, который не придёт / waiting for a call that never comes
- **LY-013** Сигаретный дым, бокал вина и одиночество в три часа ночи / smoke and wine alone at 3 a.m.
- **LY-014** Все мы носим маски, сорвать маску / we all wear masks
- **LY-015** Стены вокруг сердца, разрушить стены / walls around my heart coming down
- **LY-016** Демоны внутри меня, борьба с демонами / fighting my inner demons
- **LY-017** Ты мой ангел, ангел-хранитель / you are my angel
- **LY-018** Шторм в душе, буря внутри / a storm inside my soul
- **LY-019** Солнце после дождя, радуга после бури / sunshine after the rain
- **LY-020** Розы и шипы, у каждой розы есть шипы / every rose has its thorn
- **LY-021** Бабочки в животе от влюблённости / butterflies in my stomach
- **LY-022** Время утекает как песок сквозь пальцы / time slipping through my fingers like sand
- **LY-023** Смотрю в зеркало и не узнаю себя / I don't recognise the person in the mirror
- **LY-024** Бесконечное лето, которое никогда не кончится / endless summer that never ends
- **LY-025** Только ты и я против всего мира / you and me against the world
- **LY-026** Потерян в лабиринте, ищу выход / lost in a maze, looking for a way out
- **LY-027** Сердце из камня, ледяное сердце / heart of stone, frozen heart
- **LY-028** Две половинки одного целого / two halves of one whole, you complete me

## Rhyme pairs

- **LY-029** {rhyme} любовь / кровь / вновь / бровь
- **LY-030** {rhyme} розы / морозы / слёзы / грёзы
- **LY-031** {rhyme} ночь / прочь / помочь / дочь
- **LY-032** {rhyme} глаза / гроза / слеза / небеса
- **LY-033** {rhyme} навсегда / никогда / города / провода / вода
- **LY-034** {rhyme} мечты / ты / цветы / пустоты / красоты
- **LY-035** {rhyme} огонь / ладонь
- **LY-036** {rhyme} сердце / дверца / согреться
- **LY-037** {rhyme} fire / desire / higher / wire
- **LY-038** {rhyme} heart / apart / start / part
- **LY-039** {rhyme} love / above / enough / of
- **LY-040** {rhyme} night / light / tonight / right / fight
- **LY-041** {rhyme} pain / rain / again / insane
- **LY-042** {rhyme} soul / whole / control / hole
- **LY-043** {rhyme} dreams / seams / seems / screams

## Stock phrases

- **LY-044** Я не могу без тебя жить / I can't live without you
- **LY-045** Ты мой воздух, ты нужна мне как воздух / you are the air I breathe
- **LY-046** Я бы отдал за тебя всё / I would give it all for you
- **LY-047** Вместе навсегда, ничто нас не разлучит / together forever, nothing can tear us apart
- **LY-048** Вечно молодые / forever young
- **LY-049** Живи так, будто завтра не наступит / live like there's no tomorrow
- **LY-050** Никто меня не понимает / nobody understands me
- **LY-051** Снова и снова, по кругу / over and over again
- **LY-052** Теперь я сильнее, чем прежде / I'm stronger now than I was before
- **LY-053** Отпусти и забудь / let it go and move on
- **LY-054** Время лечит все раны / time heals all wounds
- **LY-055** Просто останься со мной этой ночью / just stay with me tonight
- **LY-056** Моё сердце бьётся только для тебя / my heart beats only for you
- **LY-057** Нам суждено быть вместе, это судьба / we were meant to be, it's destiny
- **LY-058** Без тебя всё не так / everything is wrong without you
- **LY-059** Пусть весь мир подождёт / let the whole world wait
- **LY-060** Пути назад нет / there's no turning back
- **LY-061** Мы были так молоды / we were so young back then
- **LY-062** Вокализы-заполнители как хук: «о-о-о», «на-на-на», baby baby / oh-oh-oh, na-na-na as the hook
- **LY-063** Это наша ночь, давай забудем обо всём / tonight is our night, let's forget everything

## Story arcs

- **LY-064** Расставание, боль, «я стал сильнее» как арка самоисцеления / breakup, pain, then I'm stronger without you
- **LY-065** Сжечь фотографии и письма бывшего, чтобы забыть / burning the ex's photos and letters to forget
- **LY-066** Пьяный звонок бывшему в три часа ночи / drunk dialling the ex at 3 a.m.
- **LY-067** Неотправленное письмо или сообщение бывшему / the letter or text I never sent
- **LY-068** Случайная встреча бывших спустя годы / running into the ex years later
- **LY-069** Был никем, стал звездой, хейтеры замолчали / from nothing to the top, the haters went quiet
- **LY-070** Ностальгия по детству: двор, лето у бабушки / nostalgia for childhood summers in the yard
- **LY-071** Любовь вопреки родителям и обществу, как Ромео и Джульетта / forbidden love against family and society
- **LY-072** Вечеринка как бегство: забыться на танцполе до утра / dancing all night to forget my problems
- **LY-073** Маленький город и мечта уехать в большой / small town dreams of escaping to the big city
- **LY-074** Последний танец перед расставанием / one last dance before goodbye
- **LY-075** Измена, раскрытая по уликам: помада, чужой парфюм / cheating discovered by lipstick on the collar
- **LY-076** Письмо себе младшему / a letter to my younger self
- **LY-077** Обращение к умершему близкому на небесах / singing to a loved one watching from heaven
- **LY-078** Дорога как метафора жизни, ехать без цели / life is a highway, driving with no destination
- **LY-079** Бунт против системы без конкретного адресата / rebelling against the system in general

## Structural moves

- **LY-080** {structure} Название песни как хук, повторённый четыре и больше раз в припеве / the title repeated four times as the chorus
- **LY-081** {structure} Модуляция на тон вверх в последнем припеве / key change up for the final chorus
- **LY-082** {structure} Бридж с внезапной тишиной и шёпотом перед финальным припевом / quiet whispered bridge before the last chorus
- **LY-083** {structure} Перечисление «я помню, как…», по строке на воспоминание / list of "I remember when" lines
- **LY-084** Финальный твист: всё это было сном / twist ending: it was all a dream
- **LY-085** {structure} Перекличка «он сказал / она сказала» без характеров / he said, she said call and response
- **LY-086** {structure} Дни недели или обратный отсчёт как каркас песни / Monday to Sunday or a countdown as the structure
- **LY-087** {structure} Абстрактные слова-эмоции вместо деталей: боль, пустота, душа, вечность / abstract emotion words instead of concrete detail
- **LY-088** {structure} Голосовое сообщение или звонок как интро / voicemail or phone call sample as the intro
- **LY-089** Песня о том, как трудно написать песню / a song about writer's block

## Stances

- **LY-090** Гимн самопринятия «я такая, какая есть» без конкретики / generic self-love anthem: this is me
- **LY-091** Успех как месть хейтерам / success is the best revenge on the haters
- **LY-092** Меланхолия без причины: всё серое, ничего не хочется / vague sadness, everything is grey
- **LY-093** Ода родному городу через перечисление названий улиц / ode to my hometown by listing street names
- **LY-094** Летний хит про море, коктейли и загар / summer hit about the beach, cocktails and tans
- **LY-095** Деньги, тачки и цацки как доказательство успеха / money, cars and chains as proof of success
