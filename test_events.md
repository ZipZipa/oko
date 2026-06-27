-- все события пользователя
SELECT id, event_type, report_type, plan, payment_id, created_at
FROM user_events WHERE telegram_id = TG ORDER BY created_at DESC;

-- отправленные пуши
SELECT event_key, sent_at FROM notification_log WHERE telegram_id = TG ORDER BY sent_at DESC;

-- профиль
SELECT telegram_id, name IS NOT NULL, face_json IS NOT NULL, birth_date IS NOT NULL,
        blocks_json IS NOT NULL, money_blocks_json IS NOT NULL, couple_blocks_json IS NOT NULL,
        last_activity_at, is_blocked FROM users WHERE telegram_id = TG;

Перед перетестированием того же пуша — удали его запись из лога:
DELETE FROM notification_log WHERE telegram_id = TG AND event_key = 'e1:1';

Sweep ходит каждые 60 с. После сдвига времени жди до минуты. В логе бота успешных отправок нет (только ошибки), поэтому факт прихода проверяй в Telegram.

Общий шаблон сдвига времени

-- сдвинуть событие на N минут/часов/дней назад
UPDATE user_events
SET created_at = datetime('now','-20 minutes')
WHERE telegram_id = TG AND event_type = 'entered_menu'
ORDER BY created_at DESC LIMIT 1;   -- только последнюю (SQLite 3.35+)
datetime('now',…) всегда в UTC — совпадает с тем, как хранит бот.

---
E1. Зашёл → ничего не начал

Триггер: профиль полный, но демо не запускалось. Открой бота /start (должен показать главное меню).

UPDATE user_events SET created_at = datetime('now','-20 minutes')
WHERE telegram_id = TG AND event_type = 'entered_menu'
ORDER BY created_at DESC LIMIT 1;
→ жди ~60 с → пуш 1: «Твой персональный анализ ещё не начат.»

UPDATE user_events SET created_at = datetime('now','-25 hours')
WHERE telegram_id = TG AND event_type = 'entered_menu'
ORDER BY created_at DESC LIMIT 1;
DELETE FROM notification_log WHERE telegram_id = TG AND event_key IN ('e1:1','e1:2');
→ жди → пуш 2: «Ответы о тебе всё ещё ждут тебя в ОКО.»

Проверка отмены: запусти любой демо-анализ (например, «Портрет личности» → «Запустить анализ»), затем сдвинь entered_menu назад — пуш E1 не придёт (т.к. после entered_menu есть demo_shown).

---
E2. Начал регистрацию → бросил

Триггер: новый пользователь жмёт /start (логируется registration_started), но не заполняет имя/фото/дату.

UPDATE user_events SET created_at = datetime('now','-40 minutes')
WHERE telegram_id = TG AND event_type = 'registration_started'
ORDER BY created_at DESC LIMIT 1;
→ пуш 1: «Ты почти начал анализ. Остался последний шаг.»

UPDATE user_events SET created_at = datetime('now','-13 hours')
WHERE telegram_id = TG AND event_type = 'registration_started'
ORDER BY created_at DESC LIMIT 1;
DELETE FROM notification_log WHERE telegram_id = TG AND event_key IN ('e2:1','e2:2');
→ пуш 2: «Дополни данные и получи свой персональный разбор.»

Проверка отмены: доомпли профиль до конца (имя → фото → дата рождения). Появится profile_completed — после этого E2 не сработает, сколько ни сдвигай registration_started.

---
E3. Начал совместимость → не ввёл партнёра

Триггер: главное меню → «Совместимость пары» → «Запустить анализ» (ввод данных партнёра). Не продолжай.

UPDATE user_events SET created_at = datetime('now','-40 minutes')
WHERE telegram_id = TG AND event_type = 'couple_partner_started'
ORDER BY created_at DESC LIMIT 1;
→ пуш 1: «Для анализа пары не хватает данных второго человека.»

