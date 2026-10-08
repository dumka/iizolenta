# Перехват сайтов: LeechBlock NG в Zen и Vivaldi

Цель: вместо lenta.ru (и других сайтов из списка) браузер открывает ИИзоЛенту — https://dumka.github.io/iizolenta/ — с баннером «Сайт lenta.ru заизолирован».

Список сайтов один на все устройства: https://dumka.github.io/iizolenta/sites.txt (в репозитории — `site/sites.txt`). Расширение само загружает его по ссылке, поэтому сайты в настройках на устройствах не вписываются.

## Значения настроек (одинаковые для обоих браузеров)

| Поле в LeechBlock NG | Значение |
|---|---|
| Enter the domain names of the sites to block | оставить **пустым** |
| Load list of sites from URL (раздел **Advanced Options** — сначала нажмите кнопку **Show Advanced Options**) | `https://dumka.github.io/iizolenta/sites.txt` |
| Enter the time periods within which to block these sites | нажать кнопку **All Day** (получится `0000-2400`) |
| Дни недели под временем | отметить **все семь** |
| Enter the fully specified URL of the page to show instead of these blocked sites | `https://dumka.github.io/iizolenta/#$U` |
| вкладка General → раздел Miscellaneous → Block all subdomains (not just www) | **включить** (иначе `m.lenta.ru` и другие поддомены не перехватываются) |

`$U` — LeechBlock подставит адрес, который вы пытались открыть; по нему ИИзоЛента пишет, какой сайт заизолирован.

## Zen (Windows)

1. Откройте в Zen https://addons.mozilla.org/firefox/addon/leechblock-ng/ и нажмите «Добавить в Firefox», затем подтвердите установку.
2. Откройте настройки расширения: кнопка расширений на панели → LeechBlock NG → «Options». Или `about:addons` → LeechBlock NG → «Настройки».
3. На вкладке **Block Set 1** заполните поля из таблицы выше. Поле «Load list of sites from URL» появится после нажатия **Show Advanced Options** внизу вкладки.
4. На вкладке **General** включите «Block all subdomains (not just www)».
5. Нажмите **Save Options** внизу страницы.
6. Проверка: в новой вкладке наберите `lenta.ru`. Должна открыться ИИзоЛента с красным баннером. Проверьте также `https://m.lenta.ru` и любую ссылку на статью Ленты.

## Vivaldi (Android)

Расширения в Vivaldi для Android появились в версии 8.2 (сентябрь 2026). Проверьте версию: меню → Настройки → «О Vivaldi»; при необходимости обновите из Google Play.

1. Откройте в Vivaldi https://chromewebstore.google.com/detail/leechblock-ng/blaaajhemilngeeffpbfkdjjoefldkok
   - Если магазин пишет, что браузер не поддерживается, включите в меню Vivaldi «Версия для ПК» и обновите страницу.
2. Нажмите «Установить» («Add to Vivaldi») и подтвердите.
3. Откройте настройки расширения: значок расширений (пазл) в адресной строке → LeechBlock NG → «Options»/«Параметры».
4. Заполните поля из таблицы (для «Load list of sites from URL» нажмите **Show Advanced Options**), включите «Block all subdomains (not just www)» на вкладке General, нажмите **Save Options**.
5. Полностью закройте Vivaldi (смахните из списка недавних приложений) и откройте снова.
6. Проверка: наберите `lenta.ru` — должна открыться ИИзоЛента с баннером.

### Если в Vivaldi не сработало: AdGuard

Vivaldi на Android поддерживает не все функции расширений. Если LeechBlock установился, но lenta.ru открывается как обычно, используйте расширение AdGuard (его работу в Vivaldi Android подтвердили сами разработчики AdGuard):

1. Установите «AdGuard AdBlocker» из Chrome Web Store тем же способом.
2. В настройках AdGuard откройте «Пользовательские правила» (User rules) и добавьте строку:
   ```
   ||lenta.ru^$document,urltransform=/^https?:\/\/.*/https:\/\/dumka.github.io\/iizolenta\//
   ```
3. Сохраните и проверьте `lenta.ru`.

Правило собрано по документации AdGuard (`$urltransform` работает только в пользовательских и доверенных правилах) и ещё не проверено на устройстве — если не сработает, пришлите, что происходит, поправим. Минус варианта: каждый новый сайт добавляется отдельным правилом на телефоне, а не через общий `sites.txt`.

## Как добавить сайт в перехват

1. Добавьте домен строкой в `site/sites.txt` (например, `pikabu.ru`) и запушьте в `main` — или отредактируйте файл прямо на GitHub: https://github.com/dumka/iizolenta/edit/main/site/sites.txt
2. Через 1-2 минуты GitHub Pages опубликует файл; ещё до 10 минут его может держать кеш.
3. LeechBlock перечитывает список при запуске браузера и при сохранении настроек: перезапустите браузер или откройте настройки LeechBlock и нажмите **Save Options**.

Не добавляйте в список `github.io` и `dumka.github.io` — иначе ИИзоЛента перехватит сама себя и получится бесконечный редирект.

## Если перехват не работает

- Наберите адрес полностью: `https://lenta.ru/`. Если открывается Лента — откройте настройки LeechBlock и проверьте, что «Load list of sites from URL» заполнено без пробелов и что время `0000-2400` и все дни отмечены; нажмите **Save Options**.
- Откройте https://dumka.github.io/iizolenta/sites.txt в браузере — там должна быть строка `lenta.ru`.
- Если открывается страница LeechBlock «Site blocked» вместо ИИзоЛенты — неверно заполнено поле «Enter the fully specified URL»; вставьте значение из таблицы.

## По желанию: пароль на настройки

Чтобы в момент прокрастинации было сложнее выключить перехват: вкладка General → раздел Access Control → «Require the user to enter a random 32-character access code». Перепечатывать случайный код из 32 символов каждый раз, когда хочется отключить перехват, — обычно достаточно отрезвляет.
