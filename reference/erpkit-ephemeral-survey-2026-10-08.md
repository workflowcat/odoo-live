REPORT: ERP Kit glossary, Ephemeral docs, Keeper INTERACTION, odoo-work-summary
All read-only; nothing run except ls/grep/sed/python-json reads.

NOTE ON SOURCES
- Ephemeral: the main checkout /Users/kit/Codius/ephemeral (branch core/plm) has only 5 docs. The newer docs (words, documents, demo data, ownership, sandbox, labs, testing, api) live in git worktrees. I used /Users/kit/Codius/ephemeral/.worktrees/all (branch demo/all, 2026-10-07); /Users/kit/Codius/ephemeral/.worktrees/fix17 (2026-10-08) differs only in modules.md and ownership.md.
- Ephemeral's word list names as its norm a file that is in the Odoo repo itself: /Users/kit/Codius/odoo-live-show/docs/payroll/words.md (also /Users/kit/Codius/odoo-live/docs/payroll/words.md), plus the dictionary «Лад» (https://lad-oblik.botpartners.workers.dev/). ERP Kit entities carry provenance.project = "oblik-map", i.e. the same «Лад» source.

====================================================================
1. ERP KIT  (/Users/kit/Codius/odoo-live-show/reference/erpkit/erpkit-2026-10-07/)
====================================================================