UPDATE user_events SET created_at = datetime('now','-25 hours')
WHERE telegram_id = TG AND event_type = 'couple_partner_started'
ORDER BY created_id DESC LIMIT 1;
DELETE FROM notification_log WHERE telegram_id = TG AND event_key IN ('e3:1','e3:2');
→ пуш 2: «Добавь данные партнёра и узнай, что происходит между вами на самом деле.»

Проверка отмены: введи данные партнёра до фото (имя → дата → фото). После фото логируется couple_partner_completed — E3 больше не сработает.

---
E4. Получил демо → не купил

Триггер: запусти демо-анализ (любой из трёх). После готовности логируется demo_shown с report_type.

UPDATE user_events SET created_at = datetime('now','-25 minutes')
WHERE telegram_id = TG AND event_type = 'demo_shown'
ORDER BY created_at DESC LIMIT 1;
→ пуш 1: «Ты увидел только часть своего анализа.»

UPDATE user_events SET created_at = datetime('now','-13 hours')
WHERE telegram_id = TG AND event_type = 'demo_shown'
ORDER BY created_at DESC LIMIT 1;
DELETE FROM notification_log WHERE telegram_id = TG AND event_key LIKE 'e4:%';
→ пуш 2: «Самые важные выводы остались закрыты.»

UPDATE user_events SET created_at = datetime('now','-49 hours')
WHERE telegram_id = TG AND event_type = 'demo_shown'
ORDER BY created_at DESC LIMIT 1;
DELETE FROM notification_log WHERE telegram_id = TG AND event_key LIKE 'e4:%';
→ пуш 3: «Полный разбор всё ещё доступен.»

Проверка отмены: нажми «Купить» на пакете этого же отчёта (создаст payment_initiated с тем же report_type). После этого E4 для этого отчёта не сработает.

event_key зависит от типа отчёта: e4:self:1, e4:money:2, e4:couple:3. Поэтому чистим через LIKE 'e4:%'.

---
E5. Нажал оплатить → не оплатил

Триггер: выбери пакет и нажми «Купить» → появится кнопка «Перейти к оплате». Не оплачивай и не жми «Я оплатил».

-- сдвинь время создания платежа
UPDATE payments SET created_at = datetime('now','-20 minutes')
WHERE telegram_id = TG AND status = 'pending';
→ пуш 1: «Оплата не завершена. Твой анализ уже готов.» (кнопки: «Перейти к оплате» + «Открыть ОКО»)

UPDATE payments SET created_at = datetime('now','-4 hours')
WHERE telegram_id = TG AND status = 'pending';
DELETE FROM notification_log WHERE telegram_id = TG AND event_key LIKE 'e5:%';
→ пуш 2: «Остался один шаг до полного доступа.»

UPDATE payments SET created_at = datetime('now','-25 hours')
WHERE telegram_id = TG AND status = 'pending';
DELETE FROM notification_log WHERE telegram_id = TG AND event_key LIKE 'e5:%';
→ пуш 3: «Заверши оплату и открой свой разбор.»

Проверка отмены: в payments поменяй status на succeeded (и проставь paid_at) — E5 перестанет срабатывать (sweep берёт только pending):
UPDATE payments SET status='succeeded', paid_at=datetime('now')
WHERE telegram_id = TG AND yookassa_id = '...';

Если есть несколько pending-платежей, пуш придёт только по самому свежему.

---
E6. Купил один продукт → не купил остальные

Триггер: реально оплати один отчёт (или сымитируй): после успешной оплаты логируется purchase_completed с report_type и plan.

UPDATE user_events SET created_at = datetime('now','-25 hours')
WHERE telegram_id = TG AND event_type = 'purchase_completed'
ORDER BY created_at DESC LIMIT 1;
→ пуш (один, через 24 ч): текст зависит от купленного:
- self: «Теперь узнай, как твои особенности влияют на деньги и отношения.»
- money: «Теперь узнай, какие отношения усиливают или ослабляют твой путь.»
- couple: «Теперь узнай, почему именно такие люди появляются в твоей жизни.»

Проверка отмены: добавь второй purchase_completed с другим report_type — E6 не сработает:
INSERT INTO user_events (telegram_id, event_type, report_type, plan, payment_id, created_at)
VALUES (TG, 'purchase_completed', 'money', 'base', 'fake2', datetime('now','-20 hours'));
DELETE FROM notification_log WHERE telegram_id = TG AND event_key LIKE 'e6:%';

---
E7. Купил базовый/расширенный → не купил премиум

Триггер: purchase_completed с plan = base или extended.

UPDATE user_events SET created_at = datetime('now','-3 hours')
WHERE telegram_id = TG AND event_type = 'purchase_completed' AND plan IN ('base','extended')
ORDER BY created_at DESC LIMIT 1;
→ пуш 1: «Ты открыл только часть своего анализа.»

UPDATE user_events SET created_at = datetime('now','-25 hours')
WHERE telegram_id = TG AND event_type = 'purchase_completed' AND plan IN ('base','extended')
ORDER BY created_at DESC LIMIT 1;
DELETE FROM notification_log WHERE telegram_id = TG AND event_key LIKE 'e7:%';
→ пуш 2: «Самые глубокие выводы доступны в Премиум.»

Проверка отмены: добавь purchase_completed с plan='full' для того же report_type — E7 для этого отчёта отключится.

---
E8. Давно не заходил

Триггер: у пользователя есть хоть один отчёт (blocks_json/money_blocks_json/couple_blocks_json не пусто) и last_activity_at.

UPDATE users SET last_activity_at = datetime('now','-8 days'), is_blocked = 0
WHERE telegram_id = TG;
DELETE FROM notification_log WHERE telegram_id = TG AND event_key IN ('e8:1','e8:2');
Важно: после этого НЕ пиши в бота и не жми кнопки — любое взаимодействие обновит last_activity_at и очистит e8-лог (по дизайну).

→ подожди ~60 с → пуш 1: «Твои разборы всё ещё ждут тебя.»

UPDATE users SET last_activity_at = datetime('now','-31 days')
WHERE telegram_id = TG;
DELETE FROM notification_log WHERE telegram_id = TG AND event_key IN ('e8:1','e8:2');
→ пуш 2: «Возможно, сейчас именно то время, чтобы посмотреть на свою жизнь иначе.»

Проверка отмены/перезапуска: напиши боту /start — last_activity_at обновится, e8-логи очистятся. Сдвинь снова на 8 дней — пуш придёт заново (цикл перезапустился).

---
Краевые случаи

Идемпотентность: после прихода пуша сдвинь время ещё сильнее и подожди — второго раза быть не должно (запись в notification_log блокирует).

Сброс данных: меню → «Начать заново» → «Да, сбросить». Проверь:
SELECT count(*) FROM user_events WHERE telegram_id = TG;        -- должно стать 1 (registration_started)
SELECT count(*) FROM notification_log WHERE telegram_id = TG;   -- 0
После сброса E2 снова в работе (новая регистрация).

Заблокировал бот: в Telegram останови/заблокируй бота, затем сымитируй пуш (сдвинь время). В логе бота появится ошибка Forbidden, а в БД:
SELECT is_blocked FROM users WHERE telegram_id = TG;  -- станет 1
После этого пользователь исключается из всех sweep-запросов. Разблокируй бота и напиши /start — is_blocked вернётся в 0 (через ActivityMiddleware).

Тихая оплата (поллинг): создай pending-платёж, сдвинь created_at на 6+ минут назад, поменяй статус в YooKassa (или временно мокни check_payment). Через ≤5 мин sweep опросит его, проставит
succeeded+paid_at и залогирует purchase_completed — E5 отменится, E6/E7 активируются. Проверить:
SELECT status, paid_at FROM payments WHERE telegram_id = TG ORDER BY id DESC LIMIT 1;
SELECT count(*) FROM user_events WHERE telegram_id = TG AND event_type = 'purchase_completed';