1.1 Pack structure
- CLAUDE-HANDOFF.md (1 KB): usage terms. Pack is "explanatory reference, not executable policy or approved law"; pin release toolkit-knowledge-2026-10-07; cite entity ID/revision; do not fill missing rates/dates with guesses; drafts and AI review are not human approval.
- INDEX.md (48 KB): one line per entity: [title](entities/<id>.md) - id / revision / jurisdiction.
- manifest.json: releaseId, packId, entityCount 329, sha256 per file, aiReview {date 2026-10-07}, humanReview "not-recorded".
- knowledge.json (1.19 MB): {schemaVersion "1.0", asOf "2026-10-04", applicability "unknown-without-case-facts", versionResolution "explicit-entity-version-only", capabilities ["read"], executionAuthorized false, mode "public-reference-snapshot", entities[329]}.
- entities/*.md: 329 files, one per entity, same content as JSON rendered as "**key**\n\nvalue" blocks, with header (ID, Revision, Jurisdiction, Editorial publication, Evidence, Implementation, Human review, Effective from/to), then "Sources and provenance" and "Relationships".

Entity envelope fields (all 329): id, kind, title, jurisdiction, language, version, publication, evidence, implementation, effective{from,to,checkedAt}, citations, rights, content{...}, relationships[{targetId, relation, maturity}], history, uncertainty; provenance on 323.
- jurisdiction: UA 289 (language uk), US-FED 40 (en).
- status triple (publication/evidence/implementation): draft/unverified/not-assessed 240; draft/source-checked/proposed 73; draft/unverified/proposed 16. Nothing is human-reviewed.
- versions: 0.8.0 (240, the «Лад»/oblik-map export, updated 2026-09-17), toolkitknowledge.ua.2026-10-04 (43), fixture:us:irs:w9 (40), 0.1.0 (6).

Counts by envelope "kind": explainer 188, source 60, field 27, review 16, claim 12, document-type 11, artifact 5, reporting-form 4, form-version 3, change 2, release 1.
Counts by id prefix / content.legacyKind:
- concept-- 65 (content: name, en, aliases, group, kind, definition, example, distinction, inputs, sourceIds, related, status, updated, validFrom/To)
- term-- 20 (name, variants, kind [Скорочення / Розмовна назва / Фаховий термін / Кілька значень], note, senses[{label, explanation, example, conceptIds, sourceIds, locator, targetConceptId}])
- document-- 10 (name, family, purpose, when, form, fields, checks, conceptIds, relations, example, review)
- dataset-- 53 (name, group, kind, publisher, sourceUrl, summary, access, keys, formats, auth, refreshAdvice, pitfalls, conceptIds)
- data_domain-- 12 (name, elements[{id, name, purpose, sourceIds, mode: Зовнішні дані / Поєднання / Власний довідник / Потрібне дослідження}])
- source-- 39, src.* 11 UA, src:irs 9 US, ua:source 1
- procedure-- 7 (steps[{name, action, output, check, conceptIds}], example, exceptions)
- research-- 8, review_task-- 7, evidence_rule-- 6, scenario-- 4, calculation-- 3, rule-- 3 (UA) + rule:us 4
- payroll_model 1, military_model 1, evidence_model 1
- law996.* 4 claims, reg88.* 1 claim, ua.primary-document.authentication 1 explainer
- ua.taxform.* 24 (2 reporting-form, 2 form-version, 2 artifact, 2 explainer, 2 review, 9 + 7 fields; note F0103309 has 9 field entities, J0200126 has 7)
- ua:* manufacturing slice 6 (claim, document, field, explainer, review, source), version 0.1.0
- US-FED: form 2, formversion 1, artifact 3, field 10, rule 4, practice 2, release 1, change 2, review 6

Coverage note: concepts are payroll/HR/military/accounting-basics heavy. There is no concept entity for каса, ПДВ, податкова накладна, склад, номенклатура, специфікація, основні засоби. Stock/production appears only in the 6 ua:* entities, data_domain--goods, and research--manufacturing. No entity for Ф1/Ф2 balance forms; Д1, 4ДФ, Д5 appear only as aliases of concept--report.

1.2 GLOSSARY of UA concepts (id | Ukrainian term | English | aliases | meaning). Group names in brackets are the pack's own "group" values.

A. ACCOUNTING [group «Основи обліку», plus registers from «Документи й звітність»]
- concept--event | Господарська операція | Economic event | - | Дія або подія, що змінює майно, зобов'язання чи капітал; документ описує операцію, файл не доводить, що вона відбулася.
- concept--document | Первинний документ | Source document | (term: первинка) | Запис відомостей про господарську операцію, на якому ґрунтується облік; назва чи PDF не визначають статус.
- concept--account | Бухгалтерський рахунок | Ledger account | - | Групування записів за економічним змістом, має код, призначення, аналітику; не банківський рахунок і не рахунок на оплату.
- concept--chart | План рахунків | Chart of accounts | - | Узгоджений набір рахунків; робочий план уточнює його для організації.
- concept--entry | Бухгалтерська проводка | Journal entry | проведення; дебет; кредит | Відображення суми за Дт і Кт; проведення документа може створити кілька проводок.
- concept--balance | Залишок за рахунком | Account balance | (term: сальдо) | Початковий залишок плюс рухи; нульовий загальний залишок може приховувати борг одному і переплату іншому.
- concept--trial-balance | Оборотно-сальдова відомість | Trial balance | (term: оборотка, ОСВ) | Початкові залишки, обороти Дт/Кт, кінцеві залишки за рахунками; не тотожна звіту «Баланс».
- concept--analytics | Аналітичний вимір | Accounting dimension | - | Ознака деталізації суми: працівник, підрозділ, проєкт, вид виплати, джерело фінансування.
- concept--policy | Облікова політика | Accounting policy | - | Принципи й процедури обліку компанії; має версію й дату дії.
- concept--period | Обліковий період | Accounting period | - | Проміжок групування операцій; зарплатний, розрахунковий і звітний періоди розрізняють.
- concept--reconciliation | Звірка | Reconciliation | звіряння | Зіставлення незалежних наборів даних з поясненням кожної різниці.
- concept--receivable | Дебіторська заборгованість | Receivable | (term: дебіторка) | Заборгованість інших осіб перед підприємством на дату; виданий аванс теж її створює.
- concept--payable | Кредиторська заборгованість | Payable | (term: кредиторка) | Заборгованість підприємства перед іншими; не обов'язково банківський кредит.
- concept--liability | Зобов'язання | Liability | - | Обов'язок, погашення якого потребує ресурсів; витрата, зобов'язання і виплата не обов'язково в один день.
- concept--expense | Витрати на оплату праці | Employee expense | - | Вартість праці, віднесена на напрям діяльності або у вартість активу; не дорівнює сумі «на руки».
- concept--register | Регістр | Register | - | Упорядкована сукупність записів з призначенням, ключами, правилами зміни.
- concept--correction | Коригування | Correction | - | Виправлення помилки зі збереженням початкового запису, причини і зв'язку з новою версією; перерахунок зарплати, бух. виправлення і коригування звіту - окремі дії.

B. BANK / CASH / PAYMENTS
- concept--bank-account | Банківський рахунок | Bank account | - | Рахунок клієнта в банку; відрізняти від бухгалтерського рахунку і рахунку на оплату.
- concept--bank-statement | Банківська виписка | Bank statement | виписка банку | Відомості банку про рух коштів; повторний імпорт рядка не має створювати другу оплату.
- concept--payment-instruction | Платіжна інструкція | Payment order | (term: платіжка, платіжне доручення - історична назва) | Розпорядження надавачу платіжних послуг; створення/надсилання не дорівнює оплаті.
- concept--payment | Виплата | Payment | - | Фактичний рух коштів з підставою; «підготовлено» або «надіслано» не означає «виконано».
- concept--invoice | Рахунок на оплату | Invoice for payment | - | Документ з товарами/послугами, сумою, реквізитами для оплати; сам не доводить постачання.
- concept--supplier-advance | Попередня оплата постачальнику | Supplier prepayment | (term: аванс, передоплата; субрахунок 371) | Оплата до отримання товарів/послуг; не плутати з зарплатним авансом.
(No concept for каса / касовий ордер in the pack.)

C. PAYROLL [group «Розрахунок і виплата»]
- concept--accrual | Нарахування зарплати | Payroll accrual | зарплата; нараховано; заробітна плата (term: брутто) | Визначення сум, належних працівникові за видами виплат і періодами; не підтверджує переказ.
- concept--deduction | Утримання | Deduction | - | Сума, що зменшує до виплати; внесок роботодавця не є утриманням.
- concept--pdfo | Податок на доходи фізичних осіб | Personal income tax | ПДФО | База не завжди дорівнює всій сумі нарахувань.
- concept--military-tax | Військовий збір | Military levy | ВЗ | Окреме зобов'язання; правила і пільги ПДФО на нього не переносять.
- concept--esv | Єдиний соціальний внесок | Unified social contribution | ЄСВ; єдиний внесок | Внесок роботодавця з власною базою і межами; не віднімати від чистої зарплати.
- concept--benefit | Податкова соціальна пільга | Tax social benefit | ПСП | Зменшення бази ПДФО за умов; потрібні категорія, право, документи, граничний дохід.
- concept--average | Середня заробітна плата | Average earnings | - | Методика залежить від мети виплати (Порядок № 100 для відпусток, № 1266 для соцстраху); не «рік / 365».
- concept--provision | Забезпечення оплати відпусток | Leave provision | резерв відпусток | Облікова оцінка майбутніх витрат на відпустки; не банківський рахунок.
- concept--advance | Виплата за першу половину місяця | First-half payment | аванс | Частина зарплатного циклу; «50 % окладу» не універсальне правило.
- concept--net | Сума до виплати | Net payable | чиста зарплата; на руки (term: нетто) | Після утримань; залишок до перерахування ще враховує попередні виплати.
- concept--parameter | Параметр із датою дії | Effective-dated parameter | - | Значення з умовами, періодом дії, одиницею, джерелом; дата внесення не є датою чинності.
- concept--rule | Правило розрахунку | Calculation rule | - | Умови, входи, винятки, джерело; формула в коді не доказ юридичної правильності.
- concept--payslip | Розрахунковий листок | Payslip | (term: розрахунківка, розрахунковий лист) | Пояснення працівникові нарахувань, утримань, суми до виплати; не підтверджує банківську виплату.
- concept--report | Податковий розрахунок і додатки | Payroll tax reporting | Д1; 4ДФ; Д5; об'єднана звітність | Регламентований набір показників; файл, успішна перевірка XML і прийнятий звіт - різні стани.
- concept--receipt | Квитанція про обробку звіту | Submission receipt | - | Відповідь системи приймання; доставка не означає прийняття змісту.

D. HR, TIME AND ABSENCES [groups «Люди й умови праці», «Час і відсутності»]
- concept--employee | Працівник | Employee | - | Фізична особа як сторона трудових відносин; контакт, користувач, працівник, підрядник - різні ролі.
- concept--employment | Трудові відносини | Employment relationship | - | Зв'язок з умовами і періодом дії; зміни мають власні дати.
- concept--contractor | Підрядник | Contractor | ЦПХ; ФОП | Виконує роботи за цивільним договором; ЦПХ і договір з ФОП оподатковуються по-різному.
- concept--salary | Оклад | Base salary | ставка; тариф | Сума за норму праці; оклад, нараховано, до виплати - три показники.
- concept--order | Кадровий наказ | HR order | - | Управлінський документ з номером і життєвим циклом; не замінює заяву, табель, листок.
- concept--schedule | Графік роботи | Working schedule | - | Запланований розподіл часу, норма для порівняння з фактом.
- concept--timesheet | Табель робочого часу | Timesheet | - | Облік фактичної роботи і відсутностей; відсутність запису не означає нуль годин чи прогул.
- concept--leave | Щорічна відпустка | Annual leave | відпустки | Право, погодження, фактична відсутність і оплата - окремі об'єкти.
- concept--entitlement | Право і залишок відпустки | Leave entitlement | - | Належні, використані, скориговані дні за видами і робочими роками (робочий рік не календарний).
- concept--sick | Тимчасова непрацездатність | Sick leave | лікарняні; лікарняний | Період з власними підставами, правилами оплати і джерелами фінансування.

E. MILITARY RECORDS [group «Військовий облік»]
- concept--conscript | Призовник | Conscript | - | Особа на військовому обліку призовників.
- concept--military-liable | Військовозобов'язаний | Person liable for military service | - | Особа в запасі; категорія не встановлює факту служби чи придатності.
- concept--reservist | Резервіст | Reservist | - | Проходить службу у військовому резерві; не синонім «особи в запасі».
- concept--military-records | Військовий облік у роботодавця | Employer military records | - | Організація відомостей, документів і дій роботодавця.
- concept--military-category | Категорія військового обліку | Military registration category | - | Зберігають із джерелом і датою; не визначає придатність, бронювання чи службу.
- concept--military-document | Військово-обліковий документ | Military registration document | ВОД; е-ВОД; еВОД; Резерв ID | Зображення, результат перевірки і запис у реєстрі - різні об'єкти.
- concept--military-specialty | Військово-облікова спеціальність | Military occupational specialty | ВОС | Код і назва; не виводиться з цивільної професії.
- concept--military-rank | Військове звання | Military rank | - | Окремо від посади і спеціальності.
- concept--military-authority | Орган військового обліку | Military registration authority | ТЦК; ТЦК та СП; військкомат | Побутове «військкомат» не визначає актуальної назви органу.
- concept--military-booking | Бронювання працівника | Employee reservation | бронь; заброньований | Поданий список не підтверджує завершеного бронювання.
- concept--military-deferment | Відстрочка від призову під час мобілізації | Mobilization deferment | - | Різні підстави не зводити до прапорця «бронь».
- concept--military-service | Проходження військової служби працівником | Employee military service | - | Період з підставою і датами; виклик, категорія і служба - різні події.
- concept--service-release | Увільнення від роботи у зв'язку зі службою | Release from work for military service | (term: увільнення) | Не тотожне припиненню трудових відносин («увільнення» і «звільнення» не синоніми).
- concept--service-return | Повернення до роботи після служби | Return to work after service | - | Завершення служби і фактичний вихід можуть мати різні дати.
- concept--military-record-list | Список персонального військового обліку | Employer military registration list | - | Регламентований список за Порядком № 1487; внутрішня таблиця не підтверджує відповідності формі.
- concept--military-notification | Повідомлення у військовому обліку | Military registration notification | - | Підготовлений документ не означає, що відправлено або отримано.
- concept--military-reconciliation | Звіряння військово-облікових відомостей | Military record reconciliation | - | Розбіжність не усувати автоперезаписом останньою відповіддю.

F. VAT / TAX
- No concept entities for ПДВ. Tax content is in report forms (1.5 below) and concept--pdfo / military-tax / esv / benefit / report / receipt (listed under payroll).

G. STOCK / PRODUCTION
- ua:document:material-transfer | Передача матеріалів у виробництво | - | proposed internal example of a material movement document with quantity, unit, responsible identity.
- ua:field:material-quantity | Кількість переданого матеріалу | - | decimal; proposed mapping erpModule "komora", erpField "transfer.qty" (an Ephemeral mapping, not Odoo).
- ua:explainer:manufacturing | Матеріал → передача → випуск | - | separates receipt, transfer, consumption, output.
- ua:claim:primary-document | Реквізити первинного документа | - | record content, extent and unit, date, entity, responsible person.
- ua:review:primary-document | Черга фахової перевірки | pending.

1.3 TERMS (colloquial names and abbreviations; file entities/term--*.md)
- term--oborotka | Оборотка | variants: ОСВ, оборотно-сальдова відомість | Розмовна назва → trial-balance
- term--pervynka | Первинка | первинні документи | Розмовна назва → document
- term--debitorka | Дебіторка | дебіторська заборгованість | → receivable («хто і що винен нам»)
- term--kredytorka | Кредиторка | кредиторська заборгованість | → payable (клас 6, зокрема рахунок 63)
- term--platizhka | Платіжка | платіжна інструкція, платіжне доручення | → payment-instruction («платіжне доручення» is the historic name)
- term--rozrakhunkivka | Розрахунківка | розрахунковий листок, розрахунковий лист | → payslip
- term--na-ruky | На руки | чиста зарплата, нетто, net | → net
- term--brutto | Брутто | gross, грязними, до утримань | → accrual («Нараховано до утримань»)
- term--saldo | Сальдо | залишок | Фаховий термін → balance
- term--esv | ЄСВ | єдиний внесок | Скорочення → esv (full: Єдиний внесок на загальнообов'язкове державне соціальне страхування)
- term--pdfo | ПДФО | податок на доходи фізичних осіб | Скорочення → pdfo
- term--vos | ВОС | військово-облікова спеціальність | Скорочення → military-specialty
- term--vod | ВОД | е-ВОД, еВОД, військово-обліковий документ | Скорочення → military-document
- term--bron | Бронь | бронювання, заброньований | Розмовна назва → military-booking
- term--viiskkomat | Військкомат | ТЦК, ТЦК та СП | Розмовна назва → military-authority
- term--uvilnennia | Увільнення | увільнений від роботи | Фаховий термін → service-release
Four words with several meanings (kind «Кілька значень»):
- term--rakhunok | Рахунок | (1) Бухгалтерський рахунок («віднеси на рахунок 66»); (2) Банківський рахунок («дай рахунок для переказу»); (3) Рахунок на оплату («вистав рахунок клієнту»).
- term--avans | Аванс | (1) Зарплата за першу половину місяця; (2) Попередня оплата постачальнику (субрахунок 371).
- term--provesty | Провести | (1) Відобразити в обліку (сформувати записи); (2) Виконати платіж (банк провів).
- term--zakryty | Закрити | (1) Погасити заборгованість; (2) Завершити облік періоду («закрити місяць»); (3) Оформити документи про виконане («закрити актом»).

1.4 DOCUMENT TYPES (document--*; all in the sick-leave / payroll evidence chain)
- document--sick-record | Листок непрацездатності | family Підстава | external electronic record. Checks: відкритий запис не означає готовність до оплати; продовження не запускає перші п'ять днів повторно; медичний висновок і листок розрізняються.
- document--insurance-evidence | Відомості про страховий стаж | Підстава | form ОК-7 (data since 2011). Checks: стаж у роботодавця не підміняє страховий стаж; прогалини не дорівнюють нульовому стажу.
- document--time-record | Табель і відомості про відсутності | Облік часу | employer's form. Checks: ті самі години не враховані і як робота, і як відсутність; робочі години не підставлені замість календарних днів допомоги.
- document--sick-decision | Рішення про призначення страхової виплати | Рішення | Checks: є підстава і повноваження; дата рішення не підміняє дату випадку.
- document--sick-calculation | Розрахунок лікарняного | Розрахунок | internal. Checks: невідомі дані блокують висновок; межі та винятки перевірено до погодження; продовження прив'язане до попередніх днів.
- document--pfu-application | Заява-розрахунок до ПФУ | Фінансування | додаток 1 до Порядку № 28-1. Checks: не включено суму за рахунок роботодавця; повторне відправлення не створює друге фінансування; збережено відповідь.
- document--payment-evidence | Платіжна інструкція та підтвердження виконання | Виплата | Checks: надходження ПФУ не позначено виплатою працівнику; нарахована сума не підміняє суму переказу; часткове виконання залишає залишок.
- document--pfu-notice | Повідомлення про виплату страхових коштів | Звіт про виплату | додаток 2 до Порядку № 28-1. Checks: дата відповідає виконаній операції; суми звірені із заявою; збережено результат приймання.
- document--payslip-record | Розрахунковий листок працівника | Пояснення працівнику | Checks: страхова виплата не загублена у загальній сумі; нарахування, чиста сума й залишок до виплати розрізняються.
- document--correction-note | Пояснення та версія виправлення | Виправлення | fields: було / стало / різниця, залежні розрахунки, проводки, виплати, звіти. Checks: первісний результат не перезаписано без історії; виправлення розрахунку не виправляє поданий звіт.
- ua:document:material-transfer | Передача матеріалів у виробництво (see G above).

1.5 REPORT FORMS AND CODES
- ua.taxform.fop-single-tax.quarterly | Податкова декларація платника єдиного податку - фізичної особи - підприємця (3 група - квартальна) | form F0103309 (C_DOC F01, SUB 033, VER 9) | quarterly cumulative; registry deadline 40 calendar days after period end; MFU Order 578 as amended by 57 (effective 2025-02-20, reporting from 2025-04-01). Field entities (xml path): reporting_year HZY; taxpayer_name HNAME; taxpayer_id HTIN; employees HNACTL; activity_code T1RXXXXG1S; income_5pct R006G3 (row 06); tax_5pct R011G3 (row 11 = row 06 × 5%); previous_tax R013G3 (row 13 = previous-period row 12); military_levy R023G3 (row 23 = (05+06+07) × 1%). All mappingStatus proposed_not_implemented, filing_ready false.
- ua.taxform.vat-return.legal-entity | Податкова декларація з податку на додану вартість | form J0200126 (J02/001/26) | monthly; registry deadline 20 days after month; MFU Order 21 in edition of Order 400 (effective 2024-10-01). Fields: reporting_month HZM; entity_id HTIN; vat_id HNPDV (ІПН платника ПДВ); domestic_standard_base R11GA (row 1.1 A); domestic_standard_vat R11GB (row 1.1 B); purchase_credit R101GB (row 10.1 B); prior_negative_balance R161GB (row 16.1 = previous row 21). Out of scope named: F0200126 (individual variant), correction return J0217026, tax invoice registration.
- Both have artifact-package (ARJ with XSD + PDF, windows-1251, root DECLAR), explainer, review (requiredGates: source_verified, schema_compiles, field_mapping_verified, business_rules_expert_approved, transport_conformance_tested, release_approved).
- Other form codes mentioned only inside entities: Д1, 4ДФ, Д5 (aliases of concept--report, «Податковий розрахунок», Наказ № 4); ОК-7 (insurance record); додатки 1 і 2 Порядку ПФУ № 28-1; Порядок № 1487 lists (military); Порядок № 100 and № 1266 (averages).
- payroll_model reportingProfiles: legal entity - period «Місяць»; self-employed (ФОП) - «Квартал із помісячними показниками», quarterly form from 2026-08-01 (source--payroll-reporting-2026, source--payroll-report-form-2026).
- US-FED (not UA): form:us:irs:w9 (Form W-9, Rev. March 2024, 10 field entities), form:us:irs:1099-nec, release:iris:ty2025:v1.2.

1.6 RULES / CHECKS / CALCULATIONS (one line each)
Calculations:
- calculation--salary-time | Оклад за частину місяця | Оклад / норма годин × оплачувані відпрацьовані години (30 000 / 160 × 120 = 22 500).
- calculation--net-payment | Від нарахування до залишку виплати | Нараховано − утримання − уже виплачено = залишок (30 000 − 6 900 − 10 000 = 13 100).
- calculation--sick-basic | Лікарняний: середня, відсоток і дні | Включений дохід / календарні дні × відсоток × оплачувані дні (360 000 / 360 × 70% × 10 = 7 000).
Rules (UA):
- rule--net-bridge | Від нарахування до залишку | Чиста сума = нарахування − утримання; залишок = чиста − попередні виплати. Status: перевіряється арифметично.
- rule--average-selection | Вибір методики середньої | мета виплати → порядок → період → виплати й виключення → знаменник. Status: потребує фахової перевірки.
- rule--correction-trace | Збереження історії виправлення | первісний запис + причина + нова версія + різниця + зв'язки з наслідками.
Evidence rules (sick leave):
- evidence_rule--duration | Дні непрацездатності та відсоток оплати | стаж впливає на відсоток, не є лічильником днів.
- evidence_rule--percentage | Відсоток за загальним страховим стажем | до 3 років 50%; 3-5 60%; 5-8 70%; понад 8 100%.
- evidence_rule--recent-insurance | Стаж за останні 12 місяців | менше 6 місяців - обмеження, пов'язане з мінімальною зарплатою.
- evidence_rule--average-period | Період, дохід і календарні дні | 12 календарних місяців перед місяцем випадку; Порядок № 1266 (зміни 2026).
- evidence_rule--payer | Хто фінансує дні | перші 5 днів роботодавець, з 6-го ПФУ; продовження - той самий випадок.
- evidence_rule--forms | Фінансування і повідомлення | заява-розрахунок і повідомлення - окремі форми Порядку № 28-1.
Scenarios (test inputs for sick pay): scenario--ordinary «10 днів хвороби»; scenario--continuation «Продовження на 4 дні»; scenario--short-insurance «Менше 6 місяців стажу» (no total shown); scenario--unknown «Стаж не підтверджено» (calculation blocked).
Primary-document claims:
- law996.paper-or-electronic | Первинний документ: папір або електронна форма (ст. 9(2) Закону 996).
- law996.electronic-conditions | Умови електронного підтвердження (auto-generated e-documents need e-signature or seal).
- law996.customer-exception-2026 | Умовний виняток для реквізитів замовника (services/works/rentals, effective 2026-04-01, Law 4791-IX).
- law996.customer-exception-exclusions | Операції поза сферою винятку (public funds, state property leases, construction, charity).
- reg88.authentication-guidance | Положення 88: частково перевірена настанова (п. 2.4: signature, optional seal, facsimile limits).
- ua.primary-document.authentication.general.2026-04-01 | Первинні документи · підпис і винятки ("always print, hand-fill and wet-sign" is marked an unverified practice claim, not a legal requirement).
Procedures (each step has a named check):
- procedure--monthly-payroll | Зарплата за місяць | 10 steps: Умови й межі періоду → Час і відсутності → Окремі виплати та розрахункові випадки → Нарахування, утримання та внески → Перевірка й погодження → Відображення в бухгалтерському обліку → Пояснення працівнику й виконання виплат → Звітні показники, подання та результат → Звіряння й закриття місяця → Виправлення після закриття. Sample checks: «невідомий параметр не замінено нулем»; «ті самі години не обліковані одночасно як робота й відсутність»; «внесок роботодавця не віднято від чистої суми»; «Дебет дорівнює кредиту; підсумки за працівниками узгоджені з розрахунком»; «створений файл не позначений виплатою»; «кожна різниця має причину й відповідального».
- procedure--annual-leave | Щорічна відпустка | Право → наказ → розрахунок → виплата (5 steps; «робочий рік не замінено календарним», «немає автоматичного знаменника 365»).
- procedure--prior-correction | Помилка минулого періоду | Причина → різниця → облік → звітність (5 steps).
- procedure--military-hiring | Прийняття працівника; procedure--military-change | Зміна відомостей і звіряння; procedure--military-service-start | Початок служби посеред місяця; procedure--military-service-return | Повернення до роботи (3 steps each).
Models:
- payroll_model--payroll_model: stages with owner per stage (Кадровик / Бухгалтер із зарплати / Бухгалтер / уповноважений підписувач); 5 cases (Звичайний місяць, Початок служби, Повернення після служби, Пізній лікарняний, Зміна окладу й неповний місяць); state lists: Розрахунок [Чернетка, Перевірено, Погоджено, Замінено новою версією]; Облікові записи [Підготовлено, Проведено, Виправлено]; Платіж [Підготовлено, Передано, Виконано частково, Виконано, Відхилено]; Звіт [Підготовлено, Подано, Прийнято, Відхилено, Скориговано]; Період [Відкрито, На перевірці, Закрито, Виправлення в роботі]; dataModel entities employment-version, time-record, payroll-run, payroll-line, payment-allocation, report-submission, correction-case.
- military_model--military_model: field groups Особа й трудові відносини; Облікові відомості (category, registrationState, authority, specialtyCode, rank); Документ і перевірка (documentRef, documentType, issuedAt, checkedAt, checkedBy, verificationResult); Бронювання й відстрочка (basis, applicationState, decisionRef, validFrom, validTo, revokedAt); Служба й кадрові події (serviceFrom, serviceTo, releaseOrderRef, returnDate); Дії та історія. Rule: «Знятий і виключений з обліку не об'єднуються».
- evidence_model--evidence_model: bundles the 10 documents, 6 evidence rules, scenarios; legalReview pending, productionReady false.
Review tasks (open): review_task--sick-right, sick-limits, sick-forms, military-validation (priority «До робочого застосування»); sick-exceptions, leave, payroll-specials («Наступне розширення»).
Research (open questions): research--sick-validation, military-records (Зараз); annual-leave, employment-events, payroll-parameters, reference-data (Далі); reporting-payments, manufacturing (Пізніше).

1.7 Data domains and datasets (master-data reference)
data_domain--*: address (Адреси й території), delivery (Доставка й логістика), parties (Сторони й ідентифікація: ЄДР, КОПФГ, КВЕД, статус ПДВ/єдиний податок), money (Гроші й банківські реквізити: валюти, курси НБУ, банки, IBAN, SWIFT, рахунки для податків і ЄСВ, умови оплати), ledger (Бухгалтерський облік: нормативні плани рахунків, робочий план, аналітика, періоди, правила відображення), goods (Товари, послуги й активи: одиниці КСПОВО, УКТ ЗЕД, ДКПП, ДК 021, GTIN, номенклатура/партії/серії/склади, групи активів), military (Військовий облік роботодавця), people (Люди, праця й зарплата: ДК 003 професії, посади/штат, ознаки доходів і категорії осіб, робочі календарі, параметри, види відсутностей), reporting (Податки й звітність), document-trust (Документи й довіра), locale (Мова, контакти й час), public-data.
53 dataset--* entities (names in entities/dataset--*.md), e.g. coa-enterprise «План рахунків підприємств і організацій», coa-simplified, katottg, professions (ДК 003:2010), kved, kopfg, units (КСПОВО), uktzed, dkpp, nbu-rates, nbu-banks (RCUKRU), tax-registers, edr, report-forms (ДПС XSD), payroll-codes, tax-accounts, budget-codes, tax-deadlines, work-calendar-rules, payroll-parameters, military-forms/specialties/categories-ranks/document-access/booking-service, nova-poshta, ukrposhta-addresses, iban-format, gs1.
Sources worth knowing by id: source--accounting-law (Закон 996-XIV), source--chart (Інструкція № 291), source--standard10/26/6 (НП(С)БО), source--tax-code, source--esv-law (2464-VI), source--wage-law, source--labor-code, source--leave-law, source--average-100, source--average-1266, source--wartime (2136-IX), source--report-order (Наказ № 4), source--military-order (Порядок № 1487), source--military-document-order (Постанова № 559), source--military-specialties-order (Наказ МОУ № 317), source--payment-law (1591-IX), source--payment-instruction (НБУ № 163), plus source--odoo, source--oca, source--bas, source--bas-hr (product references).

====================================================================
2. EPHEMERAL
====================================================================
Docs: /Users/kit/Codius/ephemeral/docs/{layers,modules,erp-kernel-spec,v0-scope,DEPLOYMENT}.md (main checkout) and /Users/kit/Codius/ephemeral/.worktrees/all/docs/ {words.md, documents.md, ownership.md, modules.md, layers.md, api.md, sandbox.md, labs.md, testing.md, questions-deals.md, questions-floor.md, questions-keys.md, testing/words.md, testing/pages-truth.md, demo/world.md, demo/names.md, demo/complex.md, demo/complex.json, demo/documents-spec.md, demo/sources.md, demo/nbu-rates.json}.

2a. Document types with Ukrainian names
Numbered series (format «ВН-2026-00001», gapless within a calendar year):
- РН invoice / рахунок (workers/invoicing/src/index.ts); ВН shipment / видаткова накладна; ПП customer_return / повернення від покупця; АВ advance / аванс (workers/prodazh/src/index.ts, hroshi)
- ВХ bill / рахунок постачальника (workers/expenses); ПВ supplier_return / повернення постачальнику; ВКО cash_payment / видатковий касовий ордер (ПКО for receipt); АЗ expense_report / авансовий звіт (workers/hroshi); МД import_declaration / митна декларація (workers/valyuta)
- ЗК замовлення покупця (sales_order); ЗТ запит (request); ЗЯ заявка на закупівлю (purchase_request); ЗП замовлення постачальнику (purchase_order); ВЗ виробниче замовлення (production_order); ЗМ зміна специфікації / change order (workers/gate/src/index.ts)
- Event series in packages/pack-ua/src/documents/numbering.ts: ПО прибутковий ордер; ВП накладна-вимога на внутрішнє переміщення; НВ накладна-вимога на відпуск у виробництво; АС акт списання запасів; ІН результат інвентаризації (нестача / надлишок); ВГП звіт про випуск продукції. File comment: "AN ACCOUNTANT MUST CONFIRM the letters".
Printable forms implemented (docs/documents.md; registry packages/pack-ua/src/documents/registry.ts): рахунок на оплату; акт наданих послуг (виконаних робіт); видаткова накладна; акт приймання-передачі продукції (із серійними номерами); податкова накладна / розрахунок коригування (ПН / РК; XML draft J1201016, F1201016 for ФОП); прибуткова накладна / прибутковий ордер (М-4); накладна на внутрішнє переміщення; накладна-вимога (М-11); акт списання; інвентаризаційний опис запасів; звіт про випуск продукції; прибутковий (КО-1) і видатковий (КО-2) касовий ордер; товарно-транспортна накладна (1-ТН); паспорт виробу; протокол приймально-здавальних випробувань (ВТК); пакувальний лист; відомість комплектації; etykety (серійного номера, партії, на коробку, на полицю).
Full paper-form spec with 31 forms, requisites, column headings, copies, legal basis: docs/demo/documents-spec.md (adds лімітно-забірна картка М-8, довіреність на отримання цінностей, формуляр комплексу, відомість ЗІП, маршрутний лист, картка дефекту, комплектувальна відомість, замовлення постачальнику, картка імпортної поставки, рекламаційний акт). It states which are approved typical forms (податкова накладна - наказ 1307; 1-ТН; КО-1/КО-2 - постанова НБУ № 148; інвентаризаційний опис - наказ 572) and which are free forms; М-4/М-8/М-11 are repealed typical forms printed as own blanks without the word «Типова».
VAT total wording, three variants per document (documents-spec.md §1): «З ПДВ 20 %» → «Разом без ПДВ:», «ПДВ 20 %:», «Усього з ПДВ:»; «Без ПДВ (неплатник)» → «Усього (без ПДВ):»; «Без ПДВ (звільнено від оподаткування)» → with mandatory «Підстава звільнення».
Module names (Ukrainian, used as menu): Довідник, Комора, Збірка (специфікації, виробництво, план), Закупка/Закупівля, Продаж/Продажі, Гроші (Платежі, Одержувачі, Стрічка банку, Касова книга), Активи й закриття, Валюта, Перенесення (вхідні залишки), Зарплата, Витрати, Податки, Обладнання та інструмент, Якість, Звіти, Слід (хроніка), Люди.

2b. Master / sample data and where it lives
- Demo company world: docs/demo/world.md (story), docs/demo/complex.json + complex.md (products, routes, workplaces), docs/demo/names.md (name table and checks), docs/demo/sources.md, docs/demo/nbu-rates.json.
- Code: workers/web/src/seed.ts (basic seed), workers/web/src/demo/{names.ts, demokrylo.ts, sandbox.ts, people.ts, kit.ts, runner.ts}, workers/web/src/demo/world/{cast.ts, data.ts, loader.ts, sim.ts, mistakes.ts, people.ts, floor.ts, asks.ts}; scripts/{seed-remote.mjs, prepare-demo.mjs, rename-demo.mjs, check-demo-data.mjs, build-demo-doc.mjs, simulate.mjs, simulate-rates.mjs}.
- Company: ТОВ «Крило і Гвинт» (Львів, drones), ЄДРПОУ 99000011, ІПН 990000113011. 16-17 counterparties with roles (4 buyers incl. charity fund, state customer, military unit А0000 as recipient; UA suppliers; 2 import suppliers in USD/EUR; landlord, carrier, tool supplier, metrology, electricity; «Вербівська митниця»; unknown payer «Сьомий Меридіан»). 5 made-up banks.
- Loaded before day one: 430 items with unit and stock account; 331 manufacturer P/N; 331 supplier prices with lead time; 63 analogs; 99 specifications; 221 route operations; 11 workplaces; 310 equipment units; 12 quality checklists (181 points); 20 glossary terms; company requisites and tax regime; bank account; warehouse with cells and a production site; founders' contribution 24 000 000 грн as the only opening balance; payroll parameters.
- Each counterparty has a tax regime and dated requisites for printed forms: full name, address, bank, signatory with position and basis. Payment receivers: supplier account, each employee's РНОКПП and account, a budget account per tax.
- Company profile fields (docs/documents.md): legalName, shortName, registrationNumber (ЄДРПОУ), vatNumber (ІПН платника ПДВ), legalAddress, iban, bankName, directorName, directorPosition, accountantName, accountantPosition, phone, email; checks: ЄДРПОУ 8 digits with check digit, ФОП 10 digits, ІПН 12/10 digits, IBAN UA + 27 digits mod 97.
- 18 people, each chosen to exercise a payroll case (world.md «Люди»): директорка; головний бухгалтер (стаж 12 років); заброньований; податкова пільга на дитину; лікарняний; відпустка на межі двох місяців; пенсіонер; третя група інвалідності; мобілізований (місце збережено); сумісництво пів ставки, дні без збереження зарплати; цивільно-правовий договір; догляд за хворою дитиною; звільнення; лікарняний в останній день.
- Daily simulation (9 months, 195 working days; 5 573 events, 5 511 entries, 79 customer orders, 102 purchase orders, 33 imports with customs declaration, 753 bank lines, 9 closed months, October left open).
- "Planted mistakes" table (world.md «Підкладені помилки»): stock count mismatch, bill posted to wrong expense account (92 → сторно → 93), rent paid twice (becomes аванс 371), defective batch return with розрахунок коригування, payment with wrong amount rejected, unknown payer in statement, leave entered with wrong dates, duplicate customer order, late-paying customer, etc., each with the page where it shows.
- "Open month" state left on purpose: unapproved payments, unposted statement line, import in transit, a change waiting for the second person, a person on sick leave.
- Markers of made-up data (names.md): ЄДРПОУ in 99000000-99999999, ІПН starting 99, bank code 399990-399994 in IBAN, phones with group 000, streets Зразкова/Прикладна/Учбова/Модельна, mail in .example; every printed sheet on a non-production install carries «навчальні дані». Names were changed from «Демо…» to ordinary names, each checked against YouControl for collisions with real entities.

2c. UI / interaction principles (with sources)
Naming and text placement (docs/words.md, §«Where a text stands»):
- title/label/column names the thing, one phrase; button is a verb saying what happens; empty-state is one sentence saying what is empty.
- Date in tables «07.10.2026», in a sentence «7 жовтня 2026», never «2026-10-07». Money «1 234,56» with narrow space, minus «−»; units as short words (шт, кг, год).
- A stored code is shown as its word («відвантаження», not shipment).
- Explanation opens on demand behind "?" (page lead, form note, block help), never stands on the screen.
- Refusal format: one sentence, lowercase start, no full stop: what is wrong, colon, what to do: «період закрито: оберіть дату у відкритому місяці або відкрийте цей». No «Помилка:», no English, no code, no exclamation mark. Database trigger messages are translated in one table (packages/kernel/src/refusals.ts).
- Result line: «готово» / «не проведено»; «успішно» / «помилка» are not used for business outcomes.
Navigation and forms (docs/testing.md §«Forms», docs/modules.md §6b, §6e):
- An action bar under the page title lists what the person may run now, main action first, rare ones under «Ще»; a button opens its form in place; address carries ?do=<action>.
- Pickers narrow as you type; «Шукати ще…» widens; «Створити «…»» creates the typed thing where allowed; line editors with «Додати рядок» / «Прибрати»; a refused save keeps what was typed and shows the refusal at its field.
- Result line with the document, link «Що записано» (trace of what the action wrote) and an undo step.
- «Журнал» drawer: a button on every page opens the ledger as a side panel, contextual to the open counterparty, without leaving the page.
- Per-view field customization «Налаштувати»: drag to reorder/hide columns and fields; «Зберегти тільки для мене» / «Зберегти для всіх».
- From the Odoo norm that Ephemeral adopts (odoo-live-show/docs/payroll/words.md, «Три слова про те, де що відкривається»): menu item opens a page, never a dialog; a dialog is a one-off action with 1-3 fields; anything with a period and lines is a document with its own list, «Створити за місяць», then «Заповнити», «Затвердити», «Друк». Checked by scripts/views_check.py in the Odoo repo.
Explaining how things are calculated:
- «Показати, що буде записано» = trial run of a form: lists documents and entries the action would write, nothing saved (docs/words.md; API dry run in docs/api.md §4 returns one sentence per write, e.g. «Проводка «Прихід MOT-2207 × 10 → W1»: Дт 281 Кт 631 12 005,00; Дт 644 Кт 631 2 401,00» plus every ledger line with account name).
- Blocks titled «Як пораховано» / «Як пораховано завантаження» exist in module pages.
- Payroll people are chosen so each payslip shows one rule (world.md «Що перевіряє в розрахунку»).
Checks before posting / closing:
- Month-close checklist, conditions named by the country pack (packages/pack-ua/src/close.ts), labels: «Відвантаження й аванси без податкової накладної»; «Податкові накладні, не зареєстровані в строк»; «ПДВ-зобов'язання: реєстр накладних і книга, різниця»; «Податковий кредит: реєстр накладних і книга, різниця»; «Рядки виписки без проведення»; «Платежі, які банк ще не виконав»; «Зарплату за місяць не нараховано: людей»; «Податки за місяць не нараховано»; «Основні засоби без амортизації за місяць»; «Незавершене виробництво: залишок рахунку 23»; «Загальновиробничі витрати не розподілено: залишок рахунку 91»; «Рахунки запасів, що не збігаються зі складом по місцях»; «Збережені залишки запасів, що не збігаються з рухами в книзі»; «Валютні залишки без переоцінки на кінець місяця». The close reads them inside the same batch (docs/ownership.md §«Closing a period»); after close the database refuses any entry dated in the period.
- Second-person approval: payments (бухгалтер готує, директорка затверджує), specification changes, new counterparties; AI/agent proposals never post, a human approves and the ordinary action runs (docs/modules.md §6a).
- Tax warnings (docs/modules.md §6g): group-2 ФОП selling to general-system counterparty; income vs group limit with percent used; non-payer above 1 000 000 грн in 12 months.
- Unposted document prints with «ЧЕРНЕТКА»; a document with an empty mandatory requisite does not print as final and the screen lists what is missing; reversed posting prints «Сторновано» (documents.md, documents-spec.md rule 42).
- One fact has one owner (docs/ownership.md): reserved quantity, production progress, workplace state are computed, not stored.
- Requisites are dated: a document prints with the requisites valid on its date (docs/documents.md).
Other: roles are Ukrainian job words (Перегляд, Комірник, Продажі, Закупівля, Виробництво, Бухгалтер, Головний бухгалтер); sandbox (docs/sandbox.md) offers a visitor a role and tasks («Почати», «зроблено / не зроблено / чекає оновлення», «Мої дії»); questions for the accountant are kept as files (docs/questions-deals.md, questions-floor.md, questions-keys.md) and undecided rules refuse rather than guess (e.g. «безоплатну передачу не відвантажують як продаж: правило проведення має затвердити бухгалтер»).
Automated word check: scripts/check-words.mjs (port of odoo-live/scripts/words_check.py), rules: replaced, first-person, filler, explanation, synonym, colloquial (оборотка, платіжка where «Лад» names the term), ambiguous (one-word button with several meanings in «Лад»), not-a-verb, gender, caps, exclamation, long-dash, mixed-script, english, code-in-text. Report: docs/testing/words.md (8 835 strings, 0 findings; button verb counts: Зберегти 26, Створити 19, Записати 18, Провести 13, Скасувати 10, Додати 9, Затвердити 8...).

2d. Explicit Ukrainian terminology decisions (docs/words.md; "Not" column = words rejected)
Actions:
- Створити = new standalone record (not Додати, Завести, Сформувати, Скласти). Form title is a noun: «Нова заявка», «Новий рахунок».
- Додати рядок / пункт / операцію / аналог / роль / версію = add a part to an open record; never a bare «Додати».
- Редагувати (not Змінити, Правити, Виправити, Оновити, Коригувати). Зберегти for an edit form.
- Записати = write down a fact that happened outside the system: payment, price, protocol, timesheet, supplier's bill or tax invoice (not Внести, Зареєструвати).
- Провести = post to the ledger, and the button says what: «Провести рядок», «Провести рахунок»; a bare «Провести» is banned because «Лад» lists several meanings.
- Затвердити = authorised yes (not Підтвердити, Погодити). Відхилити = no to someone else's draft. Скасувати = author stops a not-executed document (not Відмінити, Видалити). Сторнувати = reverse a posted entry. Прибрати = take off a list, record stays (nothing is «Видалити»).
- Позначити надісланим / зареєстрованою = record an outside fact without fields.
- Підготувати платіж; Закрити період / Закрити журнал (never bare «Закрити»); Зареєструвати only for ЄРПН; Друк, Перерахувати, Заповнити (not Надрукувати, Порахувати, Наповнити).
Objects and states:
- запит (before an order) vs заявка (purchase request only); угода = customer order seen end to end; платник, одержувач, хто підписує (not підписант); безоплатна передача (not подарунок, благодійність); «стоїть» for a blocked stage (not заблоковано).
- Paper steps: складено, надіслано, підписано і повернуто, відмова підписати.
- States: чернетка, чинна, затверджено, на розгляді, відхилено, виведено з ужитку; «підтвердити» only in explanations.
- People columns: Автор; «Затвердження: хто», «Видача: хто» (step noun + хто) to avoid gendered past tense; chronicle in impersonal form «комірник: прийнято 200 шт».
- Technical words translated: ключ запиту (idempotency key), супутній запис, передача (outbox), «не змінюють і не видаляють» (append-only), «такого кроку немає».
- пісочниця vs демо; навчальна компанія; «навчальні дані» mark on prints.
Seven rules of the norm (odoo-live-show/docs/payroll/words.md): name the thing not the impression; no «ми»; no explanations standing on the screen; one word one meaning (e.g. «Папери» for printed forms vs «Документи» for employee documents); short and verb-first buttons; no gender where unknown; no capitals or «Важливо!». Replacement table included there (e.g. «Скласти чернетку» → «Створити», «Правити рядки» → «Редагувати», «Друк пакета» → «Друк усіх»).
Print conventions (documents-spec.md §3, documents.md): Ukrainian only on paper, quotes «», short forms грн, коп., шт, ПДВ, ЄДРПОУ, ІПН, р.; sum in words (hryvnias in words, kopiykas in digits); basis line «договір № 12 від 1 вересня 2026 р.»; buyer without ІПН printed as «Неплатник», ІПН 100000000000; no seal required, «М.П.» only as a place mark on some forms.

====================================================================
3a. /Users/kit/Codius/Keeper/INTERACTION.md (2026-10-03, "use for ... the ERP work")
====================================================================
1. The model fills, the person confirms: a screen opens pre-filled; certain items are saved without a click, one notice says how many, one undo brings them back.
2. One thing at a time, one decision; all questions about a thing on one screen with the suggested answer preselected; Enter accepts.
3. Show confidence as a number; a low one turns the row yellow.
4. Pick, do not type: buttons from what already exists; text fields only for free values. No native dropdowns: few options are a row of buttons, many are a list narrowed by typing 2-3 letters then Enter ("the way search works in an ERP").
5. Suggest from existing records first; hold a value for the next items (lock).
6. The screen stays still: rows keep order and height, one record is one form, a fact appears once; status is one quiet line; hints sit on their control.
7. Plain names for places in the app («Розібрати», «Речі»); a word from data is never inflected, it stands after a colon («стан: робочий»).
8. A kind of fact keeps one colour; only one dark (primary) button per screen.
9. Keyboard: six actions everywhere (arrows, confirm, back); letter shortcuts written on the control; "?" lists keys; mouse is last resort.
10. Mistakes are cheap: undo everything, no "are you sure?", drafts kept. Tables: edit in place, sticky header and name column, filter by chips with counts and sums, group with subtotals. Check a change by keyboard-only run, do-and-undo, and opening three records to see nothing moves.

====================================================================
3b. /Users/kit/Codius/oopskit-context/odoo/odoo-work-summary.md (dated 2026-09-25)
====================================================================
1. Seven private repos under workflowcat; `odoo-live` is the core: Ukrainian back office on Odoo 19 Community (payroll/HR, accounting with VAT, bank and cash, fixed assets, financial reports, primary docs, FOP, purchase intake, KYC/EDR, stock, MRP).
2. Stated approach: native Odoo first, then OCA 19.0 unchanged, then thin l10n_ua_* modules; plain Odoo UI.
3. Demo DB `demo` on Mac port 8131 with 3 companies: Ясен Меблі (furniture), Ясен Логістика, АероСіч (drones).
4. `odoo-ui` is the UI lab working over the core's docs/api contract (site odoo-lab.pages.dev: mockups, warehouse client /app, 1С look-alike /variants/onec, /scan invoice reading).
5. `dronebuild-erp` (Odoo 18 sandbox) archived 2026-09-22 and moved into odoo-live; `odoo-map` and `odoo-core-map` are static reference sites; `odoo-team-plan` is the client plan (8 weeks); `odoo-demo-link` gives a stable link via tunnel.
6. Done: real Odoo tests and golden payroll numbers; demo builders for two companies with three months of data (payroll, purchases incl. import with customs VAT, MRP with serials and work orders, sales, bank, cash, assets).
7. Core/UI split with file-based agent protocol (docs/agents, agent_note.py) and API contract (docs/api, ua.api calls warehouse_map, stock_glance, floor_packages).
8. Open: Hetzner staging/prod server (docs/base/environments.md), waiting on the VM.
9. Open UI fixes from lab review: company passed per request (wrong-company data under concurrency), shared tokens and terms, scope marker, barcode input, phone layout, offline queue, fail fast.
10. Open core requests: scenario seeding S1-S5, Europe/Kyiv timezone for demo users, kiosk "who did the work order"; next step named there was a D1 sandbox with the same two companies.

FILES MOST USEFUL FOR THE WORDING TASK
- /Users/kit/Codius/odoo-live-show/docs/payroll/words.md (the norm; already in this repo)
- /Users/kit/Codius/ephemeral/.worktrees/all/docs/words.md (product word list with rejected synonyms)
- /Users/kit/Codius/odoo-live-show/reference/erpkit/erpkit-2026-10-07/entities/term--*.md (20 colloquial/ambiguous terms) and concept--*.md (65 concepts with "distinction" lines)
- /Users/kit/Codius/ephemeral/.worktrees/all/docs/demo/documents-spec.md (exact Ukrainian headings of 31 paper forms)
- /Users/kit/Codius/ephemeral/.worktrees/all/packages/pack-ua/src/close.ts (month-close check labels), .../documents/numbering.ts and registry.ts (series and form names)
- /Users/kit/Codius/ephemeral/.worktrees/all/docs/demo/world.md and names.md (demo data design)